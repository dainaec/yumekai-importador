<?php
declare(strict_types=1);
require_once __DIR__ . '/store_common.php';
require_once __DIR__ . '/store_publication.php';

const STORE_CATALOG_FIELDS = ['title', 'isbn', 'sku', 'description', 'short_description',
    'retail_price', 'sale_price', 'yumekai_status', 'is_featured', 'tax_class', 'category_ids',
    'author', 'publisher', 'series', 'volume', 'language', 'book_format', 'pages'];
const STORE_PUBLICATION_STATUSES = ['publish', 'draft', 'pending', 'private'];

function store_catalog_options(): array
{
    $terms = get_terms(['taxonomy' => 'product_cat', 'hide_empty' => false]);
    if (is_wp_error($terms)) { throw new ReviewRequestError('No se pueden leer las categorías de la tienda.', 503); }
    $categories = [];
    foreach ($terms as $term) {
        $categories[] = ['id' => (int) $term->term_id, 'name' => $term->name,
            'slug' => $term->slug, 'parent' => (int) $term->parent];
    }
    $taxes = [['slug' => '', 'name' => 'Estándar']];
    foreach (WC_Tax::get_tax_classes() as $name) { $taxes[] = ['slug' => sanitize_title($name), 'name' => $name]; }
    return ['categories' => $categories, 'stock_statuses' => wc_get_product_stock_status_options(), 'tax_classes' => $taxes];
}

/** Validate everything before calling any WooCommerce setter. */
function store_catalog_validate(array $changes, bool $create = false): void
{
    if ($changes === [] || array_diff(array_keys($changes), STORE_CATALOG_FIELDS)) {
        throw new ReviewRequestError('Hay campos de catálogo no admitidos.', 400);
    }
    if ($create && (!isset($changes['title']) || trim((string) $changes['title']) === '')) {
        throw new ReviewRequestError('Escribe el título del producto.', 400);
    }
    if ($create && (!isset($changes['sku']) || !is_string($changes['sku']) || trim($changes['sku']) === '')) {
        throw new ReviewRequestError('Escribe un SKU único para el nuevo producto.', 400);
    }
    foreach ($changes as $field => $value) {
        if (in_array($field, ['category_ids', 'is_featured'], true)) { continue; }
        if ($value !== null && !is_string($value)) { throw new ReviewRequestError('El campo ' . $field . ' debe ser texto.', 400); }
        if (is_string($value) && strlen($value) > (in_array($field, ['description', 'short_description'], true) ? 500000 : 1000)) {
            throw new ReviewRequestError('El campo ' . $field . ' es demasiado largo.', 400);
        }
    }
    if (array_key_exists('title', $changes) && trim((string) $changes['title']) === '') {
        throw new ReviewRequestError('El título no puede estar vacío.', 400);
    }
    foreach (['retail_price', 'sale_price'] as $field) {
        if (array_key_exists($field, $changes)) {
            review_validate_numbers(['retail_price' => $changes[$field]], 'tienda', ['retail_price']);
        }
    }
    foreach (['pages', 'volume'] as $field) {
        if (array_key_exists($field, $changes)) { review_validate_numbers($changes, 'tienda', [$field]); }
    }
    foreach (['isbn', 'sku'] as $field) {
        if (isset($changes[$field]) && (strlen($changes[$field]) > 128 || preg_match('/[\x00-\x1F\x7F]/', $changes[$field]))) {
            throw new ReviewRequestError('Revisa el ISBN / referencia y el SKU.', 400);
        }
    }
    if (array_key_exists('is_featured', $changes) && !in_array($changes['is_featured'], [0, 1], true)) {
        throw new ReviewRequestError('Destacado debe ser Sí o No.', 400);
    }
    if (array_key_exists('yumekai_status', $changes)
        && !array_key_exists((string) $changes['yumekai_status'], wc_get_product_stock_status_options())) {
        throw new ReviewRequestError('Selecciona un estado de disponibilidad registrado en la tienda.', 400);
    }
    if (array_key_exists('tax_class', $changes)) {
        $taxes = array_merge([''], array_map('sanitize_title', WC_Tax::get_tax_classes()));
        if (!in_array($changes['tax_class'], $taxes, true)) { throw new ReviewRequestError('La clase de impuesto no existe en la tienda.', 400); }
    }
    if ($create && (!array_key_exists('tax_class', $changes) || !isset($changes['yumekai_status']))) {
        throw new ReviewRequestError('Selecciona el impuesto y la disponibilidad del nuevo producto.', 400);
    }
    if (array_key_exists('category_ids', $changes)) {
        if (!is_array($changes['category_ids']) || count($changes['category_ids']) > 100) { throw new ReviewRequestError('Revisa las categorías.', 400); }
        foreach ($changes['category_ids'] as $id) {
            if (!is_int($id) || $id < 1) { throw new ReviewRequestError('Una categoría no es válida.', 400); }
            $term = get_term($id, 'product_cat');
            if (!$term || is_wp_error($term)) { throw new ReviewRequestError('Una categoría ya no existe. Recarga la tienda.', 409); }
        }
        $info = store_category_info($changes['category_ids'], null);
        if ($info['category_issue']) { throw new ReviewRequestError($info['category_issue'], 400); }
    }
}

function store_catalog_apply($product, array $changes): void
{
    store_catalog_validate($changes);
    // Manual prices are independent. No automatic discount or stock-unit changes.
    $regular = array_key_exists('retail_price', $changes) ? $changes['retail_price'] : $product->get_regular_price('edit');
    $sale = array_key_exists('sale_price', $changes) ? $changes['sale_price'] : $product->get_sale_price('edit');
    if ($sale !== null && $sale !== '' && ($regular === null || $regular === '' || (float) $sale > (float) $regular)) {
        throw new ReviewRequestError('El precio rebajado no puede superar el PVP ni existir sin PVP.', 400);
    }
    if (isset($changes['yumekai_status']) && $product->get_manage_stock('edit')
        && $changes['yumekai_status'] !== $product->get_stock_status('edit')) {
        throw new ReviewRequestError('Esta ficha gestiona unidades. Cambia sus unidades desde WooCommerce antes de modificar su disponibilidad.', 409);
    }
    foreach ($changes as $field => $value) {
        if (isset(STORE_META_FIELDS[$field])) {
            $product->update_meta_data(STORE_META_FIELDS[$field], sanitize_text_field((string) ($value ?? '')));
        } elseif ($field === 'isbn') { $product->update_meta_data('_yk_isbn', sanitize_text_field((string) ($value ?? ''))); }
        elseif ($field === 'title') { $product->set_name(sanitize_text_field((string) $value)); }
        elseif ($field === 'sku') { $product->set_sku((string) ($value ?? '')); }
        elseif ($field === 'description') { $product->set_description(wp_kses_post((string) ($value ?? ''))); }
        elseif ($field === 'short_description') { $product->set_short_description(wp_kses_post((string) ($value ?? ''))); }
        elseif ($field === 'retail_price') { $product->set_regular_price($value ?? ''); }
        elseif ($field === 'sale_price') { $product->set_sale_price($value ?? ''); }
        elseif ($field === 'yumekai_status') { $product->set_stock_status($value); }
        elseif ($field === 'is_featured') { $product->set_featured((bool) $value); }
        elseif ($field === 'tax_class') { $product->set_tax_class($value); }
        elseif ($field === 'category_ids') {
            $product->set_category_ids($value);
            $info = store_category_info($value, null);
            // Keep the legacy custom field consistent when the user changes categories.
            $product->update_meta_data('_yk_item_kind', strtolower($info['work_type'] ?? ''));
        }
    }
}

function store_catalog_lock(int $id, string $revision)
{
    global $wpdb;
    $locked = $wpdb->get_var($wpdb->prepare("SELECT ID FROM {$wpdb->posts} WHERE ID = %d AND post_type = 'product' FOR UPDATE", $id));
    if (!$locked) { throw new ReviewRequestError('El producto ya no existe. Recarga la tienda.', 409); }
    $wpdb->get_results($wpdb->prepare("SELECT meta_id FROM {$wpdb->postmeta} WHERE post_id = %d FOR UPDATE", $id));
    $wpdb->get_results($wpdb->prepare("SELECT term_taxonomy_id FROM {$wpdb->term_relationships} WHERE object_id = %d FOR UPDATE", $id));
    if ($wpdb->last_error) { throw new RuntimeException('No se pudo comprobar el producto actual.'); }
    clean_post_cache($id);
    $product = wc_get_product($id);
    if (!$product || !in_array($product->get_status('edit'), STORE_PUBLICATION_STATUSES, true)) {
        throw new ReviewRequestError('El producto ya no está disponible en el catálogo. Recarga la tienda.', 409);
    }
    if (!hash_equals(store_snapshot($product)['_store_revision'], $revision)) {
        throw new ReviewRequestError('El producto cambió en WooCommerce. Recarga y revisa sus datos antes de volver a guardarlo.', 409);
    }
    return $product;
}

function store_catalog_action(string $action, array $entries): array
{
    if (!in_array($action, ['update', 'unpublish', 'publish'], true) || count($entries) < 1 || count($entries) > 20) {
        throw new ReviewRequestError('Selecciona entre 1 y 20 productos y una acción válida.', 400);
    }
    $seen = [];
    foreach ($entries as $entry) {
        if (!is_array($entry) || !is_int($entry['id'] ?? null) || $entry['id'] < 1 || isset($seen[$entry['id']])
            || !is_string($entry['expected_revision'] ?? null) || preg_match('/\A[0-9a-f]{64}\z/', $entry['expected_revision']) !== 1) {
            throw new ReviewRequestError('Revisa el ID y la versión de los productos.', 400);
        }
        if ($action === 'update') {
            if (!is_array($entry['changes'] ?? null)) { throw new ReviewRequestError('Faltan los campos que quieres guardar.', 400); }
            store_catalog_validate($entry['changes']);
        }
        $seen[$entry['id']] = true;
    }
    global $wpdb;
    $saved = $failed = [];
    $stop = false;
    foreach ($entries as $entry) {
        $id = $entry['id'];
        if ($stop) { $failed[] = ['id' => $id, 'message' => 'No se envió: comprueba primero el resultado anterior.', 'status_code' => 503]; continue; }
        $transaction = false;
        try {
            if ($wpdb->query('START TRANSACTION') === false) { throw new RuntimeException('No se pudo iniciar la operación.'); }
            $transaction = true;
            $product = store_catalog_lock($id, $entry['expected_revision']);
            $previousUrl = store_product_url($product);
            $expectedStatus = $product->get_status('edit');
            if ($action === 'update') {
                if ($product->get_type() !== 'simple') { throw new ReviewRequestError('El editor admite productos simples. Edita este tipo de producto en WooCommerce.', 400); }
                store_catalog_apply($product, $entry['changes']);
            } else {
                $status = $product->get_status('edit');
                if (($action === 'unpublish' && !in_array($status, ['publish', 'draft'], true)) || ($action === 'publish' && $status !== 'draft')) {
                    throw new ReviewRequestError('La acción requiere un producto publicado o un borrador, respectivamente. Recarga la tienda.', 409);
                }
                if ($action === 'publish' && $product->get_type() === 'simple'
                    && (trim($product->get_name('edit')) === '' || $product->get_regular_price('edit') === '')) {
                    throw new ReviewRequestError('Completa el título y el PVP antes de publicar este borrador.', 400);
                }
                $expectedStatus = $action === 'unpublish' ? 'draft' : 'publish';
                $product->set_status($expectedStatus);
            }
            $product->save();
            if ($wpdb->last_error) { throw new RuntimeException('No se pudo guardar el producto.'); }
            store_verify_database_status($id, $expectedStatus);
            clean_post_cache($id);
            $snapshot = store_snapshot(wc_get_product($id));
            if (($action === 'unpublish' && $snapshot['publication_status'] !== 'draft')
                || ($action === 'publish' && $snapshot['publication_status'] !== 'publish')) {
                throw new ReviewRequestError('La tienda no aceptó el estado de publicación. Revisa sus reglas y recarga el producto.', 409);
            }
            if ($wpdb->query('COMMIT') === false) { throw new RuntimeException('No se pudo confirmar el guardado.'); }
            $transaction = false;
            // Confirm the committed database state before reporting success.
            try { store_verify_database_status($id, $expectedStatus); }
            catch (Throwable $error) { throw new RuntimeException('Cambió el estado después del guardado: ' . $error->getMessage(), 0, $error); }
            $warnings = store_clear_product_cache($id, $previousUrl);
            $snapshot = store_snapshot(wc_get_product($id));
            if ($snapshot['publication_status'] !== $expectedStatus) { throw new RuntimeException('La lectura posterior no coincide con el estado confirmado.'); }
            $saved[] = ['id' => $id, 'product' => $snapshot, 'warnings' => $warnings,
                'verification' => ['database_status' => $expectedStatus, 'verified_at' => gmdate('c')]];
            yumekai_log('store.catalog_saved', ['action' => $action, 'id' => $id, 'fields' => array_keys($entry['changes'] ?? [])]);
        } catch (Throwable $error) {
            if ($transaction) { $wpdb->query('ROLLBACK'); }
            clean_post_cache($id);
            wc_delete_product_transients($id);
            $code = $error instanceof ReviewRequestError ? $error->getCode() : ($error instanceof WC_Data_Exception ? 400 : 500);
            $message = $code < 500 ? $error->getMessage() : 'No se pudo confirmar el resultado. Recarga la tienda antes de reintentar.';
            $failed[] = ['id' => $id, 'message' => $message, 'status_code' => $code];
            yumekai_log('store.catalog_failed', ['action' => $action, 'id' => $id, 'message' => $error->getMessage()]);
            $stop = $code >= 500;
        }
    }
    return ['saved' => $saved, 'failed' => $failed];
}

/** A request token is committed with the product, so an uncertain response can be retried without creating a duplicate. */
function store_catalog_create(array $fields, string $requestId): array
{
    if (preg_match('/\A[0-9a-f]{32}\z/', $requestId) !== 1) { throw new ReviewRequestError('Falta el identificador de creación.', 400); }
    store_catalog_validate($fields, true);
    ksort($fields);
    $fingerprint = hash('sha256', json_encode($fields, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));
    global $wpdb;
    $option = 'yumekai_create_' . $requestId;
    $transaction = false;
    $id = 0;
    try {
        if ($wpdb->query('START TRANSACTION') === false) { throw new RuntimeException('No se pudo iniciar la creación.'); }
        $transaction = true;
        $claim = $wpdb->query($wpdb->prepare("INSERT IGNORE INTO {$wpdb->options} (option_name, option_value, autoload) VALUES (%s, %s, 'no')", $option, ''));
        $value = $wpdb->get_var($wpdb->prepare("SELECT option_value FROM {$wpdb->options} WHERE option_name = %s FOR UPDATE", $option));
        if ($claim === false || $value === null || $wpdb->last_error) { throw new RuntimeException('No se pudo registrar la creación.'); }
        if ($value !== '') {
            $receipt = json_decode($value, true, 512, JSON_THROW_ON_ERROR);
            if (!hash_equals($receipt['fingerprint'], $fingerprint)) { throw new ReviewRequestError('Ese identificador ya se usó con otros datos. Comprueba el producto antes de crear otro.', 409); }
            $id = (int) $receipt['id'];
            clean_post_cache($id);
            $product = wc_get_product($id);
            if (!$product) { throw new ReviewRequestError('El producto de esta solicitud ya no existe. Revisa la tienda.', 409); }
        } else {
            // Guard against a second click or a new window using the same reference.
            if (!empty($fields['isbn'])) {
                $existing = $wpdb->get_var($wpdb->prepare("SELECT post_id FROM {$wpdb->postmeta} WHERE meta_key = '_yk_isbn' AND meta_value = %s LIMIT 1", $fields['isbn']));
                if ($existing) { throw new ReviewRequestError('Ya existe un producto con ese ISBN / referencia (ID ' . $existing . ').', 409); }
            }
            $product = new WC_Product_Simple();
            $product->set_status('draft');
            $product->set_manage_stock(false);
            store_catalog_apply($product, $fields);
            $id = (int) $product->save();
            if ($id < 1 || $wpdb->last_error) { throw new RuntimeException('No se pudo crear el borrador.'); }
            $receipt = json_encode(['fingerprint' => $fingerprint, 'id' => $id], JSON_THROW_ON_ERROR);
            if ($wpdb->query($wpdb->prepare("UPDATE {$wpdb->options} SET option_value = %s WHERE option_name = %s", $receipt, $option)) === false) {
                throw new RuntimeException('No se pudo confirmar la creación.');
            }
        }
        clean_post_cache($id);
        $snapshot = store_snapshot(wc_get_product($id));
        if ($wpdb->query('COMMIT') === false) { throw new RuntimeException('No se pudo confirmar la creación.'); }
        $transaction = false;
        yumekai_log('store.created', ['id' => $id, 'request_id' => $requestId]);
        return ['id' => $id, 'product' => $snapshot, 'request_id' => $requestId];
    } catch (Throwable $error) {
        if ($transaction) { $wpdb->query('ROLLBACK'); }
        if ($id) { clean_post_cache($id); wc_delete_product_transients($id); }
        throw $error;
    }
}
