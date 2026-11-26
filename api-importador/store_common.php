<?php
declare(strict_types=1);
// These API requests must read WordPress/WooCommerce without persistent cache snapshots.
// Defined before wp-load.php so W3 Total Cache drop-ins see them too.
foreach (['DONOTCACHEPAGE', 'DONOTCACHEOBJECT', 'DONOTCACHEDB'] as $cacheConstant) {
    if (!defined($cacheConstant)) { define($cacheConstant, true); }
}
require_once __DIR__ . '/review_common.php';

const STORE_META_FIELDS = [
    'author' => '_yk_author', 'publisher' => '_yk_brand', 'series' => '_yk_franchise',
    'volume' => '_yk_volume', 'language' => '_yk_language', 'book_format' => '_yk_format',
    'pages' => '_yk_pages', 'work_type' => '_yk_item_kind',
];
const STORE_WRITE_FIELDS = ['description', 'yumekai_status', 'retail_price', 'sale_price',
    'author', 'publisher', 'series', 'volume', 'language', 'book_format', 'pages', 'work_type'];

function store_prime_products(array $ids): void
{
    if ($ids === []) { return; }
    // Prime post, metadata, terms and cover metadata in batches before hydration.
    $posts = get_posts(['post_type' => 'product', 'post_status' => 'any', 'post__in' => $ids,
        'posts_per_page' => count($ids), 'orderby' => 'ID', 'order' => 'ASC',
        'no_found_rows' => true, 'update_post_meta_cache' => true, 'update_post_term_cache' => true]);
    update_post_caches($posts, 'product', true, true);
    $images = [];
    foreach ($ids as $id) {
        $image = (int) get_post_meta($id, '_thumbnail_id', true);
        if ($image > 0) { $images[] = $image; }
    }
    if ($images !== []) {
        $images = array_values(array_unique($images));
        $attachments = get_posts(['post_type' => 'attachment', 'post_status' => ['inherit', 'private', 'publish'],
            'post__in' => $images, 'posts_per_page' => count($images), 'no_found_rows' => true,
            'update_post_meta_cache' => true, 'update_post_term_cache' => false]);
        update_post_caches($attachments, 'attachment', false, true);
        update_meta_cache('post', $images);
    }
}

function store_work_type($value): ?string
{
    $key = strtolower(trim((string) $value));
    return ['manga' => 'Manga', 'manhwa' => 'Manhwa', 'manwha' => 'Manhwa',
        'manhua' => 'Manhua'][$key] ?? null;
}

/** Product categories are the current shop classification; _yk_item_kind is a fallback. */
function store_category_info(array $ids, $fallback): array
{
    $names = $typedTerms = $ancestors = [];
    $demographics = [];
    foreach ($ids as $id) {
        $term = get_term($id, 'product_cat');
        if (!$term || is_wp_error($term)) {
            throw new ReviewRequestError('No se pudieron leer las categorías actuales de una ficha. Vuelve a cargar la tienda.', 503);
        }
        $names[] = $term->name;
        $path = array_merge([(int) $id], array_map('intval', get_ancestors($id, 'product_cat', 'taxonomy')));
        foreach ($path as $pathId) {
            $parent = $pathId === (int) $id ? $term : get_term($pathId, 'product_cat');
            if (!$parent || is_wp_error($parent)) {
                throw new ReviewRequestError('No se pudo leer la jerarquía de categorías de una ficha.', 503);
            }
            $type = store_work_type($parent->slug ?? '') ?? store_work_type($parent->name);
            if ($type !== null) {
                $typedTerms[$pathId] = $type;
                $ancestors[$pathId] = array_map('intval', get_ancestors($pathId, 'product_cat', 'taxonomy'));
            }
            $demographic = review_demographic($parent->name);
            if (in_array($demographic, ['Shonen', 'Shōjo', 'Seinen', 'Josei', 'Kodomo', 'Yaoi / BL', 'Yuri', 'Artbooks, guías y novelas'], true)) {
                $demographics[$demographic] = true;
            }
        }
    }
    // If Manhwa is nested below Manga, use the more specific classification.
    foreach ($ancestors as $child => $parents) {
        foreach ($parents as $parent) {
            if (isset($typedTerms[$child], $typedTerms[$parent]) && $typedTerms[$child] !== $typedTerms[$parent]) {
                unset($typedTerms[$parent]);
            }
        }
    }
    $types = array_values(array_unique(array_values($typedTerms)));
    sort($types, SORT_STRING);
    $type = count($types) === 1 ? $types[0] : (count($types) === 0 ? store_work_type($fallback) : null);
    return ['categories' => $names, 'work_type' => $type,
        'demographic' => $type === 'Manga' && count($demographics) === 1 ? array_key_first($demographics) : null,
        'category_issue' => count($types) > 1 ? 'Las categorías mezclan tipos de obra: ' . implode(', ', $types)
            . '. Revisa las categorías en WooCommerce.' : null];
}

/** Use a real shop identifier; never match editions by title. */
function store_identifier(int $id, string $sku): array
{
    $isbn = trim((string) get_post_meta($id, '_yk_isbn', true));
    if ($isbn !== '') { return ['isbn' => $isbn, 'identifier_source' => '_yk_isbn']; }
    $gtin = trim((string) get_post_meta($id, '_global_unique_id', true));
    if (preg_match('/\A[0-9]{13}\z/', $gtin) === 1) { return ['isbn' => $gtin, 'identifier_source' => '_global_unique_id']; }
    if (preg_match('/\AYMK-(.+)\z/iu', $sku, $match) === 1 && product_code_valid($match[1])) {
        return ['isbn' => $match[1], 'identifier_source' => '_sku'];
    }
    return ['isbn' => '', 'identifier_source' => null];
}

/** Preserve the canonical link of a previously published draft without writing a post. */
function store_product_url($product): string
{
    if ($product->get_status('edit') !== 'publish' && function_exists('get_post') && function_exists('get_permalink')) {
        $post = get_post($product->get_id());
        if ($post && (string) ($post->post_name ?? '') !== '') {
            $sample = clone $post;
            $sample->post_status = 'publish';
            $url = get_permalink($sample);
            if (is_string($url) && $url !== '') { return $url; }
        }
    }
    return (string) $product->get_permalink();
}

function store_snapshot($product): array
{
    $row = [
        'woocommerce_id' => $product->get_id(), 'isbn' => (string) get_post_meta($product->get_id(), '_yk_isbn', true),
        'product_url' => store_product_url($product),
        'title' => $product->get_name('edit'), 'description' => $product->get_description('edit'),
        'short_description' => $product->get_short_description('edit'),
        'retail_price' => $product->get_regular_price('edit') === '' ? null : $product->get_regular_price('edit'),
        'sale_price' => $product->get_sale_price('edit') === '' ? null : $product->get_sale_price('edit'),
        'yumekai_status' => $product->get_stock_status('edit'), 'sku' => $product->get_sku('edit'),
        'manage_stock' => $product->get_manage_stock('edit'), 'stock_quantity' => $product->get_stock_quantity('edit'),
        'backorders' => $product->get_backorders('edit'), 'product_type' => $product->get_type(),
        'publication_status' => $product->get_status('edit'), 'is_featured' => (int) $product->get_featured('edit'),
        'tax_class' => $product->get_tax_class('edit'), 'tax_status' => $product->get_tax_status('edit'),
        'active_price' => $product->get_price('edit'),
        'image_id' => (int) $product->get_image_id('edit'),
        'review_status' => 'in_store', 'updated_at' => get_post_field('post_modified_gmt', $product->get_id()),
    ];
    $row = array_replace($row, store_identifier($product->get_id(), $row['sku']));
    foreach (STORE_META_FIELDS as $field => $meta) {
        $row[$field] = (string) get_post_meta($product->get_id(), $meta, true);
    }
    $ids = array_map('intval', $product->get_category_ids('edit'));
    sort($ids, SORT_NUMERIC);
    $row['category_ids'] = $ids;
    $row = array_replace($row, store_category_info($ids, $row['work_type']));
    $image = wp_get_attachment_url($product->get_image_id('edit'));
    $row['image_url'] = $image ?: null;
    // Keep plugin metadata and WooCommerce attributes available for diagnosis and conflict detection.
    $row['meta_data'] = get_post_meta($product->get_id());
    $row['attributes'] = [];
    foreach ($product->get_attributes('edit') as $attribute) {
        $row['attributes'][] = $attribute->get_data();
    }
    $row['_store_revision'] = hash('sha256', json_encode($row, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));
    return $row;
}

function store_validate_changes(array $changes): void
{
    if ($changes === [] || array_diff(array_keys($changes), STORE_WRITE_FIELDS)) {
        throw new ReviewRequestError('La solicitud contiene campos no admitidos para actualizar la tienda.', 400);
    }
    $reviewChanges = $changes;
    unset($reviewChanges['sale_price']);
    review_changes($reviewChanges, 'tienda');
    if (array_key_exists('sale_price', $changes)) {
        review_validate_numbers(['retail_price' => $changes['sale_price']], 'tienda', ['retail_price']);
    }
    if (isset($changes['work_type']) && !in_array($changes['work_type'], ['Manga', 'Manhwa', 'Manhua'], true)) {
        throw new ReviewRequestError('El tipo de obra no es válido.', 400);
    }
}

function store_apply_changes($product, array $changes): void
{
    store_validate_changes($changes);
    if (isset($changes['yumekai_status'])) {
        $status = review_stock_code($changes['yumekai_status']);
        if (!array_key_exists($status, wc_get_product_stock_status_options())) {
            throw new ReviewRequestError('La tienda no reconoce ese estado Yumekai. Revisa los estados disponibles.', 400);
        }
        if ($product->get_manage_stock('edit') && $product->get_stock_status('edit') !== $status) {
            throw new ReviewRequestError('Esta ficha gestiona unidades en WooCommerce. Revisa esa gestión antes de cambiar su disponibilidad desde el distribuidor.', 409);
        }
        $product->set_stock_status($status);
    } elseif (array_key_exists('yumekai_status', $changes)) {
        throw new ReviewRequestError('Selecciona un estado Yumekai válido.', 400);
    }
    foreach ($changes as $field => $value) {
        if (isset(STORE_META_FIELDS[$field])) {
            if ($field === 'work_type') { $value = strtolower($value ?? ''); }
            $product->update_meta_data(STORE_META_FIELDS[$field], sanitize_text_field((string) ($value ?? '')));
        } elseif ($field === 'description') {
            $product->set_description(wp_kses_post((string) ($value ?? '')));
        } elseif ($field === 'retail_price') {
            $product->set_regular_price($value ?? '');
        } elseif ($field === 'sale_price') {
            $product->set_sale_price($value ?? '');
        }
    }
    $product->save();
}
