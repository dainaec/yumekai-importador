<?php
declare(strict_types=1);
ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
require_once __DIR__ . '/store_common.php';

try {
    $method = $_SERVER['REQUEST_METHOD'];
    if (!in_array($method, ['GET', 'POST'], true)) {
        header('Allow: GET, POST');
        throw new ReviewRequestError('Usa GET para consultar o POST para aplicar cambios.', 405);
    }
    if ($method === 'POST' && strtolower(trim(explode(';', $_SERVER['CONTENT_TYPE'] ?? '', 2)[0])) !== 'application/json') {
        throw new ReviewRequestError('Envía los cambios en formato JSON.', 415);
    }
    // Bootstrap at file scope so WordPress globals have their normal lifetime.
    $wordpressPath = dirname(__DIR__) . '/wp-load.php';
    if (!is_file($wordpressPath)) {
        throw new ReviewRequestError('No se encuentra WordPress junto a importer-api.', 503);
    }
    if (!defined('WP_USE_THEMES')) { define('WP_USE_THEMES', false); }
    if (!defined('DISABLE_WP_CRON')) { define('DISABLE_WP_CRON', true); }
    $bufferLevel = ob_get_level();
    ob_start();
    try { require_once $wordpressPath; }
    finally { while (ob_get_level() > $bufferLevel) { ob_end_clean(); } }
    if (!function_exists('wc_get_product')) {
        throw new ReviewRequestError('WooCommerce no está disponible.', 503);
    }
    if ($method === 'GET') {
        $page = filter_var($_GET['page'] ?? 1, FILTER_VALIDATE_INT);
        if (!$page || $page < 1 || $page > 10000) { throw new ReviewRequestError('Página no válida.', 400); }
        $result = wc_get_products(['status' => 'publish', 'limit' => 100, 'page' => $page,
            'return' => 'ids', 'paginate' => true, 'orderby' => 'ID', 'order' => 'ASC']);
        store_prime_products($result->products);
        $rows = [];
        foreach ($result->products as $id) {
            $product = wc_get_product($id);
            if (!$product || $product->get_status('edit') !== 'publish') {
                throw new ReviewRequestError('El catálogo cambió durante la consulta. Recarga para comprobarlo.', 409);
            }
            $rows[] = store_snapshot($product);
        }
        review_response(200, ['products' => $rows,
            'page' => $page, 'pages' => (int) $result->max_num_pages, 'total' => (int) $result->total]);
    }
    $payload = json_decode(file_get_contents('php://input'));
    if (!is_object($payload) || !is_array($payload->products ?? null)
        || count($payload->products) < 1 || count($payload->products) > 100) {
        throw new ReviewRequestError('Envía entre 1 y 100 fichas por lote.', 400);
    }
    $seen = [];
    foreach ($payload->products as $entry) {
        if (!is_object($entry) || !is_int($entry->id ?? null) || $entry->id < 1
            || isset($seen[$entry->id]) || !is_string($entry->expected_revision ?? null)
            || preg_match('/\A[0-9a-f]{64}\z/', $entry->expected_revision) !== 1
            || !is_object($entry->changes ?? null)) {
            throw new ReviewRequestError('Revisa el ID, la versión y los cambios de cada ficha.', 400);
        }
        store_validate_changes((array) $entry->changes);
        $seen[$entry->id] = true;
    }
    global $wpdb;
    $saved = $failed = [];
    foreach ($payload->products as $entry) {
        $transaction = false;
        try {
            if ($wpdb->query('START TRANSACTION') === false) { throw new RuntimeException('No se pudo iniciar la operación.'); }
            $transaction = true;
            // Lock current post + metadata while verifying and saving the accepted snapshot.
            $locked = $wpdb->get_var($wpdb->prepare("SELECT ID FROM {$wpdb->posts} WHERE ID = %d AND post_type = 'product' FOR UPDATE", $entry->id));
            if (!$locked) { throw new ReviewRequestError('La ficha ya no existe en WooCommerce.', 409); }
            $wpdb->get_results($wpdb->prepare("SELECT meta_id FROM {$wpdb->postmeta} WHERE post_id = %d FOR UPDATE", $entry->id));
            if ($wpdb->last_error) { throw new RuntimeException('No se pudo comprobar la ficha actual.'); }
            clean_post_cache($entry->id);
            $product = wc_get_product($entry->id);
            if (!$product || $product->get_status('edit') !== 'publish') {
                throw new ReviewRequestError('La ficha ya no está publicada. Recarga para revisarla.', 409);
            }
            if ($product->get_type() !== 'simple') {
                throw new ReviewRequestError('La actualización está preparada para productos simples. Revisa esta ficha en WooCommerce.', 400);
            }
            if (!hash_equals(store_snapshot($product)['_store_revision'], $entry->expected_revision)) {
                throw new ReviewRequestError('La ficha ha cambiado en WooCommerce desde que la leíste. Sus propuestas se conservan. Recarga y consulta SD para preparar cambios sobre la versión actual.', 409);
            }
            store_apply_changes($product, (array) $entry->changes);
            if ($wpdb->last_error) { throw new RuntimeException('No se pudo guardar la ficha.'); }
            $updated = store_snapshot($product);
            if ($wpdb->query('COMMIT') === false) { throw new RuntimeException('No se pudo confirmar el guardado.'); }
            $transaction = false;
            $saved[] = ['id' => $entry->id, 'product' => $updated];
            yumekai_log('store.updated', ['id' => $entry->id, 'fields' => array_keys((array) $entry->changes)]);
        } catch (Throwable $error) {
            if ($transaction) { $wpdb->query('ROLLBACK'); }
            clean_post_cache($entry->id);
            wc_delete_product_transients($entry->id);
            $known = $error instanceof ReviewRequestError;
            yumekai_log('store.update_failed', ['id' => $entry->id, 'message' => $error->getMessage()]);
            if (!$known) { error_log('Yumekai store update: ' . $error->getMessage()); }
            $failed[] = ['id' => $entry->id, 'message' => $known ? $error->getMessage() : 'No se pudo confirmar esta ficha. Recarga antes de reintentar.',
                'status_code' => $known ? $error->getCode() : 500];
            // An ambiguous failure stops the rest; never retry an unconfirmed write automatically.
            if (!$known) { break; }
        }
    }
    $finished = array_merge(array_column($saved, 'id'), array_column($failed, 'id'));
    foreach ($payload->products as $entry) {
        if (!in_array($entry->id, $finished, true)) {
            $failed[] = ['id' => $entry->id, 'message' => 'Sin enviar: lote detenido tras un resultado sin confirmar.', 'status_code' => 503];
        }
    }
    review_response(200, ['saved' => $saved, 'failed' => $failed]);
} catch (Throwable $error) {
    $known = $error instanceof ReviewRequestError;
    if (!$known) { error_log('Yumekai store API: ' . $error->getMessage()); }
    review_response($known ? $error->getCode() : 500,
        ['message' => $known ? $error->getMessage() : 'No se pudo consultar o actualizar WooCommerce.']);
}
