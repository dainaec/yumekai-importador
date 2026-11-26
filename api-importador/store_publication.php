<?php
declare(strict_types=1);

/** Read the persisted status, independently of the WC_Product object being saved. */
function store_verify_database_status(int $id, string $expected): string
{
    global $wpdb;
    $actual = $wpdb->get_var($wpdb->prepare("SELECT post_status FROM {$wpdb->posts} WHERE ID = %d AND post_type = 'product'", $id));
    if ($wpdb->last_error || !is_string($actual)) { throw new RuntimeException('No se pudo verificar el estado guardado en la base de datos.'); }
    if ($actual !== $expected) {
        throw new ReviewRequestError('WooCommerce no guardó el estado solicitado. Estado real: ' . $actual . '. Actualiza la ficha antes de reintentar.', 409);
    }
    return $actual;
}

/** Purge after COMMIT: a public request must never refill the old page during the transaction. */
function store_clear_product_cache(int $id, string $previousUrl): array
{
    $warnings = [];
    try {
        clean_post_cache($id);
        wc_delete_product_transients($id);
        if (function_exists('w3tc_flush_post')) {
            w3tc_flush_post($id, true);
            if ($previousUrl !== '' && function_exists('w3tc_flush_url')) { w3tc_flush_url($previousUrl); }
            yumekai_log('store.cache_purge_requested', ['id' => $id, 'provider' => 'w3_total_cache']);
        }
    } catch (Throwable $error) {
        $warnings[] = 'El estado se guardó, pero no se pudo renovar la ficha pública del ID ' . $id . '. Revisa W3 Total Cache antes de darla por retirada de la web.';
        yumekai_log('store.cache_purge_failed', ['id' => $id, 'message' => $error->getMessage()]);
    }
    return $warnings;
}
