import copy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from yumekai_importer.storage.catalog_api import CatalogRequestError
from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup
from yumekai_importer.storage.review_saving import save_review_drafts
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from tests.test_review_workflow import FakeApi, product

FIRST, SECOND = '9788419914163', '9791370138479'


class ConflictingApi(FakeApi):
    def review_products(self, action, entries):
        if action == 'save' and any(entry['original_isbn'] == SECOND for entry in entries):
            raise CatalogRequestError('La ficha ya no existe en el importador.', 409)
        return super().review_products(action, entries)


class SaveBatchTests(unittest.TestCase):
    def test_one_rejected_draft_does_not_block_the_other_1040(self):
        class Api:
            calls = 0
            def review_products(self, action, entries):
                self.calls += 1
                if any(row['original_isbn'] == '520' for row in entries):
                    raise CatalogRequestError('Ficha con conflicto', 409)
                return {'saved': [{'original_isbn': row['original_isbn'], 'product': {}} for row in entries]}
        api = Api()
        result = {'saved': [], 'failed': []}
        save_review_drafts(api, [{'original_isbn': str(i)} for i in range(1041)], result)
        self.assertEqual(len(result['saved']), 1040)
        self.assertEqual([row['original_isbn'] for row in result['failed']], ['520'])
        self.assertLess(api.calls, 30)

    def test_network_ambiguity_stops_without_resubmitting_confirmed_rows(self):
        class Api:
            calls = []
            def review_products(self, action, entries):
                self.calls.append([row['original_isbn'] for row in entries])
                if len(entries) == 4:
                    raise CatalogRequestError('Conflicto', 409)
                if entries[0]['original_isbn'] == '2':
                    raise ValueError('Conexión interrumpida; resultado sin confirmar')
                return {'saved': [{'original_isbn': row['original_isbn'], 'product': {}} for row in entries]}
        api = Api()
        result = {'saved': [], 'failed': []}
        with self.assertRaisesRegex(ValueError, 'sin confirmar'):
            save_review_drafts(api, [{'original_isbn': str(i)} for i in range(4)], result)
        self.assertEqual([row['original_isbn'] for row in result['saved']], ['0', '1'])
        self.assertEqual(len(api.calls), 3)


class SaveUiAndBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = ReviewDraftBackup(Path(self.temp.name) / 'pending.json')
        self.api = ConflictingApi([product(FIRST), product(SECOND)])
        self.window = PendingReviewWindow(draft_backup=self.store)
        self.window._api_override = self.api
        self.window._load_pending()
        self.wait_finished()

    def tearDown(self):
        self.window._drafts.clear()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def wait_finished(self):
        until = monotonic() + 5
        while self.window._busy and monotonic() < until:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.window._busy)

    def test_partial_save_clears_only_confirmed_drafts_and_keeps_failed_backup(self):
        for key in (FIRST, SECOND):
            self.window._drafts[key] = {'changes': {'author': 'Autora corregida'}, 'ready_to_upload': False}
        self.window._retry_drafts()
        self.wait_finished()
        self.assertEqual(set(self.window._drafts), {SECOND})
        self.assertEqual(self.api.rows[FIRST]['author'], 'Autora corregida')
        self.assertNotEqual(self.api.rows[SECOND]['author'], 'Autora corregida')
        self.assertIn('ya no existe', self.window._drafts[SECOND]['save_error'])
        self.assertIn('1 ficha(s) guardadas', self.window._feedback.text())
        self.assertEqual(set(self.store.load()['drafts']), {SECOND})

    def test_recovery_preserves_original_revision_and_never_silently_rebases(self):
        original = copy.deepcopy(self.window._products['pending_review'][FIRST])
        self.window._drafts[FIRST] = {'changes': {'description': 'Texto largo ' * 100}, 'ready_to_upload': False}
        self.window._checkpoint_drafts()
        self.window._drafts.clear()
        self.window._products['pending_review'][FIRST]['_revision'] = 'b' * 64
        self.window._restore_draft_backup()
        self.assertEqual(self.window._entry(FIRST)['expected_revision'], original['_revision'])
        self.assertEqual(self.window._current_product(FIRST)['description'], 'Texto largo ' * 100)
        self.assertIn('Recuperados 1 cambios', self.window._feedback.text())

    def test_invalid_backup_is_reported_without_replacing_current_products(self):
        self.store.path.write_text('{broken', encoding='utf-8')
        before = copy.deepcopy(self.window._products)
        self.window._restore_draft_backup()
        self.assertEqual(self.window._products, before)
        self.assertIn('formato válido', self.window._feedback.text())

    def test_fully_confirmed_save_clears_backup_but_an_empty_screen_does_not(self):
        self.window._drafts[FIRST] = {'changes': {'author': 'Guardada'}, 'ready_to_upload': False}
        self.window._checkpoint_drafts()
        self.assertTrue(self.store.exists())
        self.window._drafts.clear()
        self.window._checkpoint_drafts()
        self.assertTrue(self.store.exists())
        self.window._restore_draft_backup()
        self.window._retry_drafts()
        self.wait_finished()
        self.assertFalse(self.store.exists())
