<?php

declare(strict_types=1);
ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
require __DIR__ . '/review_common.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Allow: POST');
    review_response(405, ['message' => 'Usa POST para guardar o borrar fichas.']);
}
if (strtolower(trim(explode(';', $_SERVER['CONTENT_TYPE'] ?? '', 2)[0])) !== 'application/json') {
    review_response(415, ['message' => 'Envía las fichas en formato JSON.']);
}

$pdo = null;
$original = '';
try {
    $payload = json_decode(file_get_contents('php://input'));
    if (!is_object($payload) || !in_array($payload->action ?? null, ['save', 'ready', 'pending', 'delete'], true)
        || !is_array($payload->products ?? null) || count($payload->products) < 1 || count($payload->products) > 5000) {
        throw new ReviewRequestError('Selecciona entre 1 y 5000 fichas y una acción válida.', 400);
    }
    $action = $payload->action;
    $entries = [];
    foreach ($payload->products as $entry) {
        if (!is_object($entry) || !is_string($entry->original_isbn ?? null)
            || !product_code_valid($entry->original_isbn)
            || isset($entries[$entry->original_isbn])
            || !in_array($entry->expected_review_status ?? null, REVIEW_STATUSES, true)
            || !is_string($entry->expected_updated_at ?? null)
            || (isset($entry->expected_revision) && (!is_string($entry->expected_revision)
                || preg_match('/\A[0-9a-f]{64}\z/', $entry->expected_revision) !== 1))) {
            throw new ReviewRequestError('La solicitud contiene una ficha incompleta o repetida. Recarga las fichas.', 400);
        }
        if ($action === 'save' && (!is_object($entry->changes ?? null) || !is_bool($entry->ready_to_upload ?? null))) {
            throw new ReviewRequestError('Indica los cambios y si la ficha está lista para subir.', 400);
        }
        if (isset($entry->changes) && !is_object($entry->changes)) {
            throw new ReviewRequestError('Los cambios no son válidos.', 400);
        }
        if (property_exists($entry, 'exceptions_confirmed') && !is_bool($entry->exceptions_confirmed)) {
            throw new ReviewRequestError('La autorización de excepciones debe ser explícita.', 400);
        }
        $entries[$entry->original_isbn] = $entry;
    }
    ksort($entries, SORT_STRING);
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $lock = $pdo->prepare('SELECT ' . REVIEW_COLUMNS . ' FROM products WHERE isbn = :isbn FOR UPDATE');
    $read = $pdo->prepare('SELECT ' . REVIEW_COLUMNS . ' FROM products WHERE isbn = :isbn');
    $delete = $pdo->prepare('DELETE FROM products WHERE isbn = :isbn');
    $pdo->beginTransaction();
    $saved = [];
    $deleted = [];
    foreach ($entries as $entry) {
        $original = $entry->original_isbn;
        $lock->execute(['isbn' => $original]);
        $previous = $lock->fetch(PDO::FETCH_ASSOC);
        $lock->closeCursor();
        if ($previous === false) {
            throw new ReviewRequestError("La ficha {$original} ya no existe en el importador. Sus cambios se conservan para revisar.", 409);
        }
        if ($previous['review_status'] !== $entry->expected_review_status) {
            throw new ReviewRequestError("La ficha {$original} está ahora en otro estado ({$previous['review_status']}). Sus cambios se conservan para revisar.", 409);
        }
        if ($previous['updated_at'] !== $entry->expected_updated_at
            || (isset($entry->expected_revision) && !hash_equals(review_row($previous)['_revision'], $entry->expected_revision))) {
            throw new ReviewRequestError("La ficha {$original} tiene una versión distinta en el importador. Sus cambios se conservan para comparar antes de sobrescribir.", 409);
        }
        if (($action === 'ready' && $previous['review_status'] !== 'pending_review')
            || ($action === 'pending' && $previous['review_status'] !== 'ready_to_upload')) {
            throw new ReviewRequestError("El estado de {$original} ha cambiado. Recarga las fichas.", 409);
        }
        if ($action === 'delete') {
            $delete->execute(['isbn' => $original]);
            if ($delete->rowCount() !== 1) {
                throw new ReviewRequestError("No se pudo borrar {$original}. Recarga las fichas.", 409);
            }
            $deleted[] = $original;
            continue;
        }
        $changes = (array) ($entry->changes ?? new stdClass());
        if ($action === 'pending') {
            $changes = [];
        }
        review_changes($changes, $original);
        $current = array_replace($previous, $changes);
        $target = $action === 'ready' || ($action === 'save' && $entry->ready_to_upload)
            ? 'ready_to_upload' : 'pending_review';
        $values = array_replace($changes, review_computed($current, $target, $original,
            ($entry->exceptions_confirmed ?? false) === true));
        $assignments = array_map(static function ($field) { return "{$field} = :{$field}"; }, array_keys($values));
        $update = $pdo->prepare('UPDATE products SET ' . implode(', ', $assignments) . ' WHERE isbn = :original_isbn');
        $update->execute($values + ['original_isbn' => $original]);
        $read->execute(['isbn' => $current['isbn']]);
        $row = $read->fetch(PDO::FETCH_ASSOC);
        $read->closeCursor();
        if ($row === false) {
            throw new RuntimeException('No se pudo releer la ficha guardada.');
        }
        $saved[] = ['original_isbn' => $original, 'product' => review_row($row)];
    }
    $pdo->commit();
    review_response(200, $action === 'delete' ? ['deleted' => $deleted] : ['saved' => $saved]);
} catch (Throwable $error) {
    yumekai_log('request.failed', ['type' => get_class($error), 'message' => $error->getMessage()]);
    if ($pdo instanceof PDO && $pdo->inTransaction()) {
        $pdo->rollBack();
    }
    if ($error instanceof ReviewRequestError) {
        review_response($error->getCode(), ['message' => $error->getMessage()]);
    }
    if ($error instanceof PDOException && (int) ($error->errorInfo[1] ?? 0) === 1062) {
        review_response(409, ['message' => "El ISBN o SKU de {$original} ya pertenece a otra ficha."]);
    }
    if ($error instanceof PDOException && (int) ($error->errorInfo[1] ?? 0) === 1406
        && preg_match('/isbn|sku/i', $error->errorInfo[2] ?? '')) {
        review_response(400, ['message' => 'El campo ISBN/SKU de la base de datos es demasiado corto. Ejecuta ampliar_codigos_productos.sql en la base del importador.']);
    }
    if ($error instanceof PDOException && (int) ($error->errorInfo[1] ?? 0) === 1406
        && strpos(strtolower($error->errorInfo[2] ?? ''), 'demographic') !== false) {
        review_response(400, ['message' => 'El campo demographic de la base de datos es demasiado corto. Ejecuta ampliar_demografia.sql antes de guardar esta categoría.']);
    }
    error_log('Yumekai review action: ' . $error->getCode());
    review_response(500, ['message' => 'No se pudo completar el lote. No se ha aplicado parcialmente.']);
}
