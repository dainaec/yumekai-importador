<?php
declare(strict_types=1);

// Install inside the existing importer-api directory protected by Basic Auth.
ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function completion_respond(int $status, array $body): void
{
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    exit;
}

function completion_updates(): array
{
    $type = strtolower(trim(explode(';', $_SERVER['CONTENT_TYPE'] ?? '', 2)[0]));
    if ($type !== 'application/json') {
        completion_respond(415, ['message' => 'Envía la marca de ficha completa en formato JSON.']);
    }
    $raw = file_get_contents('php://input');
    if ($raw === false || strlen($raw) > 4 * 1024 * 1024) {
        completion_respond(413, ['message' => 'La selección de fichas es demasiado grande.']);
    }
    try {
        $body = json_decode($raw, false, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException $error) {
        completion_respond(400, ['message' => 'La solicitud no contiene JSON válido.']);
    }
    if (!is_object($body) || !is_bool($body->complete ?? null)
        || !is_array($body->isbns ?? null) || count($body->isbns) < 1 || count($body->isbns) > 5000) {
        completion_respond(400, ['message' => 'Selecciona las fichas cuya marca quieres cambiar.']);
    }
    $seen = [];
    foreach ($body->isbns as $isbn) {
        // This checks the request identifier only; ISBN-13 and product data are not validated.
        if (!is_string($isbn) || preg_match('/\A[^\x00-\x1f\x7f]{1,128}\z/u', $isbn) !== 1
            || isset($seen['isbn:' . $isbn])) {
            completion_respond(400, ['message' => 'La selección contiene un código vacío, inválido o repetido.']);
        }
        $seen['isbn:' . $isbn] = true;
    }
    $isbns = $body->isbns;
    sort($isbns, SORT_STRING);
    return [$isbns, $body->complete];
}

$method = $_SERVER['REQUEST_METHOD'] ?? '';
if (!in_array($method, ['GET', 'POST'], true)) {
    header('Allow: GET, POST');
    completion_respond(405, ['message' => 'Usa GET para leer las marcas o POST para cambiarlas.']);
}
$updates = $method === 'POST' ? completion_updates() : null;
$pdo = null;
try {
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    if ($method === 'GET') {
        $statement = $pdo->query('SELECT isbn FROM product_manual_completion ORDER BY isbn');
        $isbns = array_map('strval', $statement->fetchAll(PDO::FETCH_COLUMN));
        completion_respond(200, ['complete_isbns' => $isbns]);
    }

    [$isbns, $complete] = $updates;
    $lock = $pdo->prepare('SELECT isbn FROM products WHERE isbn = :isbn FOR UPDATE');
    $write = $pdo->prepare($complete
        ? 'INSERT INTO product_manual_completion (isbn) VALUES (:isbn) ON DUPLICATE KEY UPDATE isbn = isbn'
        : 'DELETE FROM product_manual_completion WHERE isbn = :isbn');
    $pdo->beginTransaction();
    foreach ($isbns as $isbn) {
        $lock->execute(['isbn' => $isbn]);
        $stored = $lock->fetchColumn();
        $lock->closeCursor();
        if ($stored === false || (string) $stored !== $isbn) {
            $pdo->rollBack();
            completion_respond(409, ['message' => 'Una de las fichas ya no existe o cambió de código. Actualiza la lista.']);
        }
        $write->execute(['isbn' => $isbn]);
    }
    $pdo->commit();
    completion_respond(200, ['isbns' => $isbns, 'complete' => $complete]);
} catch (Throwable $error) {
    if ($pdo instanceof PDO && $pdo->inTransaction()) {
        $pdo->rollBack();
    }
    error_log('Yumekai manual completion: ' . $error->getCode());
    if ($error instanceof PDOException && ($error->errorInfo[0] ?? '') === '42S02') {
        completion_respond(503, ['message' => 'Falta instalar manual_completion.sql en la base de datos del importador.']);
    }
    completion_respond(500, ['message' => 'No se pudo confirmar la marca de ficha completa. Actualiza la lista.']);
}
