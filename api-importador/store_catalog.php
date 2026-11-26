<?php
declare(strict_types=1);
ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
require_once __DIR__ . '/store_catalog_common.php';
$started = microtime(true);
try {
    $method = $_SERVER['REQUEST_METHOD'];
    if (!in_array($method, ['GET', 'POST'], true)) { header('Allow: GET, POST'); throw new ReviewRequestError('Usa GET o POST.', 405); }
    if ($method === 'POST' && strtolower(trim(explode(';', $_SERVER['CONTENT_TYPE'] ?? '', 2)[0])) !== 'application/json') {
        throw new ReviewRequestError('Envía los datos en JSON.', 415);
    }
    // Keep WordPress bootstrap at file scope, as in the tested SD endpoint.
    $wordpressPath = dirname(__DIR__) . '/wp-load.php';
    if (!is_file($wordpressPath)) { throw new ReviewRequestError('No se encuentra WordPress junto a importer-api.', 503); }
    if (!defined('WP_USE_THEMES')) { define('WP_USE_THEMES', false); }
    if (!defined('DISABLE_WP_CRON')) { define('DISABLE_WP_CRON', true); }
    $level = ob_get_level();
    ob_start();
    try { require_once $wordpressPath; }
    finally { while (ob_get_level() > $level) { ob_end_clean(); } }
    if (!function_exists('wc_get_product')) { throw new ReviewRequestError('WooCommerce no está disponible.', 503); }
    $booted = microtime(true);
    if ($method === 'GET') {
        $status = $_GET['status'] ?? 'publish';
        if (!in_array($status, array_merge(STORE_PUBLICATION_STATUSES, ['all']), true)) { throw new ReviewRequestError('Filtro de publicación no válido.', 400); }
        $page = filter_var($_GET['page'] ?? 1, FILTER_VALIDATE_INT);
        $limit = filter_var($_GET['per_page'] ?? 200, FILTER_VALIDATE_INT);
        if (!$page || $page < 1 || $page > 10000 || !$limit || $limit < 1 || $limit > 250) { throw new ReviewRequestError('Página o tamaño no válido.', 400); }
        $statuses = $status === 'all' ? STORE_PUBLICATION_STATUSES : [$status];
        $result = wc_get_products(['status' => $statuses, 'limit' => $limit, 'page' => $page,
            'return' => 'ids', 'paginate' => true, 'orderby' => 'ID', 'order' => 'ASC']);
        store_prime_products($result->products);
        $rows = [];
        foreach ($result->products as $id) {
            $product = wc_get_product($id);
            if (!$product || !in_array($product->get_status('edit'), $statuses, true)) {
                throw new ReviewRequestError('El catálogo cambió durante la lectura. Recarga para comprobarlo.', 409);
            }
            $rows[] = store_snapshot($product);
        }
        $options = $page === 1 ? store_catalog_options() : null;
        $timing = ['bootstrap_ms' => (int) round(1000 * ($booted - $started)),
            'query_ms' => (int) round(1000 * (microtime(true) - $booted))];
        yumekai_log('store.page_loaded', ['page' => $page, 'status' => $status, 'products' => count($rows), 'timing' => $timing]);
        review_response(200, ['api_version' => 3, 'products' => $rows, 'page' => $page, 'pages' => (int) $result->max_num_pages,
            'total' => (int) $result->total, 'status' => $status, 'options' => $options, 'timing' => $timing]);
    }
    if ((int) ($_SERVER['CONTENT_LENGTH'] ?? 0) > 2000000) { throw new ReviewRequestError('El envío es demasiado grande.', 413); }
    $payload = json_decode(file_get_contents('php://input'), true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($payload) || !is_string($payload['action'] ?? null)) { throw new ReviewRequestError('Solicitud de catálogo no válida.', 400); }
    if ($payload['action'] === 'create') {
        if (!is_array($payload['fields'] ?? null) || !is_string($payload['request_id'] ?? null)) { throw new ReviewRequestError('Faltan los datos del nuevo producto.', 400); }
        review_response(200, ['api_version' => 3] + store_catalog_create($payload['fields'], $payload['request_id']));
    }
    if (!is_array($payload['products'] ?? null)) { throw new ReviewRequestError('Faltan los productos.', 400); }
    review_response(200, ['api_version' => 3] + store_catalog_action($payload['action'], $payload['products']));
} catch (Throwable $error) {
    yumekai_log('store.catalog_error', ['type' => get_class($error), 'message' => $error->getMessage()]);
    $code = $error instanceof ReviewRequestError ? $error->getCode() : ($error instanceof WC_Data_Exception || $error instanceof JsonException ? 400 : 500);
    review_response($code, ['message' => $code < 500 ? $error->getMessage() : 'No se pudo completar la operación. Recarga la tienda y revisa el registro antes de reintentar.']);
}
