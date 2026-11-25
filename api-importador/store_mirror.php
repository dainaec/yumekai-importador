<?php
declare(strict_types=1);
require_once __DIR__ . '/store_common.php';

/** Only shared catalogue fields. Import workflow state and the ISBN key stay intact. */
function store_importer_values(array $snapshot): array
{
    $values = [];
    foreach (['title', 'author', 'description', 'image_url', 'publisher', 'series', 'volume',
              'language', 'book_format', 'work_type', 'demographic', 'yumekai_status', 'sku',
              'is_featured'] as $field) {
        $values[$field] = $snapshot[$field] ?? null;
    }
    foreach (['retail_price', 'sale_price'] as $field) {
        $value = $snapshot[$field] ?? null;
        $values[$field] = $value === null || $value === '' ? null : wc_format_decimal($value, 2);
    }
    $pages = $snapshot['pages'] ?? null;
    $values['pages'] = $pages === '' ? null : $pages;
    $values['categories'] = json_encode($snapshot['categories'] ?? [], JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    return $values;
}

function store_copy_differs(array $current, array $values): bool
{
    foreach ($values as $field => $value) {
        $old = $current[$field] ?? null;
        if ($field === 'categories') {
            if (json_decode($old ?? '[]', true) !== json_decode($value, true)) { return true; }
        } elseif ($old === null || $value === null) {
            if ($old !== $value) { return true; }
        } elseif ((string) $old !== (string) $value) {
            return true;
        }
    }
    return false;
}

/** The caller supplies a transaction; do not detach records for absent products. */
function store_reconcile(PDO $pdo, array $current, array $snapshots): array
{
    $byIsbn = $byId = [];
    foreach ($current as $row) {
        $byIsbn[(string) $row['isbn']] = $row;
        if ($row['woocommerce_id'] !== null) { $byId[(int) $row['woocommerce_id']][] = (string) $row['isbn']; }
    }
    $summary = ['sync_version' => 2, 'store_isbns' => 0, 'linked' => 0, 'already_linked' => 0,
        'not_in_importer' => 0, 'invalid_store_isbns' => 0, 'conflicting_store_isbns' => 0,
        'updated' => 0, 'unchanged' => 0, 'missing' => 0, 'unpublished' => 0,
        'conflicts' => 0, 'products' => [], 'issues' => []];
    $catalog = [];
    foreach ($snapshots as $id => $snapshot) {
        if ($snapshot === null || $snapshot['publication_status'] !== 'publish') { continue; }
        $isbn = trim((string) $snapshot['isbn']);
        $compact = preg_replace('/[\s-]+/u', '', $isbn);
        if (is_string($compact) && preg_match('/\A[0-9]{13}\z/', $compact)) { $isbn = $compact; }
        if (!product_code_valid($isbn)) { $summary['invalid_store_isbns']++; continue; }
        if (isset($catalog[$isbn]) && $catalog[$isbn] !== (int) $id) {
            throw new ReviewRequestError('Hay ISBN duplicados en WooCommerce. No se ha sincronizado ningún dato.', 409);
        }
        $catalog[$isbn] = (int) $id;
    }
    $summary['store_isbns'] = count($catalog);
    $values = store_importer_values([
        'categories' => [], 'pages' => null,
    ]);
    $assignments = array_map(static function ($field) { return "`{$field}` = :{$field}"; }, array_keys($values));
    $update = $pdo->prepare('UPDATE products SET ' . implode(', ', $assignments)
        . ', woocommerce_id = :woocommerce_id, updated_at = CURRENT_TIMESTAMP WHERE isbn = :original_isbn');
    $processed = [];
    $copy = static function (string $isbn, int $id, array $row, array $snapshot, bool $link) use (
        $update, &$summary, &$processed
    ): void {
        $values = store_importer_values($snapshot);
        if ($link || store_copy_differs($row, $values)) {
            $update->execute($values + ['woocommerce_id' => $id, 'original_isbn' => $isbn]);
            $summary['updated']++;
        } else {
            $summary['unchanged']++;
        }
        $processed[$isbn] = true;
    };
    $issue = static function (string $isbn, int $id, string $status, string $message) use (&$summary): void {
        $summary['issues'][] = ['isbn' => $isbn, 'woocommerce_id' => $id, 'status' => $status, 'message' => $message];
    };
    foreach ($catalog as $isbn => $id) {
        $isbn = (string) $isbn;
        $row = $byIsbn[$isbn] ?? null;
        if ($row === null) {
            if (isset($byId[$id])) { $summary['already_linked']++; }
            else { $summary['not_in_importer']++; }
            continue;
        }
        if (($row['woocommerce_id'] !== null && (int) $row['woocommerce_id'] !== $id)
            || (isset($byId[$id]) && $byId[$id] !== [$isbn])) {
            $summary['conflicting_store_isbns']++;
            $summary['conflicts']++;
            $issue($isbn, $id, 'conflict', 'El ISBN y el vínculo apuntan a fichas diferentes. Copia conservada.');
            $processed[$isbn] = true;
            continue;
        }
        $link = $row['woocommerce_id'] === null;
        if ($link) {
            $summary['linked']++;
            $summary['products'][] = ['isbn' => $isbn, 'woocommerce_id' => $id];
        } else { $summary['already_linked']++; }
        $copy($isbn, $id, $row, $snapshots[$id], $link);
    }
    // Inspect every existing link, including trash, drafts and permanently deleted IDs.
    foreach ($byId as $id => $isbns) {
        foreach ($isbns as $isbn) {
            if (isset($processed[$isbn])) { continue; }
            if (!array_key_exists($id, $snapshots)) {
                throw new RuntimeException('No se ha comprobado un vínculo. Sincronización cancelada.');
            }
            $snapshot = $snapshots[$id];
            if ($snapshot === null) {
                $summary['missing']++;
                $issue($isbn, $id, 'deleted', 'Eliminada en WooCommerce. Última copia y vínculo conservados.');
            } elseif ($snapshot['publication_status'] !== 'publish') {
                $summary['unpublished']++;
                $issue($isbn, $id, $snapshot['publication_status'], 'Ya no está publicada. Última copia y vínculo conservados.');
            } else {
                $summary['conflicts']++;
                $issue($isbn, $id, 'conflict', 'Cambió el ISBN en WooCommerce o hay varios vínculos al mismo ID. Revisa la identidad antes de sincronizar.');
            }
        }
    }
    return $summary;
}
