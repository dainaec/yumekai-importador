<?php
declare(strict_types=1);

function product_code_valid($value): bool
{
    return is_string($value) && trim($value) !== ''
        && preg_match('/\A[^\x00-\x1f\x7f]{1,128}\z/u', $value) === 1;
}

function standard_isbn13($isbn): bool
{
    if (!is_string($isbn) || preg_match('/\A97[89][0-9]{10}\z/', $isbn) !== 1) {
        return false;
    }
    $sum = 0;
    for ($i = 0; $i < 13; $i++) {
        $sum += (int) $isbn[$i] * ($i % 2 === 0 ? 1 : 3);
    }
    return $sum % 10 === 0;
}

function product_exception_warnings(array $product, bool $ready): array
{
    $issues = [];
    if (!standard_isbn13($product['isbn'] ?? null)) {
        $issues[] = 'Código no estándar ISBN-13';
    }
    $price = $product['retail_price'] ?? null;
    if ($price === null || !is_numeric($price) || (float) $price <= 0) {
        $issues[] = 'PVP pendiente o no positivo';
    }
    if ($ready) {
        foreach (['publisher', 'author', 'series', 'volume', 'language', 'book_format', 'pages', 'description', 'image_url'] as $field) {
            if (product_data_empty($product[$field] ?? null)) {
                $issues[] = "Falta {$field}";
            }
        }
        if (!in_array($product['work_type'] ?? null, ['Manga', 'Manhwa', 'Manhua'], true)) {
            $issues[] = 'Tipo de obra pendiente';
        }
        if (($product['work_type'] ?? null) === 'Manga' && product_data_empty($product['demographic'] ?? null)) {
            $issues[] = 'Demografía pendiente';
        }
    }
    return $issues;
}

function product_data_empty($value): bool
{
    return in_array(strtolower(trim((string) ($value ?? ''))),
        ['', '-', '- -', 'n/d', 'por completar', 'sin datos'], true);
}
