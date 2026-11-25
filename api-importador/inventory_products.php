<?php

declare(strict_types=1);

ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

require __DIR__ . '/review_common.php';

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    header('Allow: GET');
    review_response(405, ['message' => 'Usa GET para consultar el inventario.']);
}

try {
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

    $statement = $pdo->query(
        'SELECT ' . REVIEW_COLUMNS . ', woocommerce_id
         FROM products
         WHERE woocommerce_id IS NOT NULL
         ORDER BY title, isbn'
    );

    $products = array_map(
        'review_row',
        $statement->fetchAll(PDO::FETCH_ASSOC)
    );

    foreach ($products as &$product) {
        $product['woocommerce_id'] = (int) $product['woocommerce_id'];
    }
    unset($product);

    review_response(200, $products);
} catch (Throwable $error) {
    yumekai_log('request.failed', ['type' => get_class($error), 'message' => $error->getMessage()]);
    error_log('Yumekai inventory: ' . $error->getMessage());

    review_response(500, [
        'message' => 'No se pudieron cargar las fichas del inventario.'
    ]);
}