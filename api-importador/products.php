<?php

declare(strict_types=1);
ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
require __DIR__ . '/review_common.php';

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    header('Allow: GET');
    review_response(405, ['message' => 'Usa GET para consultar fichas.']);
}
$status = $_GET['review_status'] ?? 'pending_review';
if (!is_string($status) || !in_array($status, REVIEW_STATUSES, true)) {
    review_response(400, ['message' => 'El estado de revisión no es válido.']);
}
try {
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $statement = $pdo->prepare('SELECT ' . REVIEW_COLUMNS . ' FROM products
        WHERE review_status = :status
        AND woocommerce_id IS NULL
        ORDER BY title, isbn');
    $statement->execute(['status' => $status]);
    review_response(200, array_map('review_row', $statement->fetchAll(PDO::FETCH_ASSOC)));
} catch (Throwable $error) {
    yumekai_log('request.failed', ['type' => get_class($error), 'message' => $error->getMessage()]);
    error_log('Yumekai review list: ' . $error->getCode());
    review_response(500, ['message' => 'No se pudieron cargar las fichas del importador.']);
}
