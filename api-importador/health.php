<?php
require_once __DIR__ . "/event_log.php";

ini_set('display_errors', '0');

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

try {
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';

    $pdo->query('SELECT isbn FROM products LIMIT 1');

    echo '{"ok":true}';
} catch (Throwable $error) {
    yumekai_log('request.failed', ['type' => get_class($error), 'message' => $error->getMessage()]);
    error_log('Yumekai importer database check: ' . $error->getCode());
    http_response_code(500);
    echo '{"ok":false}';
}