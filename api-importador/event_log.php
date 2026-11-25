<?php
declare(strict_types=1);

/** Diagnostics stay beside database.php, outside the public WordPress folder. */
function yumekai_log(string $event, array $context = []): void
{
    $directory = dirname(__DIR__, 2) . '/importer-private';
    $path = $directory . '/yumekai-api.log';
    $request = $_SERVER['HTTP_X_YUMEKAI_REQUEST_ID'] ?? '';
    if (!preg_match('/\A[a-f0-9]{12,32}\z/', $request)) { $request = ''; }
    $entry = json_encode(['time' => gmdate('c'), 'event' => $event, 'request_id' => $request,
        'endpoint' => basename($_SERVER['SCRIPT_NAME'] ?? ''), 'context' => $context],
        JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
    $entry = preg_replace('/(authorization\s*[:=]\s*)(basic|bearer)\s+\S+/i', '$1[OCULTO]', $entry ?? '');
    $entry = preg_replace('/((password|passwd|token|consumer_secret|api_key)\s*[=:]\s*)[^\s,;]+/i', '$1[OCULTO]', $entry);
    $lock = @fopen($path . '.lock', 'c');
    if ($lock === false || !flock($lock, LOCK_EX)) {
        if (is_resource($lock)) { fclose($lock); }
        error_log('Yumekai diagnostics: ' . $entry);
        return;
    }
    try {
        clearstatcache(true, $path);
        if (is_file($path) && filesize($path) >= 2 * 1024 * 1024) {
            @unlink($path . '.5');
            for ($i = 4; $i >= 1; $i--) {
                if (is_file($path . '.' . $i)) { @rename($path . '.' . $i, $path . '.' . ($i + 1)); }
            }
            @rename($path, $path . '.1');
        }
        if (@file_put_contents($path, $entry . PHP_EOL, FILE_APPEND) === false) {
            error_log('Yumekai diagnostics: ' . $entry);
        } else {
            @chmod($path, 0600);
        }
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

function yumekai_response_event(int $status, array $body): void
{
    $counts = [];
    foreach (['saved', 'failed', 'deleted', 'created', 'duplicates', 'products', 'linked', 'updated',
              'missing', 'unpublished', 'conflicts'] as $key) {
        if (isset($body[$key])) { $counts[$key] = is_array($body[$key]) ? count($body[$key]) : $body[$key]; }
    }
    yumekai_log('response.sent', ['status' => $status, 'counts' => $counts,
        'message' => $body['message'] ?? $body['error'] ?? null]);
}

$yumekaiRequestStart = microtime(true);
yumekai_log('request.start', ['method' => $_SERVER['REQUEST_METHOD'] ?? 'CLI']);
register_shutdown_function(static function () use ($yumekaiRequestStart): void {
    $last = error_get_last();
    if ($last !== null && in_array($last['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR], true)) {
        yumekai_log('request.fatal', ['message' => $last['message'], 'file' => basename($last['file']), 'line' => $last['line']]);
    }
    yumekai_log('request.end', ['status' => http_response_code() ?: 200,
        'elapsed_ms' => (int) round(1000 * (microtime(true) - $yumekaiRequestStart))]);
});
