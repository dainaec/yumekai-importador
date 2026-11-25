<?php

declare(strict_types=1);
require_once __DIR__ . '/event_log.php';
require_once __DIR__ . '/exception_rules.php';

const REVIEW_COLUMNS = 'isbn, title, retail_price, sale_price, author, description, categories,
    image_url, publisher, series, volume, language, book_format, pages, work_type,
    demographic, yumekai_status, sku, is_featured, review_status, updated_at';
const REVIEW_STATUSES = ['pending_review', 'ready_to_upload'];
const REVIEW_TEXT_FIELDS = [
    'title' => null, 'author' => null, 'description' => null, 'image_url' => null,
    'publisher' => 255, 'series' => 255, 'volume' => 80, 'language' => 80,
    'book_format' => 100, 'work_type' => 20, 'demographic' => 100, 'yumekai_status' => 20,
];

class ReviewRequestError extends RuntimeException {}

function review_response(int $status, array $body): void
{
    yumekai_response_event($status, $body);
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    exit;
}

function review_isbn_valid(string $isbn): bool
{
    return standard_isbn13($isbn);
}

function review_stock_code($code): string
{
    return ['preorder' => 'onbackorder', 'in_stock' => 'instock'][$code ?? ''] ?? ($code ?? '');
}

function review_demographic($value): ?string
{
    $text = trim($value ?? '');
    if ($text === '') {
        return null;
    }
    $folded = strtolower(strtr($text, [
        'ō' => 'o', 'Ō' => 'o', 'ó' => 'o', 'Ó' => 'o', 'í' => 'i', 'Í' => 'i',
        'á' => 'a', 'Á' => 'a', 'é' => 'e', 'É' => 'e', 'ú' => 'u', 'Ú' => 'u',
    ]));
    $key = trim(preg_replace('/[^a-z0-9]+/', ' ', $folded));
    $aliases = [
        'shonen' => 'Shonen', 'shojo' => 'Shōjo', 'seinen' => 'Seinen',
        'josei' => 'Josei', 'kodomo' => 'Kodomo', 'teen s love' => 'Yaoi / BL',
        'teens love' => 'Yaoi / BL', 'teenslove' => 'Yaoi / BL', 'yaoi' => 'Yaoi / BL',
        'boys love' => 'Yaoi / BL', 'boy s love' => 'Yaoi / BL', 'boyslove' => 'Yaoi / BL',
        'bl' => 'Yaoi / BL', 'yaoi bl' => 'Yaoi / BL', 'spokon' => 'Shonen',
        'manga adulto' => 'Seinen', 'novelas manga' => 'Artbooks, guías y novelas',
        'novela manga' => 'Artbooks, guías y novelas', 'artbooks' => 'Artbooks, guías y novelas',
        'artbook' => 'Artbooks, guías y novelas',
        'artbooks guias y novelas' => 'Artbooks, guías y novelas',
    ];
    return $aliases[$key] ?? $text;
}

function review_row(array $row): array
{
    // Hash the stored values as read, before decoding JSON, to catch edits within the same second.
    $revision = hash('sha256', json_encode($row, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));
    $categories = json_decode($row['categories'] ?? '[]', true);
    $row['categories'] = is_array($categories) ? $categories : [];
    $row['_revision'] = $revision;
    return $row;
}

function review_validate_numbers(array $product, string $isbn, array $fields): void
{
    if (in_array('retail_price', $fields, true)) {
        $value = $product['retail_price'] ?? null;
        if ($value !== null && (!is_string($value) || preg_match('/\A[0-9]{1,8}\.[0-9]{2}\z/', $value) !== 1)) {
            throw new ReviewRequestError("El PVP de {$isbn} debe tener hasta dos decimales y no puede ser negativo.", 400);
        }
    }
    if (in_array('pages', $fields, true)) {
        $value = $product['pages'] ?? null;
        if ($value !== null && ((!is_int($value) && !is_string($value))
            || preg_match('/\A[0-9]{1,10}\z/', (string) $value) !== 1
            || (float) $value < 1 || (float) $value > 4294967295)) {
            throw new ReviewRequestError("Escribe un número entero positivo de páginas para {$isbn}.", 400);
        }
    }
    if (in_array('volume', $fields, true)) {
        $value = $product['volume'] ?? null;
        if ($value !== null && $value !== '' && (!is_string($value)
            || preg_match('/\A([0-9]{1,10})(?:-([0-9]{1,10}))?\z/', $value, $match) !== 1
            || (isset($match[2]) && (float) $match[1] > (float) $match[2]))) {
            throw new ReviewRequestError("El tomo de {$isbn} debe ser un número o un rango como 1-5.", 400);
        }
    }
}

function review_changes(array $changes, string $isbn): void
{
    foreach ($changes as $field => $value) {
        if (array_key_exists($field, REVIEW_TEXT_FIELDS)) {
            $limit = REVIEW_TEXT_FIELDS[$field];
            if ($value !== null && (!is_string($value)
                || ($limit === null && strlen($value) > 65535)
                || ($limit !== null && preg_match('/\A.{0,' . $limit . '}\z/us', $value) !== 1))) {
                throw new ReviewRequestError("El campo {$field} de {$isbn} no es válido o es demasiado largo.", 400);
            }
        } elseif (!in_array($field, ['isbn', 'retail_price', 'pages', 'is_featured'], true)) {
            throw new ReviewRequestError('La solicitud contiene un campo que no se puede editar.', 400);
        }
    }
    if (array_key_exists('isbn', $changes) && !product_code_valid($changes['isbn'])) {
        throw new ReviewRequestError("El código de {$isbn} es obligatorio y admite hasta 128 caracteres sin caracteres de control.", 400);
    }
    if (array_key_exists('is_featured', $changes) && !in_array($changes['is_featured'], [0, 1], true)) {
        throw new ReviewRequestError("Revisa el valor de Destacado en {$isbn}.", 400);
    }
    if (array_key_exists('yumekai_status', $changes) && $changes['yumekai_status'] !== null
        && !in_array(review_stock_code($changes['yumekai_status']), ['instock', 'outofstock', 'onbackorder', 'yk_on_demand'], true)) {
        throw new ReviewRequestError("Selecciona un estado Yumekai válido para {$isbn}.", 400);
    }
    review_validate_numbers($changes, $isbn, array_keys($changes));
}

function review_computed(array $product, string $target, string $original, bool $exceptionsConfirmed = false): array
{
    if ($target === 'ready_to_upload') {
        if (!product_code_valid($product['isbn'] ?? null)
            || trim((string) ($product['title'] ?? '')) === ''
            || !in_array(review_stock_code($product['yumekai_status'] ?? null),
                         ['instock', 'outofstock', 'onbackorder', 'yk_on_demand'], true)) {
            throw new ReviewRequestError("{$original}: código, título y estado Yumekai son obligatorios para pasar a listas.", 400);
        }
        $warnings = product_exception_warnings($product, true);
        if ($warnings !== [] && !$exceptionsConfirmed) {
            throw new ReviewRequestError("Autoriza expresamente las excepciones de {$original} antes de pasar a listas: " . implode('; ', $warnings), 400);
        }
    }
    $type = trim($product['work_type'] ?? '');
    $demographic = strcasecmp($type, 'Manga') === 0 ? (review_demographic($product['demographic'] ?? null) ?? '') : '';
    $categories = $type === '' ? [] : [$type];
    if ($demographic !== '') {
        $categories[] = "{$type} > {$demographic}";
    }
    return [
        'review_status' => $target,
        'sku' => $target === 'ready_to_upload' ? 'YMK-' . $product['isbn'] : null,
        'categories' => json_encode($categories, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR),
        'demographic' => $demographic === '' ? null : $demographic,
        'yumekai_status' => review_stock_code($product['yumekai_status'] ?? null) ?: null,
    ];
}
