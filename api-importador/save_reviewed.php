<?php

declare(strict_types=1);

ini_set('display_errors', '0');

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

const TEXT_FIELDS = [
    'title' => null,
    'author' => null,
    'description' => null,
    'image_url' => null,
    'publisher' => 255,
    'series' => 255,
    'volume' => 80,
    'language' => 80,
    'book_format' => 100,
    'work_type' => 20,
    'demographic' => 20,
    'yumekai_status' => 20,
];

class ReviewError extends RuntimeException
{
}

function respond(int $status, array $body): void
{
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    exit;
}

function is_isbn13(string $isbn): bool
{
    if (preg_match('/\A97[89][0-9]{10}\z/', $isbn) !== 1) {
        return false;
    }

    $sum = 0;
    for ($index = 0; $index < 13; $index++) {
        $sum += (int) $isbn[$index] * ($index % 2 === 0 ? 1 : 3);
    }
    return $sum % 10 === 0;
}

function read_updates(): array
{
    $payload = json_decode(file_get_contents('php://input'));
    if (!is_object($payload) || !is_array($payload->products ?? null) || $payload->products === []) {
        throw new ReviewError('Selecciona las fichas revisadas que quieres guardar.', 400);
    }

    $updates = [];
    foreach ($payload->products as $item) {
        if (!is_object($item) || !is_string($item->original_isbn ?? null) || !is_object($item->changes ?? null)) {
            throw new ReviewError('La solicitud contiene una ficha incompleta.', 400);
        }
        $original = $item->original_isbn;
        if (preg_match('/\A.{1,13}\z/us', $original) !== 1 || isset($updates[$original])) {
            throw new ReviewError('La solicitud contiene un ISBN de origen inválido o repetido.', 400);
        }
        if (isset($item->expected_updated_at) && !is_string($item->expected_updated_at)) {
            throw new ReviewError('La versión de la ficha no es válida. Recarga y vuelve a intentarlo.', 400);
        }
        $updates[$original] = $item;
    }

    ksort($updates, SORT_STRING);
    return $updates;
}

function validate_changes(array $changes, string $original): void
{
    foreach ($changes as $field => $value) {
        if (array_key_exists($field, TEXT_FIELDS)) {
            $limit = TEXT_FIELDS[$field];
            if ($value !== null && (
                !is_string($value)
                || ($limit === null && strlen($value) > 65535)
                || ($limit !== null && preg_match('/\A.{0,' . $limit . '}\z/us', $value) !== 1)
            )) {
                throw new ReviewError("El campo {$field} de {$original} no es válido o es demasiado largo.", 400);
            }
        } elseif (!in_array($field, ['isbn', 'retail_price', 'pages', 'is_featured'], true)) {
            throw new ReviewError('La solicitud contiene un campo que se calcula automáticamente o no se puede editar.', 400);
        }
    }

    if (array_key_exists('is_featured', $changes) && !in_array($changes['is_featured'], [0, 1], true)) {
        throw new ReviewError("Revisa el valor de Destacado en {$original}.", 400);
    }
    if (array_key_exists('isbn', $changes) && !is_string($changes['isbn'])) {
        throw new ReviewError("Introduce un ISBN-13 válido para {$original}.", 400);
    }
}

function review_values(array $product, string $original): array
{
    if (!is_string($product['isbn']) || !is_isbn13($product['isbn'])) {
        throw new ReviewError("Comprueba el dígito de control y los 13 dígitos del ISBN de {$original}.", 400);
    }
    if (!is_string($product['title']) || trim($product['title']) === '') {
        throw new ReviewError("Completa el título de {$original}.", 400);
    }

    $price = $product['retail_price'];
    if ($price !== null && (!is_string($price) || preg_match('/\A[0-9]{1,8}\.[0-9]{2}\z/', $price) !== 1)) {
        throw new ReviewError("El PVP de {$original} debe ser un importe positivo o cero con dos decimales.", 400);
    }
    $pages = $product['pages'];
    if ($pages !== null && (
        (!is_int($pages) && !is_string($pages))
        || preg_match('/\A[0-9]{1,10}\z/', (string) $pages) !== 1
        || (float) $pages < 1 || (float) $pages > 4294967295
    )) {
        throw new ReviewError("Escribe un número entero positivo de páginas para {$original}.", 400);
    }
    $volume = $product['volume'];
    if ($volume !== null && $volume !== '' && (
        preg_match('/\A([0-9]{1,10})(?:-([0-9]{1,10}))?\z/', $volume, $match) !== 1
        || (isset($match[2]) && (float) $match[1] > (float) $match[2])
    )) {
        throw new ReviewError("El tomo de {$original} debe ser un número o un rango como 1-5.", 400);
    }

    $type = trim($product['work_type'] ?? '');
    $isManga = strcasecmp($type, 'Manga') === 0;
    $demographic = $isManga ? trim($product['demographic'] ?? '') : '';
    $categories = $type === '' ? [] : [$type];
    if ($demographic !== '') {
        $categories[] = "{$type} > {$demographic}";
    }

    return [
        'sku' => 'YMK-' . $product['isbn'],
        'categories' => json_encode($categories, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR),
        'demographic' => $demographic === '' ? null : $demographic,
        'review_status' => 'ready_to_upload',
    ];
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Allow: POST');
    respond(405, ['message' => 'Usa POST para guardar las fichas revisadas.']);
}

$contentType = explode(';', $_SERVER['CONTENT_TYPE'] ?? '', 2)[0];
if (strtolower(trim($contentType)) !== 'application/json') {
    respond(415, ['message' => 'Envía las fichas en formato JSON.']);
}

$pdo = null;
$originalIsbn = '';
try {
    $updates = read_updates();
    $pdo = require dirname(__DIR__, 2) . '/importer-private/database.php';
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $columns = 'isbn, title, retail_price, sale_price, author, description, categories,
                image_url, publisher, series, volume, language, book_format, pages,
                work_type, demographic, yumekai_status, sku, is_featured, review_status,
                updated_at';
    $lock = $pdo->prepare("SELECT {$columns} FROM products WHERE isbn = :isbn FOR UPDATE");
    $read = $pdo->prepare("SELECT {$columns} FROM products WHERE isbn = :isbn");
    $pdo->beginTransaction();

    $saved = [];
    foreach ($updates as $entry) {
        $originalIsbn = $entry->original_isbn;
        $lock->execute(['isbn' => $originalIsbn]);
        $previous = $lock->fetch(PDO::FETCH_ASSOC);
        $lock->closeCursor();
        if ($previous === false || $previous['review_status'] !== 'pending_review') {
            throw new ReviewError("El ISBN {$originalIsbn} ha cambiado o ya se revisó. Recarga las fichas.", 409);
        }
        if (isset($entry->expected_updated_at) && $previous['updated_at'] !== $entry->expected_updated_at) {
            throw new ReviewError("La ficha {$originalIsbn} se modificó desde la última carga. Recarga las fichas.", 409);
        }

        $changes = (array) $entry->changes;
        validate_changes($changes, $originalIsbn);
        $current = array_replace($previous, $changes);
        $values = array_replace($changes, review_values($current, $originalIsbn));
        $assignments = [];
        foreach (array_keys($values) as $field) {
            $assignments[] = "{$field} = :{$field}";
        }

        $sql = 'UPDATE products SET ' . implode(', ', $assignments)
             . " WHERE isbn = :original_isbn AND review_status = 'pending_review'";
        $update = $pdo->prepare($sql);
        $update->execute($values + ['original_isbn' => $originalIsbn]);
        if ($update->rowCount() !== 1) {
            throw new ReviewError("No se pudo actualizar la ficha {$originalIsbn}. Recarga las fichas.", 409);
        }

        $read->execute(['isbn' => $current['isbn']]);
        $row = $read->fetch(PDO::FETCH_ASSOC);
        $read->closeCursor();
        if ($row === false) {
            throw new RuntimeException('No se pudo releer la ficha.');
        }
        $row['categories'] = json_decode($row['categories'], true, 512, JSON_THROW_ON_ERROR);
        $saved[] = ['original_isbn' => $originalIsbn, 'product' => $row];
    }

    $pdo->commit();
    respond(200, ['saved' => $saved]);
} catch (Throwable $error) {
    if ($pdo instanceof PDO && $pdo->inTransaction()) {
        $pdo->rollBack();
    }
    if ($error instanceof ReviewError) {
        respond($error->getCode(), ['message' => $error->getMessage()]);
    }
    if ($error instanceof PDOException && (int) ($error->errorInfo[1] ?? 0) === 1062) {
        respond(409, ['message' => "El ISBN o SKU que intentas asignar a {$originalIsbn} ya pertenece a otra ficha."]);
    }

    error_log('Yumekai save reviewed: ' . $error->getCode());
    respond(500, ['message' => 'Hostalia no pudo guardar el lote.']);
}
