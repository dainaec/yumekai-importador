<?php
declare(strict_types=1);
require_once dirname(__DIR__) . '/api-importador/store_mirror.php';

// Execute with php tests/test_store_sync.php (PDO SQLite enabled).
// These tests exercise the real reconciliation SQL without touching WordPress or MySQL.
function check(bool $condition, string $message): void
{
    if (!$condition) { throw new RuntimeException($message); }
}

function wc_format_decimal($value, $decimals): string
{
    return number_format((float) $value, $decimals, '.', '');
}

function snapshot(string $isbn, int $id, array $changes = []): array
{
    return array_replace(['isbn' => $isbn, 'woocommerce_id' => $id, 'title' => 'Título original',
        'author' => 'Autora', 'description' => "Texto\n\ncompleto", 'image_url' => 'https://example.test/cover.jpg',
        'publisher' => 'Panini', 'series' => 'Serie', 'volume' => '1', 'language' => 'Castellano',
        'book_format' => 'Rústica', 'work_type' => 'Manga', 'demographic' => 'Shonen',
        'yumekai_status' => 'instock', 'sku' => 'YMK-' . $isbn, 'is_featured' => 0,
        'retail_price' => '10.00', 'sale_price' => '9.50', 'pages' => '200', 'categories' => ['Manga', 'Shonen'],
        'publication_status' => 'publish'], $changes);
}

function database(): PDO
{
    $pdo = new PDO('sqlite::memory:');
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $columns = array_keys(store_importer_values(snapshot('A', 1)));
    $definitions = array_map(static function ($name) {
        return $name === 'title' ? 'title TEXT CHECK(title <> \'RECHAZAR\')' : "`{$name}` TEXT";
    }, $columns);
    $pdo->exec('CREATE TABLE products (isbn TEXT PRIMARY KEY, woocommerce_id INTEGER, '
        . "review_status TEXT DEFAULT 'pending_review', updated_at TEXT DEFAULT '2026-01-01', "
        . implode(', ', $definitions) . ')');
    return $pdo;
}

function insert(PDO $pdo, string $isbn, ?int $id, array $overrides = []): void
{
    $values = store_importer_values(snapshot($isbn, $id ?? 999)) + ['isbn' => $isbn, 'woocommerce_id' => $id];
    $values = array_replace($values, $overrides);
    $keys = array_keys($values);
    $query = $pdo->prepare('INSERT INTO products (`' . implode('`, `', $keys) . '`) VALUES (:' . implode(', :', $keys) . ')');
    $query->execute($values);
}

function row(PDO $pdo, string $isbn): array
{
    $query = $pdo->prepare('SELECT * FROM products WHERE isbn = ?');
    $query->execute([$isbn]);
    return $query->fetch(PDO::FETCH_ASSOC);
}

function reconcile(PDO $pdo, array $snapshots): array
{
    $pdo->beginTransaction();
    try {
        $result = store_reconcile($pdo, $pdo->query('SELECT * FROM products')->fetchAll(PDO::FETCH_ASSOC), $snapshots);
        $pdo->commit();
        return $result;
    } catch (Throwable $error) {
        $pdo->rollBack();
        throw $error;
    }
}

$tests = [];
$tests['edits update copies; links and workflow state remain correct'] = static function (): void {
    $pdo = database();
    insert($pdo, 'A', 1, ['review_status' => 'ready_to_upload']);
    insert($pdo, 'B', null);
    insert($pdo, 'C', null);
    $result = reconcile($pdo, [1 => snapshot('A', 1, ['title' => 'Título corregido', 'retail_price' => '12']), 2 => snapshot('B', 2)]);
    check(row($pdo, 'A')['title'] === 'Título corregido', 'No copió el título actual');
    check(row($pdo, 'A')['retail_price'] === '12.00', 'No normalizó el precio');
    check(row($pdo, 'A')['review_status'] === 'ready_to_upload', 'Cambió el estado de revisión');
    check((int) row($pdo, 'B')['woocommerce_id'] === 2, 'No creó el vínculo');
    check(row($pdo, 'C')['woocommerce_id'] === null, 'Vinculó una ficha inexistente');
    check($result['linked'] === 1 && $result['updated'] === 2, 'Recuento incorrecto');
};
$tests['deleted, trashed and draft products keep history and stay out of pending'] = static function (): void {
    $pdo = database();
    insert($pdo, 'A', 1); insert($pdo, 'B', 2); insert($pdo, 'C', 3);
    $before = row($pdo, 'A');
    $result = reconcile($pdo, [1 => null, 2 => snapshot('B', 2, ['publication_status' => 'trash']),
        3 => snapshot('C', 3, ['publication_status' => 'draft'])]);
    check($result['missing'] === 1 && $result['unpublished'] === 2, 'No distinguió eliminados y sin publicar');
    check(row($pdo, 'A') === $before, 'Perdió la copia de la ficha eliminada');
    check((int) $pdo->query('SELECT COUNT(*) FROM products WHERE woocommerce_id IS NULL')->fetchColumn() === 0,
        'Una ficha eliminada volvió a pendientes');
};
$tests['changed external ISBN is a conflict, never a silent key rewrite'] = static function (): void {
    $pdo = database(); insert($pdo, 'A', 1);
    $before = row($pdo, 'A');
    $result = reconcile($pdo, [1 => snapshot('OTRO-CODIGO', 1)]);
    check($result['conflicts'] === 1 && row($pdo, 'A') === $before, 'No protegió el ISBN original');
};
$tests['duplicate store ISBN aborts before writing'] = static function (): void {
    $pdo = database(); insert($pdo, 'A', 1);
    try { reconcile($pdo, [1 => snapshot('A', 1), 2 => snapshot('A', 2)]); }
    catch (ReviewRequestError $error) { check($error->getCode() === 409, 'Código de conflicto incorrecto'); return; }
    throw new RuntimeException('Aceptó un ISBN duplicado');
};
$tests['duplicate importer links are preserved and reported'] = static function (): void {
    $pdo = database(); insert($pdo, 'A', 1); insert($pdo, 'B', 1);
    $result = reconcile($pdo, [1 => snapshot('A', 1, ['title' => 'Nuevo título'])]);
    check($result['conflicts'] >= 1 && $result['updated'] === 0, 'Actualizó un vínculo ambiguo');
    check(row($pdo, 'A')['title'] === 'Título original', 'Cambió una ficha ambigua');
};
$tests['unchanged copies keep timestamps and revisions'] = static function (): void {
    $pdo = database(); insert($pdo, 'A', 1);
    $before = row($pdo, 'A');
    $result = reconcile($pdo, [1 => snapshot('A', 1)]);
    check($result['unchanged'] === 1 && $result['updated'] === 0, 'Marcó una copia sin cambios');
    check(row($pdo, 'A') === $before, 'Alteró la copia sin cambios');
};
$tests['database failure rolls back earlier updates'] = static function (): void {
    $pdo = database(); insert($pdo, 'A', 1); insert($pdo, 'B', 2);
    $before = row($pdo, 'A');
    try {
        reconcile($pdo, [1 => snapshot('A', 1, ['title' => 'Cambio válido']), 2 => snapshot('B', 2, ['title' => 'RECHAZAR'])]);
    } catch (PDOException $error) {
        check(row($pdo, 'A') === $before, 'Guardó parcialmente una sincronización fallida');
        return;
    }
    throw new RuntimeException('No se provocó el error de base de datos');
};
$tests['uninspected link cannot be treated as deletion'] = static function (): void {
    $pdo = database(); insert($pdo, 'A', 1);
    try { reconcile($pdo, []); }
    catch (RuntimeException $error) { check(row($pdo, 'A')['woocommerce_id'] == 1, 'Quitó el vínculo'); return; }
    throw new RuntimeException('Aceptó una consulta incompleta');
};
$tests['reused ISBN never attaches history to another product'] = static function (): void {
    $pdo = database(); insert($pdo, 'A', 1);
    $result = reconcile($pdo, [1 => null, 2 => snapshot('A', 2)]);
    check($result['conflicting_store_isbns'] === 1 && row($pdo, 'A')['woocommerce_id'] == 1, 'Reasignó el historial a otro producto');
};
foreach ($tests as $name => $test) {
    $test();
    echo 'OK: ' . $name . PHP_EOL;
}
echo count($tests) . ' PHP integration tests passed' . PHP_EOL;
