"""Real PHP endpoint against a local WooCommerce test double, never the user's store."""
import copy
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest
import requests
from yumekai_importer.storage.catalog_api import CatalogApi


def fixture_product(identifier=421, **changes):
    return dict(id=identifier,title='Título editado en la tienda',description='Sinopsis editada\ncon saltos.\n\nOtro párrafo.',
        short_description='Texto corto manual',regular_price='12.00',sale_price='11.40',stock_status='instock',
        sku='SKU-MANUAL',manage_stock=False,stock_quantity=None,backorders='no',type='simple',status='publish',featured=True,
        categories=[7,8,99],image_id=77,modified=100,meta={'_yk_isbn':'9788410515901','_yk_author':'Autor manual',
        '_yk_brand':'Editorial manual','_yk_franchise':'Colección editada','_yk_volume':'1','_yk_language':'Castellano',
        '_yk_format':'Rústica','_yk_pages':'200','_yk_item_kind':'manga','_uag_css_file_name':'uag-css-421.css'}) | changes


@unittest.skipUnless(os.environ.get('YUMEKAI_TEST_PHP') or shutil.which('php'),'PHP no disponible')
class StorePhpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.database=cls.root/'store.sqlite'
        public=cls.root/'public'
        api_dir=public/'importer-api'
        api_dir.mkdir(parents=True)
        source=Path(__file__).resolve().parents[1]
        for name in ('review_common.php','exception_rules.php','store_common.php','store_review.php'):
            shutil.copyfile(source/'api-importador'/name,api_dir/name)
        shutil.copyfile(source/'tests/fixtures/wordpress-store.php',public/'wp-load.php')
        with sqlite3.connect(cls.database) as db:
            db.execute('CREATE TABLE products (id INTEGER PRIMARY KEY, data TEXT)')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        cls.url=f'http://127.0.0.1:{port}/importer-api'
        args=[os.environ.get('YUMEKAI_TEST_PHP') or shutil.which('php')]
        extensions=os.environ.get('YUMEKAI_TEST_PHP_EXTENSIONS')
        if extensions:
            args+=['-n','-d',f'extension={extensions}/pdo.so','-d',f'extension={extensions}/pdo_sqlite.so']
        cls.process=subprocess.Popen(args+['-S',f'127.0.0.1:{port}','-t',str(public)],
                                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        until=time.monotonic()+5
        while time.monotonic()<until:
            try:
                requests.get(cls.url+'/store_review.php',timeout=.2)
                break
            except requests.RequestException:
                time.sleep(.03)
        else:
            cls.process.terminate();cls.process.wait();cls.temp.cleanup()
            raise RuntimeError('No se pudo iniciar el servidor PHP local')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=3);cls.temp.cleanup()

    def setUp(self):
        self.api=CatalogApi(self.url,'test','test')
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM products')
            for p in (fixture_product(),fixture_product(422,description='Otra sinopsis')):
                db.execute('INSERT INTO products VALUES (?,?)',(p['id'],json.dumps(p)))

    def stored(self,identifier=421):
        with sqlite3.connect(self.database) as db:
            return json.loads(db.execute('SELECT data FROM products WHERE id=?',(identifier,)).fetchone()[0])

    def modify(self,identifier=421,**changes):
        p=self.stored(identifier);p.update(changes)
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p),identifier))

    def entry(self,identifier=421,**changes):
        p=next(p for p in self.api.list_store_products() if p['woocommerce_id']==identifier)
        return {'id':identifier,'expected_revision':p['_store_revision'],'changes':changes}

    def test_reads_actual_store_values_including_four_state_code_and_html(self):
        self.modify(stock_status='yk_on_demand',description='<p>Texto manual<br>con formato.</p>')
        p=self.api.list_store_products()[0]
        self.assertEqual(p['description'],'<p>Texto manual<br>con formato.</p>')
        self.assertEqual(p['yumekai_status'],'yk_on_demand')
        self.assertEqual(p['publisher'],'Editorial manual')
        self.assertEqual(p['categories'],['Manga','Seinen','Categoría editada'])
        self.assertEqual(p['demographic'],'Seinen')
        self.assertEqual(len(p['_store_revision']),64)

    def test_only_approved_description_and_state_are_written(self):
        before=self.stored()
        entry=self.entry(description='Sinopsis editada con saltos.\n\nOtro párrafo.',yumekai_status='yk_on_demand')
        result=self.api.update_store_products([entry])
        self.assertFalse(result['failed'])
        actual=self.stored()
        expected=copy.deepcopy(before)
        expected.update(description=entry['changes']['description'],stock_status='yk_on_demand',modified=101)
        self.assertEqual(actual,expected)  # Prices, title, categories, image, CSS and all manual metadata survive.
        self.assertNotEqual(entry['expected_revision'],result['saved'][0]['product']['_store_revision'])

    def test_same_second_manual_edit_is_conflict_and_rest_of_batch_saves(self):
        first=self.entry(description='No sobrescribir')
        second=self.entry(422,yumekai_status='outofstock')
        self.modify(description='Corrección manual más reciente')  # Keep modified timestamp equal.
        result=self.api.update_store_products([first,second])
        self.assertEqual([row['id'] for row in result['saved']],[422])
        self.assertEqual(result['failed'][0]['status_code'],409)
        self.assertEqual(self.stored()['description'],'Corrección manual más reciente')
        self.assertEqual(self.stored(422)['stock_status'],'outofstock')

    def test_price_or_metadata_edit_also_changes_snapshot(self):
        entry=self.entry(yumekai_status='outofstock')
        p=self.stored();p['meta']['_yk_author']='Autor corregido';self.modify(meta=p['meta'])
        result=self.api.update_store_products([entry])
        self.assertFalse(result['saved'])
        self.assertEqual(result['failed'][0]['status_code'],409)
        self.assertEqual(self.stored()['stock_status'],'instock')

    def test_missing_or_unpublished_or_variable_product_is_not_changed(self):
        for change in ({'status':'draft'},{'type':'variable'}):
            with self.subTest(change=change):
                self.modify(status='publish',type='simple')
                entry=self.entry(yumekai_status='outofstock')
                self.modify(**change)
                result=self.api.update_store_products([entry])
                self.assertFalse(result['saved'])
        self.assertEqual(self.stored()['stock_status'],'instock')

    def test_unapproved_fields_and_malformed_requests_never_write(self):
        before=self.stored()
        entry=self.entry(title='Alterado')
        r=requests.post(self.url+'/store_review.php',json={'products':[entry]},timeout=2)
        self.assertEqual(r.status_code,400,r.text)
        self.assertEqual(self.stored(),before)
        for method in ('put','delete'):
            self.assertEqual(getattr(requests,method)(self.url+'/store_review.php',timeout=2).status_code,405)

    def test_units_management_is_preserved_instead_of_silently_disabled(self):
        self.modify(manage_stock=True,stock_quantity=5)
        result=self.api.update_store_products([self.entry(yumekai_status='outofstock')])
        self.assertEqual(result['failed'][0]['status_code'],409)
        self.assertTrue(self.stored()['manage_stock'])
        self.assertEqual(self.stored()['stock_quantity'],5)

    def test_missing_metadata_is_saved_using_plugin_existing_keys(self):
        entry=self.entry(author='Autora',pages=224,book_format='Tapa dura',work_type='Manhwa',retail_price='10.00',sale_price='9.50')
        result=self.api.update_store_products([entry])
        self.assertFalse(result['failed'])
        p=self.stored()
        self.assertEqual(p['meta']['_yk_author'],'Autora')
        self.assertEqual(p['meta']['_yk_pages'],'224')
        self.assertEqual(p['meta']['_yk_item_kind'],'manhwa')
        self.assertEqual(p['sale_price'],'9.50')

    def test_unexpected_save_failure_rolls_back_and_stops_remaining_requests(self):
        self.modify(save_error=True)
        entries=[self.entry(description='Texto nuevo'),self.entry(422,yumekai_status='outofstock')]
        before=self.stored()
        result=self.api.update_store_products(entries)
        self.assertEqual(result['saved'],[])
        self.assertEqual([r['status_code'] for r in result['failed']],[500,503])
        self.assertEqual(self.stored(),before)
        self.assertEqual(self.stored(422)['stock_status'],'instock')


if __name__=='__main__': unittest.main()
