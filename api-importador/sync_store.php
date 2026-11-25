<?php

declare(strict_types=1);

ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
require __DIR__ . '/review_common.php';

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

    global $wpdb;
    $wpdb->suppress_errors(true);
    $storeProducts = $wpdb->get_results(
        "SELECT p.ID AS woocommerce_id, TRIM(m.meta_value) AS isbn
         FROM `{$wpdb->posts}` AS p
         INNER JOIN `{$wpdb->postmeta}` AS m
             ON m.post_id = p.ID AND m.meta_key = '_yk_isbn'
         WHERE p.post_type = 'product'
           AND p.post_status = 'publish'
           AND TRIM(m.meta_value) <> ''
         ORDER BY p.ID",
        ARRAY_A
    );
    if ($wpdb->last_error !== '' || !is_array($storeProducts)) {
        throw new RuntimeException('No se pudo consultar el catálogo de la tienda.');
    }

    // Preparar un mapa ISBN -> ID y comprobar que las coincidencias son claras.
    $catalog = [];
    $isbnById = [];
    $invalid = 0;
    foreach ($storeProducts as $product) {
        $isbn = trim((string) $product['isbn']);
        $compact = preg_replace('/[\s-]+/u', '', $isbn);
        if (is_string($compact) && preg_match('/\A[0-9]{13}\z/', $compact)) {
            $isbn = $compact;
        }
        $id = (int) $product['woocommerce_id'];
        if (!product_code_valid($isbn) || $id < 1) {
            $invalid++;
            continue;
        }
        if ((isset($catalog[$isbn]) && $catalog[$isbn] !== $id)
            || (isset($isbnById[$id]) && $isbnById[$id] !== $isbn)) {
            throw new ReviewRequestError('Hay productos con ISBN o ID contradictorios en la tienda. Revisa sus ISBN antes de sincronizar.', 409);
        }
        $catalog[$isbn] = $id;
        $isbnById[$id] = $isbn;
    }
    ksort($catalog, SORT_STRING);

    // Guardar los vínculos en la base de datos del importador.
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $find = $pdo->prepare('SELECT woocommerce_id FROM products WHERE isbn = :isbn FOR UPDATE');
    $update = $pdo->prepare('UPDATE products SET woocommerce_id = :id
        WHERE isbn = :isbn AND woocommerce_id IS NULL');

    $linked = [];
    $alreadyLinked = 0;
    $notFound = 0;
    $pdo->beginTransaction();
    foreach ($catalog as $isbn => $id) {
        $isbn = (string) $isbn;
        $find->execute(['isbn' => $isbn]);
        $current = $find->fetch(PDO::FETCH_ASSOC);
        $find->closeCursor();
        if ($current === false) {
            $notFound++;
            continue;
        }
        if ($current['woocommerce_id'] !== null) {
            $alreadyLinked++;
            continue;
        }
        $update->execute(['id' => $id, 'isbn' => $isbn]);
        if ($update->rowCount() !== 1) {
            throw new RuntimeException('No se pudo guardar uno de los vínculos.');
        }
        $linked[] = ['isbn' => $isbn, 'woocommerce_id' => $id];
    }
    $pdo->commit();

    review_response(200, [
        'store_isbns' => count($catalog),
        'linked' => count($linked),
        'already_linked' => $alreadyLinked,
        'not_in_importer' => $notFound,
        'invalid_store_isbns' => $invalid,
        'products' => $linked,
    ]);
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
    error_log('Yumekai store sync: ' . $error->getMessage());
    review_response(500, ['message' => 'No se pudo completar la sincronización. No se guardó parcialmente el lote.']);
}
