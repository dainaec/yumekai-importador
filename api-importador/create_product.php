<?php

ini_set('display_errors', '0');

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
require_once __DIR__ . '/exception_rules.php';

function send_json(int $status, array $body): void
{
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Allow: POST');
    send_json(405, ['error' => 'method_not_allowed']);
}

$contentType = explode(';', $_SERVER['CONTENT_TYPE'] ?? '', 2)[0];

if (strtolower(trim($contentType)) !== 'application/json') {
    send_json(415, ['error' => 'unsupported_media_type']);
}

function product_values(array $data): array {
    $isbn = $data['isbn'] ?? null;
    $title = $data['title'] ?? null;

    if (!product_code_valid($isbn)) {
        send_json(400, ['error' => 'invalid_isbn', 'message' => 'Falta el código o supera los 128 caracteres admitidos.']);
    }

    if (!is_string($title) || trim($title) === '' || strlen($title) > 65535) {
        send_json(400, ['error' => 'invalid_title']);
    }

    $price = $data['retail_price'] ?? null;

    if ($price !== null && (
        !is_string($price) || preg_match('/\A-?[0-9]{1,8}\.[0-9]{2}\z/', $price) !== 1
    )) {
        send_json(400, ['error' => 'invalid_retail_price']);
    }

    $pages = $data['pages'] ?? null;

    if ($pages !== null && (!is_int($pages) || $pages < 1 || $pages > 4294967295)) {
        send_json(400, ['error' => 'invalid_pages']);
    }

    $categories = $data['categories'] ?? [];

    if (!is_array($categories)) {
        send_json(400, ['error' => 'invalid_categories']);
    }

    foreach ($categories as $category) {
        if (!is_string($category)) {
            send_json(400, ['error' => 'invalid_categories']);
        }
    }

    	$data['language'] = $data['language'] ?? 'Castellano';

    $values = [
        'isbn' => $isbn,
        'title' => trim($title),
        'retail_price' => $price,
        'pages' => $pages,
        'categories' => json_encode($categories, JSON_UNESCAPED_UNICODE),
    ];

    $textFields = [
        'author', 'description', 'image_url', 'publisher', 'series',
        'volume', 'language', 'book_format', 'work_type', 'demographic', 'yumekai_status',
    ];

    foreach ($textFields as $field) {
        $value = $data[$field] ?? null;

        if ($value !== null && !is_string($value)) {
            send_json(400, ['error' => 'invalid_field', 'field' => $field]);
        }

        $values[$field] = $value;
    }

    $warnings = product_exception_warnings($values, false);
    if ($warnings !== [] && ($data['exceptions_confirmed'] ?? false) !== true) {
        send_json(400, ['error' => 'exceptions_confirmation_required',
            'message' => "Autoriza expresamente las excepciones de {$isbn} antes de guardar: " . implode('; ', $warnings)]);
    }
    return $values;
}

$request = json_decode(file_get_contents('php://input'));

if (!is_object($request)) {
    send_json(400, ['error' => 'invalid_payload']);
}

$isBatch = property_exists($request, 'products');
$items = $isBatch ? $request->products : [$request];

if (!is_array($items) || $items === []) {
    send_json(400, ['error' => 'empty_or_invalid_batch']);
}

$rows = [];

foreach ($items as $item) {
    if (!is_object($item)) {
        send_json(400, ['error' => 'invalid_product']);
    }

    $rows[] = product_values((array) $item);
}

try {
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';

    $fields = array_keys($rows[0]);
    $columns = implode(', ', $fields);
    $parameters = ':' . implode(', :', $fields);
    $statement = $pdo->prepare(
        "INSERT INTO products ($columns) VALUES ($parameters)"
    );

    $created = 0;
    $duplicates = 0;

    $pdo->beginTransaction();

    foreach ($rows as $values) {
        try {
            $statement->execute($values);
            $created++;
        } catch (PDOException $error) {
            if ((int) ($error->errorInfo[1] ?? 0) !== 1062) {
                throw $error;
            }

            $duplicates++;
        }
    }

    $pdo->commit();

    if ($isBatch) {
        send_json(200, ['created' => $created, 'duplicates' => $duplicates]);
    }

    if ($duplicates > 0) {
        send_json(409, ['error' => 'duplicate_isbn']);
    }

    send_json(201, ['isbn' => $rows[0]['isbn']]);
} catch (Throwable $error) {
    if (isset($pdo) && $pdo->inTransaction()) {
        $pdo->rollBack();
    }

    error_log('Yumekai create products: ' . $error->getCode());
    if ($error instanceof PDOException && (int) ($error->errorInfo[1] ?? 0) === 1406
        && preg_match('/isbn|sku/i', $error->errorInfo[2] ?? '')) {
        send_json(400, ['error' => 'code_column_too_short',
            'message' => 'El campo ISBN/SKU de la base de datos es demasiado corto. Ejecuta ampliar_codigos_productos.sql en la base del importador.']);
    }
    send_json(500, ['error' => 'server_error']);
}
