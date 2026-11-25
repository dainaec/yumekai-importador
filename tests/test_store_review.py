import copy
from dataclasses import replace
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import unittest
from unittest.mock import Mock, patch

from lxml import html
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from yumekai_importer.catalog.descriptions import format_description
from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.importers.sd.details import _description_text
from yumekai_importer.importers.sd.lookup import SdLookupResult
from yumekai_importer.storage.catalog_api import CatalogApi
from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup
from yumekai_importer.ui.widgets.change_review_dialog import ChangeReviewDialog
from yumekai_importer.ui.windows.store_review_window import StoreReviewWindow
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from yumekai_importer.ui.windows.import_window import ImportWindow
from yumekai_importer.ui.windows.catalog_window import CatalogWindow
from yumekai_importer.ui.workers.store_workers import StoreSaveWorker
from tests.test_review_workflow import product, FakeApi
from tests.test_sd_recheck import DETAILS

MODULE='yumekai_importer.ui.windows.'
CODE='9788410515901'


def store_product(identifier=421,**changes):
    return product(CODE,description='Una sinopsis editada\ncon saltos.\n\nOtro párrafo.',author='Autor manual',
                   woocommerce_id=identifier,review_status='in_store',_store_revision='a'*64,
                   categories=['Manga','Categoría manual'],manage_stock=False) | changes


class DescriptionFormattingTests(unittest.TestCase):
    def test_single_line_breaks_join_while_paragraphs_and_words_survive(self):
        raw='La primavera llega con toda su fuerza\ngracias al nuevo título que se incorpora\nal catálogo.\n\nAl principio, solo existía el invierno.\nIncapaz de soportar la soledad, creó la primavera.'
        result=format_description(raw)
        self.assertTrue(result.changed)
        self.assertEqual(result.text,'La primavera llega con toda su fuerza gracias al nuevo título que se incorpora al catálogo.\n\nAl principio, solo existía el invierno. Incapaz de soportar la soledad, creó la primavera.')
        self.assertEqual(raw.split(),result.text.split())
        self.assertFalse(format_description(result.text).changed)

    def test_html_lists_dialogue_and_split_words_are_not_automatically_rewritten(self):
        for value in ('<p>Texto<br>revisado</p>','<!-- wp:paragraph --><p>Texto</p><!-- /wp:paragraph -->',
                      'Lista:\n- Una cosa\n- Otra cosa','— Hola\n— Buenos días','Una pala-\nbra partida'):
            with self.subTest(value=value):
                result=format_description(value)
                self.assertEqual(result.text,value)
                self.assertFalse(result.changed)
                self.assertTrue(result.note)

    def test_windows_breaks_multiple_blank_lines_and_idempotence(self):
        self.assertEqual(format_description(' Uno\r\ndos.\r\n \r\n\r\nTres. ').text,'Uno dos.\n\nTres.')
        self.assertIsNone(format_description(None).text)

    def test_sd_html_paragraph_boundaries_survive_extraction(self):
        page=html.fromstring('<div><span id="txtSinpsis"><p>Uno<br>dos.</p><p>Tres.</p></span></div>')
        value=_description_text(page)
        self.assertEqual(format_description(value).text,'Uno dos.\n\nTres.')
        special=html.fromstring('<div id="txtSinpsis"><ul><li>Uno</li><li>Dos</li></ul></div>')
        value=_description_text(special)
        self.assertIn('<li>Uno</li>',value)
        self.assertFalse(format_description(value).changed)

    def test_recheck_formats_current_manual_text_without_replacing_it_with_sd(self):
        p=store_product()
        result=SdLookupResult(CODE,'found',True,replace(DETAILS,description='Otra sinopsis del distribuidor'))
        changes,note=sd_review_changes(p,result)
        self.assertEqual(changes['description'],'Una sinopsis editada con saltos.\n\nOtro párrafo.')
        self.assertNotIn('author',changes)
        self.assertEqual(p['description'],'Una sinopsis editada\ncon saltos.\n\nOtro párrafo.')
        self.assertIn('normalizados',note)

    def test_stock_only_changes_exactly_availability_and_failed_queries_preserve_it(self):
        p=store_product()
        changes,_=sd_review_changes(p,SdLookupResult(CODE,'found',False,DETAILS),stock_only=True)
        self.assertEqual(changes,{'yumekai_status':'outofstock'})
        for status in ('error','not_found','cancelled'):
            self.assertEqual(sd_review_changes(p,SdLookupResult(CODE,status),stock_only=True)[0],{})


class StoreClientTests(unittest.TestCase):
    def setUp(self):
        self.api=CatalogApi('https://example.test/api','test','test')

    def response(self,body):
        r=Mock(status_code=200,ok=True);r.json.return_value=body;return r

    def test_paginated_store_read_uses_live_endpoint_and_keeps_distinct_ids(self):
        responses=[self.response({'products':[store_product(421)],'page':1,'pages':2}),
                   self.response({'products':[store_product(422)],'page':2,'pages':2})]
        with patch('yumekai_importer.storage.catalog_api.requests.get',side_effect=responses) as get:
            products=self.api.list_store_products()
        self.assertEqual([p['woocommerce_id'] for p in products],[421,422])
        self.assertTrue(get.call_args.args[0].endswith('/store_review.php'))

    def test_malformed_or_duplicate_receipts_are_rejected(self):
        entry={'id':421,'expected_revision':'a'*64,'changes':{'description':'Texto'}}
        for body in ({'saved':[],'failed':[]},{'saved':[{'id':422,'product':store_product(422)}],'failed':[]},
                     {'saved':[{'id':421,'product':store_product()}],'failed':[{'id':421,'message':'Error','status_code':409}]}):
            with patch('yumekai_importer.storage.catalog_api.requests.post',return_value=self.response(body)):
                with self.assertRaises(ValueError): self.api.update_store_products([entry])

    def test_worker_chunks_and_stops_after_unconfirmed_results(self):
        api=Mock()
        api.update_store_products.side_effect=lambda entries:{'saved':[{'id':e['id'],'product':store_product(e['id'])} for e in entries],'failed':[]}
        worker=StoreSaveWorker(api,[{'id':i} for i in range(101)])
        worker.run()
        self.assertEqual([len(c.args[0]) for c in api.update_store_products.call_args_list],[20,20,20,20,20,1])
        self.assertEqual(len(worker.result['saved']),101)
        api.reset_mock()
        api.update_store_products.side_effect=ValueError('Sin confirmar')
        worker=StoreSaveWorker(api,[{'id':i} for i in range(101)])
        worker.run()
        self.assertEqual(api.update_store_products.call_count,1)
        self.assertIn('Sin confirmar',worker.error)


class FakeStoreApi:
    def __init__(self,products):
        self.products={p['woocommerce_id']:copy.deepcopy(p) for p in products}
        self.calls=[]

    def list_store_products(self): return list(copy.deepcopy(self.products).values())

    def update_store_products(self,entries):
        self.calls.append(copy.deepcopy(entries))
        result={'saved':[],'failed':[]}
        for entry in entries:
            p=self.products[entry['id']]
            if p['_store_revision']!=entry['expected_revision']:
                result['failed'].append({'id':entry['id'],'message':'La ficha cambió en WooCommerce','status_code':409})
            else:
                p.update(entry['changes']);p['_store_revision']='b'*64
                result['saved'].append({'id':entry['id'],'product':copy.deepcopy(p)})
        return result


class StoreReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=TemporaryDirectory()
        self.backup=ReviewDraftBackup(Path(self.temp.name)/'store.json')
        self.window=StoreReviewWindow(draft_backup=self.backup)
        self.api=FakeStoreApi([store_product(),store_product(422)])
        self.window._api_override=self.api
        self.window._load_inventory();self.wait()
        self.widgets=[self.window]

    def tearDown(self):
        for w in self.widgets:
            if hasattr(w,'_drafts'): w._drafts.clear()
            if isinstance(w,ImportWindow): w._issues_exported=True
            w.close();w.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.app.processEvents();self.temp.cleanup()

    def wait(self,window=None):
        w=window or self.window
        until=monotonic()+5
        while w._busy and monotonic()<until:
            self.app.processEvents();QTest.qWait(5)
        self.assertFalse(w._busy)

    def propose(self):
        self.window._toggle_visible()
        with patch('yumekai_importer.ui.workers.sd_recheck_worker.lookup_sd_isbn',
                   return_value=SdLookupResult(CODE,'found',False,DETAILS)):
            self.window._recheck_sd();self.wait()

    def test_store_recheck_is_only_a_proposal_and_uses_id_not_repeated_isbn(self):
        self.propose()
        self.assertEqual(self.api.calls,[])
        self.assertEqual(set(self.window._drafts),{'421','422'})
        self.assertIn('description',self.window._drafts['421']['changes'])
        self.assertEqual(self.api.products[421]['yumekai_status'],'instock')

    def test_only_checked_fields_save_and_unchecked_proposals_remain(self):
        self.propose()
        text=self.window._drafts['421']['changes']['description']
        with patch(MODULE+'store_review_window.review_changes',return_value={'421':{'description':text}}):
            self.window._save_proposals();self.wait()
        self.assertEqual(self.api.calls[0][0]['changes'],{'description':text})
        self.assertEqual(self.api.calls[0][0]['expected_revision'],'a'*64)
        self.assertEqual(self.api.products[421]['yumekai_status'],'instock')
        self.assertEqual(self.api.products[421]['author'],'Autor manual')
        self.assertIn('yumekai_status',self.window._drafts['421']['changes'])
        self.assertNotIn('description',self.window._drafts['421']['changes'])

    def test_cancel_preview_preserves_proposals_and_never_calls_store(self):
        self.propose();before=copy.deepcopy(self.window._drafts)
        with patch(MODULE+'store_review_window.review_changes',return_value=None): self.window._save_proposals()
        self.assertEqual(self.api.calls,[])
        self.assertEqual(self.window._drafts,before)

    def test_conflicted_product_keeps_proposals_while_other_products_save(self):
        self.propose()
        self.api.products[421]['_store_revision']='c'*64
        self.api.products[421]['description']='Edición más reciente'
        with patch(MODULE+'store_review_window.review_changes',side_effect=lambda rows,**kwargs:{key:row['changes'] for key,row in rows.items()}):
            self.window._save_proposals();self.wait()
        self.assertEqual(set(self.window._drafts),{'421'})
        self.assertIn('cambió',self.window._drafts['421']['save_error'])
        self.assertEqual(self.api.products[421]['description'],'Edición más reciente')
        self.assertEqual(self.api.products[422]['yumekai_status'],'outofstock')

    def test_backup_recovers_original_revision_without_silent_rebase(self):
        self.propose()
        self.window._drafts.clear()
        self.window._products[0]['_store_revision']='c'*64
        self.window._restore_backup()
        self.assertEqual(self.window._products[0]['_store_revision'],'a'*64)
        self.assertEqual(set(self.window._drafts),{'421','422'})

    def test_change_dialog_unchecked_field_is_not_in_accepted_payload(self):
        dialog=ChangeReviewDialog({'421':{'product':store_product(),'changes':{'description':'Texto','yumekai_status':'outofstock'}}},store=True)
        self.widgets.append(dialog)
        dialog.table.item(1,0).setCheckState(Qt.CheckState.Unchecked)
        dialog.accept()
        self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.accepted_changes,{'421':{'description':'Texto'}})

    def test_importer_no_longer_has_distributor_check_button(self):
        w=ImportWindow();self.widgets.append(w)
        self.assertFalse(any('Comprobar stock' in b.text() for b in w.findChildren(QPushButton)))
        self.assertFalse(hasattr(w,'_stock_worker'))

    def test_pending_partial_sd_save_keeps_unchecked_fields(self):
        w=PendingReviewWindow();self.widgets.append(w)
        p=product();api=FakeApi([p]);w._api_override=api;w._load_pending();self.wait(w)
        key=p['isbn'];w._drafts[key]={'changes':{'book_format':'Tapa dura','pages':224},'ready_to_upload':False}
        w._sd_results[key]={'changed':True,'note':'SD','saved':False}
        with patch(MODULE+'pending_review_window.review_changes',return_value={key:{'book_format':'Tapa dura'}}):
            w._retry_drafts();self.wait(w)
        self.assertEqual(w._drafts[key]['changes'],{'pages':224})
        self.assertEqual(api.rows[key]['pages'],176)
        self.assertEqual(api.rows[key]['book_format'],'Tapa dura')

    def test_catalog_routes_both_review_entries_to_the_same_workspace(self):
        w=CatalogWindow();self.widgets.append(w)
        with patch.object(w._review_page,'_load_pending'),patch.object(w._inventory_page,'_load_inventory'):
            w._show_page(w._inventory_page)
        self.assertIs(w._pages.currentWidget(),w._review_workspace)
        self.assertIs(w._review_workspace.tabs.currentWidget(),w._inventory_page)
        self.assertEqual(w._pages.count(),3)


if __name__=='__main__': unittest.main()
