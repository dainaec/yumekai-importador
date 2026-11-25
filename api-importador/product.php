<?php

ini_set('display_errors', '0');

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$method = $_SERVER['REQUEST_METHOD'];

if ($method !== 'GET' && $method !== 'POST') {
    header('Allow: GET, POST');
    http_response_code(405);
    echo '{"error":"method_not_allowed"}';
    exit;
}

require_once __DIR__ . '/exception_rules.php';
$isbn = $_GET['isbn'] ?? '';

if (!product_code_valid($isbn)) {
    http_response_code(400);
    echo '{"error":"invalid_isbn"}';
    exit;
}

try {
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';

    if ($method === 'POST') {
        $contentType = explode(';', $_SERVER['CONTENT_TYPE'] ?? '', 2)[0];

        if (strtolower(trim($contentType)) !== 'application/json') {
            http_response_code(415);
            echo '{"error":"unsupported_media_type"}';
            exit;
        }

        $data = json_decode(file_get_contents('php://input'), true);
        $receivedTitle = $data['title'] ?? null;
        $title = is_string($receivedTitle) ? trim($receivedTitle) : '';

        if ($title === '' || strlen($title) > 65535) {
            http_response_code(400);
            echo '{"error":"invalid_title"}';
            exit;
        }

        $update = $pdo->prepare(
            'UPDATE products SET title = :title WHERE isbn = :isbn'
        );
        $update->execute(['title' => $title, 'isbn' => $isbn]);
    }

    $statement = $pdo->prepare(
        'SELECT isbn, title, retail_price, language, review_status
         FROM products
         WHERE isbn = :isbn'
    );
    $statement->execute(['isbn' => $isbn]);
    $product = $statement->fetch(PDO::FETCH_ASSOC);

    if ($product === false) {
        http_response_code(404);
        echo '{"error":"product_not_found"}';
        exit;
    }

    echo json_encode($product, JSON_UNESCAPED_UNICODE);
} catch (Throwable $error) {
    error_log('Yumekai product read: ' . $error->getCode());
    http_response_code(500);
    echo '{"error":"server_error"}';
}
