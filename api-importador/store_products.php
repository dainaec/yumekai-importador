<?php

declare(strict_types=1);

ini_set('display_errors', '0');

function store_response(int $status, array $data): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');

    echo json_encode(
        $data,
        JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR
    );
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    header('Allow: GET');
    store_response(405, ['message' => 'Usa GET para consultar la tienda.']);
}

$bufferLevel = ob_get_level();

try {
    $wordpressPath = dirname(__DIR__) . '/wp-load.php';

    if (!is_file($wordpressPath)) {
        throw new RuntimeException('No se encuentra wp-load.php.');
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

    global $wpdb;
    $wpdb->suppress_errors(true);

    $products = $wpdb->get_results(
        "SELECT
            p.ID AS woocommerce_id,
            p.post_title AS title,
            TRIM(m.meta_value) AS isbn
        FROM {$wpdb->posts} AS p
        INNER JOIN {$wpdb->postmeta} AS m
            ON m.post_id = p.ID
            AND m.meta_key = '_yk_isbn'
        WHERE p.post_type = 'product'
          AND p.post_status = 'publish'
          AND TRIM(m.meta_value) <> ''
        ORDER BY p.ID",
        ARRAY_A
    );

    if ($wpdb->last_error !== '' || !is_array($products)) {
        throw new RuntimeException('Error al consultar los productos.');
    }

    foreach ($products as &$product) {
        $product['woocommerce_id'] = (int) $product['woocommerce_id'];
    }
    unset($product);

    store_response(200, $products);
} catch (Throwable $error) {
    while (ob_get_level() > $bufferLevel) {
        ob_end_clean();
    }

    error_log('Yumekai store products: ' . $error->getMessage());

    store_response(500, [
        'message' => 'No se pudo consultar la tienda. Revisa la ruta de WordPress y el registro de errores.'
    ]);
}