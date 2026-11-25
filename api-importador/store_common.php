<?php
declare(strict_types=1);
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
    if ($images !== []) { update_meta_cache('post', array_values(array_unique($images))); }
}

function store_snapshot($product): array
{
    $row = [
        'woocommerce_id' => $product->get_id(), 'isbn' => (string) $product->get_meta('_yk_isbn', true, 'edit'),
        'title' => $product->get_name('edit'), 'description' => $product->get_description('edit'),
        'short_description' => $product->get_short_description('edit'),
        'retail_price' => $product->get_regular_price('edit') === '' ? null : $product->get_regular_price('edit'),
        'sale_price' => $product->get_sale_price('edit') === '' ? null : $product->get_sale_price('edit'),
        'yumekai_status' => $product->get_stock_status('edit'), 'sku' => $product->get_sku('edit'),
        'manage_stock' => $product->get_manage_stock('edit'), 'stock_quantity' => $product->get_stock_quantity('edit'),
        'backorders' => $product->get_backorders('edit'), 'product_type' => $product->get_type(),
        'publication_status' => $product->get_status('edit'), 'is_featured' => (int) $product->get_featured('edit'),
        'review_status' => 'in_store', 'updated_at' => get_post_field('post_modified_gmt', $product->get_id()),
    ];
    foreach (STORE_META_FIELDS as $field => $meta) {
        $row[$field] = (string) $product->get_meta($meta, true, 'edit');
    }
    $row['work_type'] = ['manga' => 'Manga', 'manhwa' => 'Manhwa', 'manwha' => 'Manhwa',
        'manhua' => 'Manhua'][$row['work_type']] ?? $row['work_type'];
    $ids = array_map('intval', $product->get_category_ids('edit'));
    sort($ids, SORT_NUMERIC);
    $row['category_ids'] = $ids;
    $row['categories'] = [];
    $row['demographic'] = null;
    foreach ($ids as $id) {
        $term = get_term($id, 'product_cat');
        if ($term && !is_wp_error($term)) {
            $row['categories'][] = $term->name;
            $demographic = review_demographic($term->name);
            if (in_array($demographic, ['Shonen', 'Shōjo', 'Seinen', 'Josei', 'Kodomo', 'Yaoi / BL', 'Yuri', 'Artbooks, guías y novelas'], true)) {
                $row['demographic'] = $demographic;
            }
        }
    }
    $image = wp_get_attachment_url($product->get_image_id('edit'));
    $row['image_url'] = $image ?: null;
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
