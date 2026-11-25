<?php

declare(strict_types=1);

ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
require_once __DIR__ . '/store_mirror.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Allow: POST');
    review_response(405, ['message' => 'Usa POST para sincronizar con la tienda.']);
}

$contentType = strtolower(trim(explode(';', $_SERVER['CONTENT_TYPE'] ?? '', 2)[0]));
if ($contentType !== 'application/json') {
    review_response(415, ['message' => 'Envía la sincronización en formato JSON.']);
}
$payload = json_decode(file_get_contents('php://input'));
if (!is_object($payload) || ($payload->action ?? null) !== 'sync') {
    review_response(400, ['message' => 'Indica la acción sync para sincronizar.']);
}

$pdo = null;
$bufferLevel = ob_get_level();

try {
    // Leer la tienda usando la conexión que WordPress ya tiene configurada.
    $wordpressPath = dirname(__DIR__) . '/wp-load.php';
    if (!is_file($wordpressPath)) {
        throw new ReviewRequestError('No se encuentra wp-load.php.', 503);
    }
    if (!defined('WP_USE_THEMES')) {
        define('WP_USE_THEMES', false);
    }
    if (!defined('DISABLE_WP_CRON')) {
        define('DISABLE_WP_CRON', true);
    }

    ob_start();
    require_once $wordpressPath;
    while (ob_get_level() > $bufferLevel) {
        ob_end_clean();
    }
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');

    if (!function_exists('wc_get_product')) {
        throw new ReviewRequestError('WooCommerce no está disponible.', 503);
    }
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    // Read identities first; WordPress hydration happens before taking importer locks.
    $existing = $pdo->query('SELECT woocommerce_id FROM products WHERE woocommerce_id IS NOT NULL')
        ->fetchAll(PDO::FETCH_COLUMN);
    $published = wc_get_products(['status' => 'publish', 'limit' => -1, 'return' => 'ids',
        'orderby' => 'ID', 'order' => 'ASC']);
    global $wpdb;
    if (!is_array($published) || $wpdb->last_error !== '') {
        throw new RuntimeException('No se pudo obtener el catálogo completo de WooCommerce.');
    }
    $ids = array_values(array_unique(array_merge(array_map('intval', $published), array_map('intval', $existing))));
    $snapshots = [];
    foreach (array_chunk($ids, 100) as $batch) {
        store_prime_products($batch);
        foreach ($batch as $id) {
            $product = wc_get_product($id);
            if (!$product) {
                $post = get_post($id);
                if ($post && $post->post_type === 'product') {
                    throw new ReviewRequestError('WooCommerce no pudo leer una ficha que todavía existe. No se ha sincronizado ningún dato.', 503);
                }
            }
            $snapshots[$id] = $product ? store_snapshot($product) : null;
            if ($wpdb->last_error !== '') {
                throw new RuntimeException('No se pudo leer una ficha de WooCommerce.');
            }
        }
    }
    $pdo->beginTransaction();
    $current = $pdo->query('SELECT ' . REVIEW_COLUMNS . ', woocommerce_id FROM products FOR UPDATE')
        ->fetchAll(PDO::FETCH_ASSOC);
    // A new link created while WordPress was loading requires a fresh read, never a deletion guess.
    foreach ($current as $row) {
        if ($row['woocommerce_id'] !== null && !array_key_exists((int) $row['woocommerce_id'], $snapshots)) {
            throw new ReviewRequestError('Los vínculos cambiaron durante la sincronización. Vuelve a sincronizar.', 409);
        }
    }
    $summary = store_reconcile($pdo, $current, $snapshots);
    $pdo->commit();
    yumekai_log('store.synchronized', array_diff_key($summary, ['products' => true, 'issues' => true]));
    foreach ($summary['issues'] as $issue) { yumekai_log('store.sync_issue', $issue); }
    review_response(200, $summary);
} catch (Throwable $error) {
    while (ob_get_level() > $bufferLevel) {
        ob_end_clean();
    }
    if ($pdo instanceof PDO && $pdo->inTransaction()) {
        $pdo->rollBack();
    }
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    if ($error instanceof ReviewRequestError) {
        review_response($error->getCode(), ['message' => $error->getMessage()]);
    }
    yumekai_log('store.sync_failed', ['message' => $error->getMessage()]);
    error_log('Yumekai store sync: ' . $error->getMessage());
    review_response(500, ['message' => 'No se pudo completar la sincronización. No se guardó parcialmente el lote.']);
}
