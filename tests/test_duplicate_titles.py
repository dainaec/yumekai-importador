import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from time import monotonic
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from yumekai_importer.catalog.duplicate_titles import duplicate_title_key, find_duplicate_titles
from yumekai_importer.ui.styles.theme import apply_light_theme
from yumekai_importer.ui.widgets.duplicate_titles_dialog import DuplicateTitlesDialog
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from tests.test_review_workflow import FakeApi, product


FIRST = '9788419914163'
SECOND = '9791370138479'
THIRD = '9788412930627'
FOURTH = '9791399163087'


class DuplicateTitleRulesTests(unittest.TestCase):
    def test_full_title_matches_across_isbns_publishers_and_lists(self):
        rows = {FIRST: product(FIRST, '  ÁRBOLES   DEL MAR 01 '),
                SECOND: product(SECOND, 'Arboles\u00a0del mar 01', status='ready_to_upload', publisher='Otra editorial'),
                THIRD: product(THIRD, 'Árboles del mar 02')}
        groups = find_duplicate_titles(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0].keys), {FIRST, SECOND})

    def test_accents_decomposed_unicode_and_whitespace_do_not_split_a_group(self):
        self.assertEqual(duplicate_title_key('  A\u0301RBOL\tDEL\nMAR '), 'arbol del mar')
        self.assertEqual(duplicate_title_key('ＡＲＢＯＬ DEL MAR'), 'arbol del mar')

    def test_volume_numbers_subtitles_and_edition_labels_are_preserved(self):
        rows = {str(i): {'title': title} for i, title in enumerate([
            'Serie 01', 'Serie 02', 'Serie 1', 'Serie 01 - Edición especial',
            'Serie 01 - Otro subtítulo', 'Serie 01: Otro subtítulo',
        ])}
        self.assertEqual(find_duplicate_titles(rows), ())

    def test_blank_titles_are_not_duplicates_and_input_is_not_modified(self):
        rows = {'a': {'title': None}, 'b': {'title': ''}, 'c': {'title': '  '}, 'd': {'title': 'Único'}}
        self.assertEqual(find_duplicate_titles(rows), ())
        self.assertIsNone(rows['a']['title'])

    def test_groups_are_deterministic_and_keep_original_record_keys(self):
        rows = {'original-z': {'isbn': 'nuevo-z', 'title': 'Zeta'},
                'original-a': {'isbn': 'nuevo-a', 'title': 'ZETA'},
                'otro-b': {'title': 'Beta'}, 'otro-a': {'title': 'BETA'}}
        groups = find_duplicate_titles(rows)
        self.assertEqual([group.title_key for group in groups], ['beta', 'zeta'])
        self.assertEqual(groups[1].keys, ('original-a', 'original-z'))


class DuplicateTitleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        apply_light_theme(cls.app)

    def setUp(self):
        self.api = FakeApi([
            product(FIRST, '  ÁRBOLES   DEL MAR 01 '),
            product(SECOND, 'Árboles del mar 01', status='ready_to_upload', publisher='Otra editorial'),
            product(THIRD, 'Árboles del mar 02'),
        ])
        self.window = PendingReviewWindow()
        self.window._api_override = self.api
        self.window._load_pending()
        self.wait_finished()

    def tearDown(self):
        self.wait_finished()
        self.window._drafts.clear()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait_finished(self):
        until = monotonic() + 3
        while self.window._busy and monotonic() < until:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.window._busy)

    def in_duplicates(self, action):
        errors = []
        def run():
            dialog = self.window._duplicates_dialog
            try:
                self.assertIsInstance(dialog, DuplicateTitlesDialog)
                action(dialog)
            except BaseException as error:
                errors.append(error)
            finally:
                self.wait_finished()
                dialog.reject()
        QTimer.singleShot(0, run)
        self.window._show_duplicates()
        self.assertIsNone(self.window._duplicates_dialog)
        if errors:
            raise errors[0]

    def choose_confirmation(self, label):
        def choose():
            box = QApplication.activeModalWidget()
            self.assertEqual(box.windowTitle(), 'Confirmar borrado')
            self.assertIn(FIRST, box.detailedText())
            self.assertIn(SECOND, box.detailedText())
            for button in box.buttons():
                if button.text() == label:
                    button.click()
                    return
            box.reject()
            raise AssertionError(label)
        QTimer.singleShot(0, choose)

    def test_button_opens_all_matches_even_when_main_filters_hide_them(self):
        self.window._search.setText('02')
        self.window._publisher_filter.setCurrentIndex(self.window._publisher_filter.findData('Milky Way'))
        self.assertEqual(self.window._duplicates_button.text(), 'Ver duplicados (1)')
        def check(dialog):
            self.assertEqual(set(dialog._keys), {FIRST, SECOND})
            self.assertEqual(dialog._selected, set())
            self.assertFalse(dialog._delete_button.isEnabled())
            captions = {caption: column for column, (_, caption, _) in enumerate(dialog._columns)}
            labels = {dialog.table.item(row, captions['Lista']).text() for row in range(2)}
            self.assertEqual(labels, {'Por revisar', 'Listas para subir'})
            self.assertIn('Sinopsis', captions)
            self.assertIn('Formato', captions)
            self.assertTrue(all(dialog.table.item(row, captions['Coincidencias']).text() == '2' for row in range(2)))
        self.in_duplicates(check)
        self.assertEqual(self.window._search.text(), '02')
        self.assertEqual(self.api.calls, [])

    def test_every_cell_can_open_the_correct_record_in_the_other_list(self):
        def check(dialog):
            row = dialog._keys.index(SECOND)
            for column in range(dialog.table.columnCount()):
                with patch('yumekai_importer.ui.windows.pending_review_window.ProductReviewDialog') as factory:
                    factory.return_value.exec.return_value = QDialog.DialogCode.Rejected
                    factory.return_value.changes = {}
                    factory.return_value.ready_to_upload = True
                    dialog.table.doubleClicked.emit(dialog.table.model().index(row, column))
                    self.assertEqual(factory.call_args.args[0]['isbn'], SECOND)
                    self.assertTrue(factory.call_args.kwargs['reviewed'])
                    self.assertIs(factory.call_args.args[3], dialog)
        self.in_duplicates(check)
        self.assertEqual(self.api.calls, [])

    def test_edit_saves_from_the_duplicate_dialog_preserves_list_and_refreshes_groups(self):
        def check(dialog):
            dialog.table.setCurrentCell(dialog._keys.index(SECOND), 1)
            with patch('yumekai_importer.ui.windows.pending_review_window.ProductReviewDialog') as factory:
                factory.return_value.exec.return_value = QDialog.DialogCode.Accepted
                factory.return_value.changes = {'title': 'Árboles del mar 01 - Otra edición'}
                factory.return_value.ready_to_upload = True
                dialog._edit_button.click()
            self.wait_finished()
            self.assertEqual(self.api.rows[SECOND]['title'], 'Árboles del mar 01 - Otra edición')
            self.assertEqual(self.api.rows[SECOND]['review_status'], 'ready_to_upload')
            self.assertEqual(dialog.table.rowCount(), 0)
            self.assertIn('No hay títulos duplicados', dialog._summary.text())
            self.assertIn('guardadas', dialog._feedback.text())
            self.assertEqual(self.window._duplicates_button.text(), 'Ver duplicados (0)')
        self.in_duplicates(check)
        self.assertEqual(self.window._drafts, {})

    def test_batch_delete_cancel_then_confirm_only_deletes_checked_records_in_both_lists(self):
        def check(dialog):
            dialog._select_button.click()
            self.assertEqual(dialog._selected, {FIRST, SECOND})
            self.choose_confirmation('Cancelar')
            dialog._delete_button.click()
            self.assertEqual(self.api.calls, [])
            self.assertEqual(set(dialog._keys), {FIRST, SECOND})
            self.choose_confirmation('Borrar fichas')
            dialog._delete_button.click()
            self.wait_finished()
            self.assertEqual(set(self.api.rows), {THIRD})
            action, entries = self.api.calls[-1]
            self.assertEqual(action, 'delete')
            self.assertEqual({entry['original_isbn'] for entry in entries}, {FIRST, SECOND})
            self.assertEqual({entry['expected_review_status'] for entry in entries},
                             {'pending_review', 'ready_to_upload'})
            self.assertTrue(all(entry['expected_revision'] == 'a' * 64 for entry in entries))
            self.assertEqual(dialog._selected, set())
            self.assertEqual(dialog.table.rowCount(), 0)
        self.in_duplicates(check)

    def test_search_hides_whole_groups_and_clears_checks_before_deleting(self):
        other = product(FOURTH, 'Otra obra')
        self.window._products['pending_review'][FOURTH] = other
        self.window._products['pending_review'][THIRD]['title'] = 'OTRA OBRA'
        self.window._fill_tables()
        def check(dialog):
            dialog._select_button.click()
            self.assertEqual(len(dialog._selected), 4)
            dialog._search.setText('árboles')
            self.assertEqual(set(dialog._keys), {FIRST, SECOND})
            self.assertEqual(dialog._selected, set())
            self.assertFalse(dialog._delete_button.isEnabled())
        self.in_duplicates(check)

    def test_failed_edit_keeps_draft_visible_and_can_be_saved_again_in_the_dialog(self):
        self.api.fail = True
        def check(dialog):
            with patch('yumekai_importer.ui.windows.pending_review_window.ProductReviewDialog') as factory:
                factory.return_value.exec.return_value = QDialog.DialogCode.Accepted
                factory.return_value.changes = {'author': 'Autora corregida'}
                factory.return_value.ready_to_upload = True
                dialog._edit_index(dialog.table.model().index(dialog._keys.index(SECOND), 1))
            self.wait_finished()
            self.assertIn(SECOND, self.window._drafts)
            self.assertIn('Sin conexión', dialog._feedback.text())
            self.assertTrue(dialog._save_button.isEnabled())
            self.assertTrue(dialog._save_button.isVisible())
            self.assertEqual(len(dialog._keys), 2)
            self.api.fail = False
            dialog._save_button.click()
            self.wait_finished()
            self.assertEqual(self.api.rows[SECOND]['author'], 'Autora corregida')
            self.assertEqual(self.window._drafts, {})
            self.assertFalse(dialog._save_button.isVisible())
        self.in_duplicates(check)

    def test_empty_results_stay_usable_and_busy_actions_cannot_close_the_dialog(self):
        self.window._products['ready_to_upload'][SECOND]['title'] = 'Título diferente'
        self.window._fill_tables()
        def check(dialog):
            self.assertEqual(dialog.table.rowCount(), 0)
            self.assertFalse(dialog._delete_button.isEnabled())
            self.assertFalse(dialog._edit_button.isEnabled())
            dialog.set_busy(True)
            dialog.reject()
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog.close())
            dialog.set_busy(False)
        self.in_duplicates(check)


if __name__ == '__main__': unittest.main()
