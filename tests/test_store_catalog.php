<?php
declare(strict_types=1);
require_once dirname(__DIR__) . '/api-importador/store_catalog_common.php';
require_once dirname(__DIR__) . '/api-importador/store_mirror.php';

// SQLite-backed WordPress/WooCommerce doubles exercise real transactions, tokens,
// snapshots and receipts. No request is sent to a live shop.
function check(bool $condition, string $message): void { if (!$condition) { throw new RuntimeException($message); } }
function rejects(callable $call, int $code): void {
    try { $call(); } catch (ReviewRequestError $e) { check($e->getCode() === $code, $e->getMessage()); return; }
    throw new RuntimeException('Expected rejection ' . $code);
}
class WC_Data_Exception extends RuntimeException {}
class FakeWpdb {
    public string $posts = 'posts', $postmeta = 'postmeta', $options = 'options', $term_relationships = 'relationships', $last_error = '';
    public PDO $pdo;
    public function __construct() {
        $this->pdo = new PDO('sqlite::memory:');
        $this->pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $this->pdo->exec('CREATE TABLE posts (ID INTEGER PRIMARY KEY AUTOINCREMENT, post_type TEXT, post_status TEXT, data TEXT)');
        $this->pdo->exec('CREATE TABLE postmeta (meta_id INTEGER PRIMARY KEY, post_id INTEGER, meta_key TEXT, meta_value TEXT)');
        $this->pdo->exec('CREATE TABLE relationships (object_id INTEGER, term_taxonomy_id INTEGER)');
        $this->pdo->exec('CREATE TABLE options (option_name TEXT UNIQUE, option_value TEXT, autoload TEXT)');
    }
    public function prepare($sql, ...$args) {
        $i = 0;
        return preg_replace_callback('/%[ds]/', function ($m) use ($args, &$i) {
            $value = $args[$i++]; return $m[0] === '%d' ? (string) (int) $value : $this->pdo->quote((string) $value);
        }, $sql);
    }
    private function sql($sql) { return str_replace([' FOR UPDATE', 'START TRANSACTION', 'INSERT IGNORE'], ['', 'BEGIN', 'INSERT OR IGNORE'], $sql); }
    public function query($sql) { $this->last_error = ''; return $this->pdo->exec($this->sql($sql)); }
    public function get_var($sql) { $this->last_error = ''; $r = $this->pdo->query($this->sql($sql))->fetchColumn(); return $r === false ? null : $r; }
    public function get_results($sql) { $this->last_error = ''; return $this->pdo->query($this->sql($sql))->fetchAll(PDO::FETCH_ASSOC); }
}
$wpdb = new FakeWpdb();
$terms = [
    1 => (object) ['term_id' => 1, 'name' => 'Manga', 'slug' => 'manga', 'parent' => 0],
    2 => (object) ['term_id' => 2, 'name' => 'Shonen', 'slug' => 'shonen', 'parent' => 1],
    20 => (object) ['term_id' => 20, 'name' => 'Manwha/Manhua', 'slug' => 'manwha-manhua', 'parent' => 0],
    30 => (object) ['term_id' => 30, 'name' => 'Manwha', 'slug' => 'manwha', 'parent' => 20],
    40 => (object) ['term_id' => 40, 'name' => 'Manhua', 'slug' => 'manhua', 'parent' => 20],
    50 => (object) ['term_id' => 50, 'name' => 'Manhwa', 'slug' => 'manhwa-hijo', 'parent' => 1],
];
function get_term($id, $taxonomy) { return $GLOBALS['terms'][$id] ?? null; }
function get_terms($args) { return array_values($GLOBALS['terms']); }
function is_wp_error($v) { return false; }
function get_ancestors($id, $taxonomy, $resource) {
    $parents = [];
    while (($id = (int) ($GLOBALS['terms'][$id]->parent ?? 0)) > 0 && !in_array($id, $parents, true)) { $parents[] = $id; }
    return $parents;
}
function get_post_meta($id, $key = '', $single = false) {
    $q = $GLOBALS['wpdb']->pdo->prepare('SELECT meta_key, meta_value FROM postmeta WHERE post_id = ? ORDER BY meta_id');
    $q->execute([$id]); $meta = [];
    foreach ($q as $row) { $meta[$row['meta_key']][] = $row['meta_value']; }
    return $key === '' ? $meta : ($single ? ($meta[$key][0] ?? '') : ($meta[$key] ?? []));
}
function get_post_field($field, $id) { return '2026-11-25 12:00:00'; }
function wp_get_attachment_url($id) { return $id ? 'https://example.test/cover.jpg' : false; }
function sanitize_text_field($v) { return trim(strip_tags($v)); }
function sanitize_title($v) { return strtolower(str_replace(' ', '-', $v)); }
function wp_kses_post($v) { return $v; }
function get_post($id) {
    if (($GLOBALS['url_sample_post']->ID ?? null) === $id) { return $GLOBALS['url_sample_post']; }
    return (object) ['ID' => $id, 'post_name' => 'product-' . $id, 'post_status' => 'draft'];
}
function get_permalink($post) {
    $GLOBALS['sample_link_status'] = $post->post_status;
    return 'https://example.test/product/' . $post->ID;
}
function clean_post_cache($id) {}
function wc_delete_product_transients($id) {}
$GLOBALS['cache_flushes'] = [];
function w3tc_flush_post($id, $force = false) {
    if ($GLOBALS['cache_should_fail'] ?? false) { throw new RuntimeException('Cache unavailable'); }
    $GLOBALS['cache_flushes'][] = ['id' => $id, 'force' => $force, 'in_transaction' => $GLOBALS['wpdb']->pdo->inTransaction()];
}
function w3tc_flush_url($url) { $GLOBALS['cache_urls'][] = $url; }
function wc_get_product_stock_status_options() { return ['instock' => 'Hay existencias', 'outofstock' => 'Sin existencias', 'onbackorder' => 'Se puede reservar']; }
function wc_format_decimal($v, $dp) { return number_format((float) $v, $dp, '.', ''); }
class WC_Tax { static function get_tax_classes() { return ['Tasa reducida']; } }
class WC_Product_Simple {
    public int $id = 0;
    public array $data = ['name' => '', 'description' => '', 'short_description' => '', 'regular_price' => '', 'sale_price' => '',
        'stock_status' => 'outofstock', 'sku' => '', 'manage_stock' => false, 'stock_quantity' => null, 'backorders' => 'no',
        'type' => 'simple', 'status' => 'draft', 'featured' => false, 'category_ids' => [], 'image_id' => 0,
        'tax_class' => '', 'tax_status' => 'taxable', 'attributes' => [], 'price' => ''];
    public array $meta = [];
    function get_id() { return $this->id; }
    function get_permalink() { return 'https://example.test/product/' . $this->id; }
    function __call($method, $args) {
        if ($method === 'get_type') { return $this->data['type']; }
        if (str_starts_with($method, 'get_')) { return $this->data[substr($method, 4)]; }
        if (str_starts_with($method, 'set_')) { $this->data[substr($method, 4)] = $args[0]; return; }
        throw new RuntimeException('Unexpected method ' . $method);
    }
    function update_meta_data($key, $v) { $this->meta[$key] = (string) $v; }
    function get_meta($key, $single = true, $context = 'view') { throw new RuntimeException('Snapshot read stale WC metadata'); }
    function save() {
        global $wpdb;
        if ($this->id === 0) {
            $wpdb->query($wpdb->prepare("INSERT INTO posts (post_type, post_status, data) VALUES ('product', %s, %s)", $this->data['status'], json_encode($this->data)));
            $this->id = (int) $wpdb->pdo->lastInsertId();
        } else { $wpdb->query($wpdb->prepare('UPDATE posts SET data = %s, post_status = %s WHERE ID = %d', json_encode($this->data), $GLOBALS['ignore_status_write'] ?? false ? 'publish' : $this->data['status'], $this->id)); }
        $wpdb->query($wpdb->prepare('DELETE FROM postmeta WHERE post_id = %d', $this->id));
        foreach ($this->meta as $key => $value) {
            $wpdb->query($wpdb->prepare('INSERT INTO postmeta (post_id, meta_key, meta_value) VALUES (%d, %s, %s)', $this->id, $key, $value));
        }
        return $this->id;
    }
}
function wc_get_product($id) {
    global $wpdb;
    $value = $wpdb->get_var($wpdb->prepare('SELECT data FROM posts WHERE ID = %d', $id));
    if ($value === null) { return false; }
    $p = new WC_Product_Simple(); $p->id = (int) $id; $p->data = json_decode($value, true);
    foreach (get_post_meta($id) as $key => $v) { $p->meta[$key] = $v[0]; }
    return $p;
}
function seed(): WC_Product_Simple {
    $p = new WC_Product_Simple();
    $p->set_name('TOWER OF GOD 01'); $p->set_status('publish'); $p->set_regular_price('15.00'); $p->set_sale_price('14.25');
    $p->set_category_ids([20, 30]); $p->update_meta_data('_yk_item_kind', 'manga'); $p->update_meta_data('_yk_isbn', '9788413349992');
    $p->update_meta_data('_yk_brand', 'PANINI COMICS'); $p->set_description('<p>Sinopsis <strong>original</strong></p>'); $p->save(); return $p;
}
function entry($p, array $changes = []): array { return ['id' => $p->get_id(), 'expected_revision' => store_snapshot($p)['_store_revision'], 'changes' => $changes]; }
function fields($title): array { return ['title' => $title, 'isbn' => '', 'sku' => 'TEST-' . $title, 'retail_price' => '10.00', 'sale_price' => null,
    'tax_class' => 'tasa-reducida', 'yumekai_status' => 'outofstock', 'category_ids' => [20,30]]; }

$tests = [];
$tests['Tower of God categories override obsolete custom metadata without writing'] = function () {
    $p = seed(); $snapshot = store_snapshot($p);
    check($snapshot['work_type'] === 'Manhwa' && $snapshot['categories'] === ['Manwha/Manhua', 'Manwha'], 'Ignored real categories');
    check($snapshot['demographic'] === null && get_post_meta($p->id, '_yk_item_kind', true) === 'manga', 'Read modified metadata');
    check(store_importer_values($snapshot)['work_type'] === 'Manhwa', 'Mirror ignored real work type');
    check($snapshot['description'] === '<p>Sinopsis <strong>original</strong></p>', 'Changed HTML on read');
};
$tests['specific child wins and conflicting unrelated categories are exposed'] = function () {
    check(store_category_info([1,50], 'manga')['work_type'] === 'Manhwa', 'Ignored more specific child');
    check(store_category_info([1,30], 'manga')['category_issue'] !== null, 'Hid conflict');
    check(store_category_info([2], null)['demographic'] === 'Shonen', 'Ignored demographic ancestor');
    check(store_category_info([], 'manhua')['work_type'] === 'Manhua', 'Lost legacy fallback');
    rejects(fn() => store_category_info([999], 'manga'), 503);
};
$tests['category-only and raw-meta changes invalidate optimistic revision'] = function () {
    $p = seed(); $before = store_snapshot($p)['_store_revision'];
    $p->set_category_ids([1]); $p->save();
    check(store_snapshot($p)['_store_revision'] !== $before, 'Missed category change');
    $before = store_snapshot($p)['_store_revision']; $p->update_meta_data('_other_plugin_field', 'changed'); $p->save();
    check(store_snapshot($p)['_store_revision'] !== $before, 'Missed plugin metadata');
    check(store_snapshot($p)['_store_revision'] === store_snapshot($p)['_store_revision'], 'Unstable token');
};
$tests['despublishing is reversible and retains product and metadata'] = function () {
    $p = seed(); $result = store_catalog_action('unpublish', [entry($p)]);
    check(count($result['saved']) === 1 && $result['failed'] === [], 'Failed unpublish');
    $draft = wc_get_product($p->id);
    check($draft->get_status('edit') === 'draft' && get_post_meta($p->id, '_yk_isbn', true) === '9788413349992', 'Deleted product or metadata');
    $result = store_catalog_action('publish', [entry($draft)]);
    check($result['saved'][0]['id'] === $p->id && wc_get_product($p->id)->get_status('edit') === 'publish', 'Could not restore same product');
};
$tests['stale revision does not overwrite an external edit'] = function () {
    $p = seed(); $request = entry($p); $p->set_name('External edit'); $p->save();
    $result = store_catalog_action('unpublish', [$request]);
    check($result['saved'] === [] && $result['failed'][0]['status_code'] === 409, 'Accepted stale revision');
    check(wc_get_product($p->id)->get_status('edit') === 'publish', 'Partially changed status');
};
$tests['partial batch confirms each success and conflict separately'] = function () {
    $a = seed(); $b = seed(); $entries = [entry($a), entry($b)]; $b->set_name('Another edit'); $b->save();
    $result = store_catalog_action('unpublish', $entries);
    check(count($result['saved']) === 1 && $result['saved'][0]['id'] === $a->id && $result['failed'][0]['id'] === $b->id, 'Incorrect partial receipt');
};
$tests['new product is always a draft and replay is idempotent'] = function () {
    global $wpdb;
    $data = fields('Nuevo'); $id = str_repeat('a', 32);
    $before = (int) $wpdb->get_var('SELECT COUNT(*) FROM posts');
    $one = store_catalog_create($data, $id); $two = store_catalog_create($data, $id);
    check($one['id'] === $two['id'] && $one['product']['publication_status'] === 'draft', 'Replay duplicated product or auto-published');
    check((int) $wpdb->get_var('SELECT COUNT(*) FROM posts') === $before + 1, 'Created twice');
    rejects(fn() => store_catalog_create(fields('Otro título'), $id), 409);
    check(wc_get_product($one['id'])->get_name('edit') === 'Nuevo', 'Changed replay overwrote existing product');
};
$tests['create detects duplicate ISBN and rolls back token and product'] = function () {
    global $wpdb;
    $p = seed(); $data = fields('Duplicado'); $data['isbn'] = '9788413349992'; $token = str_repeat('b',32);
    $before = (int) $wpdb->get_var('SELECT COUNT(*) FROM posts');
    rejects(fn() => store_catalog_create($data, $token), 409);
    check((int) $wpdb->get_var('SELECT COUNT(*) FROM posts') === $before, 'Partial duplicate');
    check($wpdb->get_var($wpdb->prepare('SELECT option_value FROM options WHERE option_name = %s', 'yumekai_create_' . $token)) === null, 'Kept incomplete claim');
};
$tests['manual category edits keep legacy field consistent and preserve other data'] = function () {
    $p = seed(); $result = store_catalog_action('update', [entry($p, ['category_ids' => [1,2]])]);
    $row = $result['saved'][0]['product'];
    check($row['work_type'] === 'Manga' && $row['demographic'] === 'Shonen', 'Categories not applied');
    check(get_post_meta($p->id, '_yk_item_kind', true) === 'manga', 'Legacy mismatch');
    check($row['retail_price'] === '15.00' && $row['sale_price'] === '14.25', 'Changed unrelated prices');
};
$tests['manual prices are independent and removing regular with a sale is rejected'] = function () {
    $p = seed(); $r = store_catalog_action('update', [entry($p, ['retail_price' => '20.00'])]);
    check($r['saved'][0]['product']['sale_price'] === '14.25', 'Recalculated sale');
    $p = wc_get_product($p->id); $r = store_catalog_action('update', [entry($p, ['retail_price' => null])]);
    check($r['failed'][0]['status_code'] === 400 && wc_get_product($p->id)->get_regular_price('edit') === '20.00', 'Accepted inconsistent price');
};
$tests['invalid fields and categories are rejected before any write'] = function () {
    rejects(fn() => store_catalog_validate(['force_delete' => 'yes']), 400);
    rejects(fn() => store_catalog_validate(['category_ids' => [999]]), 409);
    rejects(fn() => store_catalog_validate(['category_ids' => [1,30]]), 400);
    rejects(fn() => store_catalog_validate(['sale_price' => '10.123']), 400);
    rejects(fn() => store_catalog_validate(['pages' => '-1']), 400);
    rejects(fn() => store_catalog_validate(['tax_class' => 'invented']), 400);
    rejects(fn() => store_catalog_validate(['title' => 'Nuevo'], true), 400);
    rejects(fn() => store_catalog_action('delete', [['id' => 1]]), 400);
};
$tests['managed stock cannot be changed accidentally'] = function () {
    $p = seed(); $p->set_manage_stock(true); $p->save();
    $r = store_catalog_action('update', [entry($p, ['title' => 'Must roll back', 'yumekai_status' => 'instock'])]);
    check($r['failed'][0]['status_code'] === 409 && wc_get_product($p->id)->get_name('edit') === 'TOWER OF GOD 01', 'Partially wrote managed product');
};
$tests['SD synopsis and stock use the tested writer'] = function () {
    $p = seed();
    store_apply_changes($p, ['description' => '<p>Sinopsis SD</p>', 'yumekai_status' => 'instock']);
    $row = store_snapshot(wc_get_product($p->id));
    check($row['description'] === '<p>Sinopsis SD</p>' && $row['yumekai_status'] === 'instock', 'Regressed SD save');
    check($row['work_type'] === 'Manhwa' && $row['retail_price'] === '15.00', 'Changed unrelated category or price');
};
$tests['publishing requires title and price for simple drafts'] = function () {
    $p = new WC_Product_Simple(); $p->set_name('Incompleto'); $p->save();
    $r = store_catalog_action('publish', [entry($p)]);
    check($r['saved'] === [] && $r['failed'][0]['status_code'] === 400 && wc_get_product($p->id)->get_status('edit') === 'draft', 'Published incomplete draft');
};
$tests['publication status is verified in database before confirming success'] = function () {
    $p = seed(); $GLOBALS['ignore_status_write'] = true;
    try { $r = store_catalog_action('unpublish', [entry($p)]); }
    finally { $GLOBALS['ignore_status_write'] = false; }
    check($r['saved'] === [] && $r['failed'][0]['status_code'] === 409, 'Trusted cached object instead of persisted status');
    check(wc_get_product($p->id)->get_status('edit') === 'publish', 'Did not roll back inconsistent state');
};
$tests['W3 Total Cache purge runs after commit and targets original product URL'] = function () {
    $p = seed(); $GLOBALS['cache_flushes'] = []; $GLOBALS['cache_urls'] = [];
    $r = store_catalog_action('unpublish', [entry($p)]);
    check($r['saved'][0]['verification']['database_status'] === 'draft', 'Missing real-state confirmation');
    check($GLOBALS['cache_flushes'] === [['id' => $p->id, 'force' => true, 'in_transaction' => false]], 'Purged before commit or wrong product');
    check($GLOBALS['cache_urls'] === ['https://example.test/product/' . $p->id], 'Forgot former published URL');
};
$tests['draft retirement can be verified without publishing it first'] = function () {
    $p = seed(); $p->set_status('draft'); $p->save();
    $r = store_catalog_action('unpublish', [entry($p)]);
    check(count($r['saved']) === 1 && $r['saved'][0]['product']['publication_status'] === 'draft', 'Failed idempotent retirement');
};
$tests['cache failure reports warning with committed draft instead of false rollback'] = function () {
    $p = seed(); $GLOBALS['cache_should_fail'] = true;
    try { $r = store_catalog_action('unpublish', [entry($p)]); }
    finally { $GLOBALS['cache_should_fail'] = false; }
    check(count($r['saved']) === 1 && count($r['saved'][0]['warnings']) === 1, 'Did not distinguish cache problem');
    check(wc_get_product($p->id)->get_status('edit') === 'draft', 'Lost confirmed database state');
};
$tests['shop identifier falls back to YMK SKU only when custom ISBN is empty'] = function () {
    $p = new WC_Product_Simple(); $p->set_sku('YMK-9788498852684'); $p->save();
    check(store_snapshot($p)['isbn'] === '9788498852684' && store_snapshot($p)['identifier_source'] === '_sku', 'Missed imported SKU');
    $p->update_meta_data('_yk_isbn', '9788411504898'); $p->save();
    check(store_snapshot($p)['isbn'] === '9788411504898' && store_snapshot($p)['identifier_source'] === '_yk_isbn', 'Overrode explicit ISBN');
};
$tests['draft canonical link is calculated without publishing the actual post'] = function () {
    $p = seed(); $p->set_status('draft'); $p->save();
    $GLOBALS['url_sample_post'] = (object) ['ID' => $p->id, 'post_name' => 'afro-samurai-edicion-completa', 'post_status' => 'draft'];
    $url = store_product_url($p);
    check($url === 'https://example.test/product/' . $p->id && $GLOBALS['sample_link_status'] === 'publish', 'Failed canonical link calculation');
    check($GLOBALS['url_sample_post']->post_status === 'draft' && wc_get_product($p->id)->get_status('edit') === 'draft', 'Published a draft to get its link');
    unset($GLOBALS['url_sample_post']);
};
foreach ($tests as $name => $test) { $test(); echo 'OK: ' . $name . PHP_EOL; }
echo count($tests) . ' catalog regression tests passed' . PHP_EOL;
