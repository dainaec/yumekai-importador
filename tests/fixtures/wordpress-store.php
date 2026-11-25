<?php
// Local WordPress/WooCommerce test double. Not for deployment.
class FixtureWPDB {
    public $posts = 'posts';
    public $postmeta = 'postmeta';
    public $last_error = '';
    public $db;
    function __construct() {
        $this->db = new PDO('sqlite:' . __DIR__ . '/../store.sqlite');
        $this->db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    }
    function query($sql) {
        $this->last_error = '';
        if ($sql === 'START TRANSACTION') { $this->db->beginTransaction(); return 1; }
        if ($sql === 'COMMIT') { $this->db->commit(); return 1; }
        if ($sql === 'ROLLBACK') { if ($this->db->inTransaction()) { $this->db->rollBack(); } return 1; }
        return $this->db->exec($sql);
    }
    function prepare($sql, $id) { return sprintf($sql, $id); }
    function get_var($sql) {
        preg_match('/WHERE ID = ([0-9]+)/', $sql, $match);
        $query = $this->db->prepare('SELECT id FROM products WHERE id=?');
        $query->execute([(int) $match[1]]);
        return $query->fetchColumn();
    }
    function get_results($sql) { return []; }
}
$wpdb = new FixtureWPDB();

class FixtureProduct {
    public $data;
    function __construct($data) { $this->data = $data; }
    function get_id() { return $this->data['id']; }
    function get_name($context='view') { return $this->data['title']; }
    function get_description($context='view') { return $this->data['description']; }
    function get_short_description($context='view') { return $this->data['short_description']; }
    function get_regular_price($context='view') { return $this->data['regular_price']; }
    function get_sale_price($context='view') { return $this->data['sale_price']; }
    function get_stock_status($context='view') { return $this->data['stock_status']; }
    function get_sku($context='view') { return $this->data['sku']; }
    function get_manage_stock($context='view') { return $this->data['manage_stock']; }
    function get_stock_quantity($context='view') { return $this->data['stock_quantity']; }
    function get_backorders($context='view') { return $this->data['backorders']; }
    function get_type() { return $this->data['type']; }
    function get_status($context='view') { return $this->data['status']; }
    function get_featured($context='view') { return $this->data['featured']; }
    function get_meta($key,$single=true,$context='view') { return $this->data['meta'][$key] ?? ''; }
    function get_category_ids($context='view') { return $this->data['categories']; }
    function get_image_id($context='view') { return $this->data['image_id']; }
    function set_stock_status($value) { $this->data['stock_status']=$value; }
    function set_description($value) { $this->data['description']=$value; }
    function set_regular_price($value) { $this->data['regular_price']=$value; }
    function set_sale_price($value) { $this->data['sale_price']=$value; }
    function update_meta_data($key,$value) { $this->data['meta'][$key]=$value; }
    function save() {
        global $wpdb;
        if (!empty($this->data['save_error'])) { throw new RuntimeException('Simulated save failure'); }
        $this->data['modified']++;
        $query=$wpdb->db->prepare('UPDATE products SET data=? WHERE id=?');
        $query->execute([json_encode($this->data),$this->get_id()]);
        return $this->get_id();
    }
}
function wc_get_product($id) {
    global $wpdb;
    $q=$wpdb->db->prepare('SELECT data FROM products WHERE id=?');
    $q->execute([$id]);
    $data=$q->fetchColumn();
    return $data === false ? false : new FixtureProduct(json_decode($data,true));
}
function wc_get_products($args) {
    global $wpdb;
    $all=[];
    foreach ($wpdb->db->query('SELECT data FROM products ORDER BY id') as $row) {
        $data=json_decode($row['data'],true);
        if ($data['status']===$args['status']) { $all[]=new FixtureProduct($data); }
    }
    return (object) ['products'=>array_slice($all,($args['page']-1)*$args['limit'],$args['limit']),
        'total'=>count($all),'max_num_pages'=>(int) ceil(count($all)/$args['limit'])];
}
function get_post_field($field,$id) { return (string) wc_get_product($id)->data['modified']; }
function get_term($id,$taxonomy) { return (object) ['name'=>[7=>'Manga',8=>'Seinen',99=>'Categoría editada'][$id] ?? 'Otra']; }
function is_wp_error($value) { return false; }
function wp_get_attachment_url($id) { return $id ? 'https://example.test/cover-'.$id.'.jpg' : false; }
function clean_post_cache($id) {}
function wc_delete_product_transients($id) {}
function sanitize_text_field($text) { return strip_tags($text); }
function wp_kses_post($text) { return strip_tags($text,'<p><br><strong><em>'); }
function wc_get_product_stock_status_options() {
    return ['instock'=>'Hay existencias','outofstock'=>'Sin existencias','onbackorder'=>'Se puede reservar','yk_on_demand'=>'Bajo demanda'];
}
