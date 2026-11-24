"""Local HTTP tests for the PHP endpoints. Requires PHP with PDO SQLite.

The fixture removes FOR UPDATE because SQLite does not implement row locks.
Production still uses the MySQL query unchanged; these tests do not emulate
MySQL lock scheduling or the hosting server's authentication.
"""
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


@unittest.skipUnless(os.environ.get('YUMEKAI_TEST_PHP') or shutil.which('php'), 'PHP no disponible')
class ReviewPhpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.database = cls.root / 'catalog.sqlite'
        api_dir = cls.root / 'public' / 'importer-api'
        api_dir.mkdir(parents=True)
        for name in ('review_common.php', 'products.php', 'review_products.php'):
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'api-importador' / name, api_dir / name)
        private = cls.root / 'importer-private'
        private.mkdir()
        (private / 'database.php').write_text('''<?php
class FixturePDO extends PDO {
    public function prepare(string $query, array $options = []): PDOStatement|false {
        return parent::prepare(str_replace(' FOR UPDATE', '', $query), $options);
    }
}
$p = new FixturePDO('sqlite:' . __DIR__ . '/../catalog.sqlite');
$p->setAttribute(PDO::ATTR_STRINGIFY_FETCHES, true);
return $p;
''')
        with sqlite3.connect(cls.database) as db:
            db.execute('''CREATE TABLE products (
                isbn TEXT PRIMARY KEY, title TEXT, retail_price TEXT,
                sale_price TEXT GENERATED ALWAYS AS (printf('%.2f', retail_price * 0.95)) STORED,
                author TEXT, description TEXT, categories TEXT, image_url TEXT, publisher TEXT,
                series TEXT, volume TEXT, language TEXT, book_format TEXT, pages INTEGER,
                work_type TEXT, demographic TEXT, yumekai_status TEXT, sku TEXT UNIQUE,
                is_featured INTEGER, review_status TEXT, updated_at TEXT)''')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.url = f'http://127.0.0.1:{port}/importer-api'
        args = [os.environ.get('YUMEKAI_TEST_PHP') or shutil.which('php')]
        extension_dir = os.environ.get('YUMEKAI_TEST_PHP_EXTENSIONS')
        if extension_dir:
            args += ['-n', '-d', f'extension={extension_dir}/pdo.so', '-d', f'extension={extension_dir}/pdo_sqlite.so']
        cls.process = subprocess.Popen(args + ['-S', f'127.0.0.1:{port}', '-t', str(cls.root / 'public')],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        until = time.monotonic() + 5
        while time.monotonic() < until:
            try:
                requests.get(cls.url + '/products.php', timeout=0.2)
                return
            except requests.RequestException:
                time.sleep(0.03)
        cls.process.terminate()
        cls.process.wait()
        cls.temporary.cleanup()
        raise RuntimeError('No se pudo iniciar el PHP de pruebas con PDO SQLite')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=3)
        cls.temporary.cleanup()

    def setUp(self):
        self.isbn = '9788419914163'
        self.other = '9791370138479'
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM products')
            for isbn in (self.isbn, self.other):
                db.execute('''INSERT INTO products (isbn,title,retail_price,categories,publisher,volume,
                    work_type,demographic,yumekai_status,is_featured,review_status,updated_at)
                    VALUES (?,?,'9.00','[]','Milky Way','3','Manga','Seinen','instock',0,
                            'pending_review','2026-11-23 18:30:00')''', (isbn, 'Obra ' + isbn))

    def rows(self, status='pending_review'):
        r = requests.get(self.url + '/products.php', params={'review_status': status}, timeout=2)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def entry(self, isbn=None, changes=None, ready=False, status='pending_review'):
        isbn = isbn or self.isbn
        p = next(p for p in self.rows(status) if p['isbn'] == isbn)
        return dict(original_isbn=isbn, changes=changes or {}, ready_to_upload=ready,
                    expected_updated_at=p['updated_at'], expected_revision=p['_revision'],
                    expected_review_status=p['review_status'])

    def action(self, action, entries, expected=200):
        r = requests.post(self.url + '/review_products.php', json={'action': action, 'products': entries}, timeout=3)
        self.assertEqual(r.status_code, expected, r.text)
        return r.json()

    def test_save_partial_fiche_without_marking_it_ready(self):
        response = self.action('save', [self.entry(changes={'author': 'Autora 日本語', 'retail_price': None})])
        p = response['saved'][0]['product']
        self.assertEqual(p['author'], 'Autora 日本語')
        self.assertIsNone(p['retail_price'])
        self.assertIsNone(p['sku'])
        self.assertEqual(p['review_status'], 'pending_review')

    def test_bulk_ready_generates_sku_and_categories_then_return_pending(self):
        result = self.action('ready', [self.entry(self.isbn), self.entry(self.other)])
        self.assertEqual(len(result['saved']), 2)
        ready = self.rows('ready_to_upload')
        self.assertEqual(ready[0]['sku'], 'YMK-' + ready[0]['isbn'])
        self.assertEqual(ready[0]['categories'], ['Manga', 'Manga > Seinen'])
        result = self.action('pending', [self.entry(status='ready_to_upload')])
        self.assertIsNone(result['saved'][0]['product']['sku'])
        self.assertEqual(len(self.rows()), 1)

    def test_long_synopsis_survives_save_read_and_csv_export(self):
        from yumekai_importer.storage.woocommerce_csv import export_products
        import csv
        synopsis = 'Una sinopsis completa con tildes y saltos.\n' * 60
        self.action('save', [self.entry(changes={'description': synopsis}, ready=True)])
        row = self.rows('ready_to_upload')[0]
        self.assertEqual(row['description'], synopsis)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'sinopsis.csv'
            export_products(path, [row])
            with path.open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(next(csv.DictReader(stream))['Descripción'], synopsis)

    def test_ready_transition_accepts_missing_prices_in_the_entire_batch(self):
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE products SET retail_price=NULL WHERE isbn=?', (self.other,))
        self.action('ready', [self.entry(self.isbn), self.entry(self.other)])
        self.assertEqual(self.rows(), [])
        self.assertEqual(len(self.rows('ready_to_upload')), 2)

    def test_changed_or_computed_fields_cannot_bypass_validation(self):
        for changes in ({'pages': 'abc'}, {'retail_price': '-1.00'}, {'volume': '5-1'},
                        {'sku': 'arbitrary'}, {'review_status': 'uploaded'}):
            self.action('save', [self.entry(changes=changes)], expected=400)
        self.assertEqual(len(self.rows()), 2)

    def test_invalid_isbn_can_be_marked_ready_then_corrected(self):
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE products SET isbn=? WHERE isbn=?', ('1234567890123', self.isbn))
        self.action('save', [self.entry('1234567890123', changes={'author': 'Corregida'})])
        self.action('ready', [self.entry('1234567890123')])
        self.action('save', [self.entry('1234567890123', changes={'isbn': self.isbn},
                                       status='ready_to_upload', ready=True)])
        self.assertEqual(len(self.rows('ready_to_upload')), 1)
        self.assertEqual(len(self.rows()), 1)

    def test_same_second_revision_conflict_prevents_overwrite_and_delete(self):
        entry = self.entry(changes={'title': 'Cambio antiguo'})
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE products SET title=? WHERE isbn=?', ('Cambio más reciente', self.isbn))
        self.action('save', [entry], expected=409)
        self.action('delete', [entry], expected=409)
        self.assertEqual(next(p for p in self.rows() if p['isbn'] == self.isbn)['title'], 'Cambio más reciente')

    def test_one_missing_row_does_not_block_the_other_drafts_in_python_save(self):
        from yumekai_importer.storage.review_saving import save_review_drafts
        entries = [self.entry(changes={'author': 'Guardada'}), self.entry(self.other, changes={'author': 'Pendiente'})]
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM products WHERE isbn=?', (self.other,))
        result = {'saved': [], 'failed': []}
        save_review_drafts(CatalogApi(self.url, 'test', 'test'), entries, result)
        self.assertEqual([row['original_isbn'] for row in result['saved']], [self.isbn])
        self.assertEqual(result['failed'][0]['original_isbn'], self.other)
        self.assertIn('ya no existe', result['failed'][0]['message'])
        self.assertEqual(self.rows()[0]['author'], 'Guardada')

    def test_changed_review_state_and_modified_data_have_different_messages(self):
        entry = self.entry(changes={'author': 'No sobrescribir'})
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE products SET review_status=? WHERE isbn=?', ('ready_to_upload', self.isbn))
        message = self.action('save', [entry], expected=409)['message']
        self.assertIn('otro estado', message)
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE products SET review_status=?,title=? WHERE isbn=?',
                       ('pending_review', 'Cambio más reciente', self.isbn))
        message = self.action('save', [entry], expected=409)['message']
        self.assertIn('versión distinta', message)

    def test_delete_is_atomic_and_uses_exact_original_isbns(self):
        good = self.entry()
        stale = self.entry(self.other)
        stale['expected_updated_at'] = '2020-01-01 00:00:00'
        self.action('delete', [good, stale], expected=409)
        self.assertEqual(len(self.rows()), 2)
        result = self.action('delete', [good])
        self.assertEqual(result['deleted'], [self.isbn])
        self.assertEqual([p['isbn'] for p in self.rows()], [self.other])

    def test_duplicate_entries_and_bad_methods_are_rejected(self):
        entry = self.entry()
        self.action('delete', [entry, entry], expected=400)
        self.assertEqual(requests.get(self.url + '/review_products.php', timeout=2).status_code, 405)
        self.assertEqual(requests.post(self.url + '/products.php', timeout=2).status_code, 405)
        self.assertEqual(requests.get(self.url + '/products.php?review_status=uploaded', timeout=2).status_code, 400)
        self.assertEqual(requests.post(self.url + '/review_products.php', data='x', timeout=2).status_code, 415)

    def test_python_client_and_real_php_responses_work_together(self):
        api = CatalogApi(self.url, 'test', 'test')
        self.assertEqual(len(api.list_pending_products()), 2)
        entry = self.entry(changes={'retail_price': '10.95'}, ready=True)
        result = api.review_products('save', [entry])
        self.assertEqual(result['saved'][0]['product']['sku'], 'YMK-' + self.isbn)
        self.assertEqual(len(api.list_products('ready_to_upload')), 1)
        api.review_products('delete', [self.entry(status='ready_to_upload')])
        self.assertEqual(api.list_products('ready_to_upload'), [])

    def test_supplier_demographic_aliases_are_normalized_by_php(self):
        aliases = {"Teen’s Love": 'Yaoi / BL', 'Yaoi': 'Yaoi / BL', 'Boys Love': 'Yaoi / BL',
                   'Spokon': 'Shonen', 'Shōnen': 'Shonen', 'Manga adulto': 'Seinen',
                   'Novelas manga': 'Artbooks, guías y novelas', 'Artbooks': 'Artbooks, guías y novelas'}
        for value, expected in aliases.items():
            with self.subTest(value=value):
                result = self.action('save', [self.entry(changes={'demographic': value})])
                row = result['saved'][0]['product']
                self.assertEqual(row['demographic'], expected)
                self.assertEqual(row['categories'], ['Manga', 'Manga > ' + expected])

    def test_long_demographic_can_be_saved_ready_and_api_limit_is_bounded(self):
        result = self.action('save', [self.entry(changes={'demographic': 'Artbooks, guías y novelas'}, ready=True)])
        row = result['saved'][0]['product']
        self.assertEqual(row['demographic'], 'Artbooks, guías y novelas')
        self.assertEqual(row['review_status'], 'ready_to_upload')
        entry = self.entry(status='ready_to_upload', changes={'demographic': 'x' * 101}, ready=True)
        self.action('save', [entry], expected=400)


if __name__ == '__main__':
    unittest.main()
