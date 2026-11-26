$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No se encontro .venv\Scripts\python.exe." }

# Keep a record even if the console is closed after a failed build.
$logDirectory = Join-Path $PSScriptRoot "logs-compilacion"
New-Item -ItemType Directory -Force $logDirectory | Out-Null
$logPath = Join-Path $logDirectory ("build-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
$transcriptStarted = $false
try {
    Start-Transcript -Path $logPath | Out-Null
    $transcriptStarted = $true
    $version = & $python -c "from yumekai_importer.version import APP_VERSION; print(APP_VERSION)"
    if ($LASTEXITCODE -ne 0 -or -not $version) { throw "No se pudo obtener la version." }
    $version = $version.Trim()
    if ($version -notmatch '^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$') { throw "La version no tiene un formato valido." }
    Write-Host ""
    Write-Host "YUMEKAI - Compilacion v$version" -ForegroundColor Magenta
    Write-Host ""

    # Preserve the entry point, assets and Windows keyring options from your build script.
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name "Yumekai" `
        --icon "yumekai_importer/assets/app-icon.ico" `
        --add-data "yumekai_importer/assets;yumekai_importer/assets" `
        --add-data "yumekai_importer/ui/styles/yumekai.qss;yumekai_importer/ui/styles" `
        --add-data "yumekai_importer/ui/styles/icons;yumekai_importer/ui/styles/icons" `
        --collect-all keyring `
        --hidden-import keyring.backends.Windows `
        --paths "." `
        "yumekai_importer/__main__.py"
    if ($LASTEXITCODE -ne 0) { throw "No se pudo compilar Yumekai. Consulta $logPath" }
    if (-not (Test-Path ".\dist\Yumekai\Yumekai.exe")) { throw "No se encontro el ejecutable." }

    New-Item -ItemType Directory -Force releases | Out-Null
    $zipPath = ".\releases\Yumekai-v$version-Windows.zip"
    Write-Host "Preparando archivo ZIP..." -ForegroundColor Cyan
    Compress-Archive -Path ".\dist\Yumekai" -DestinationPath $zipPath -Force
    if (-not (Test-Path $zipPath) -or (Get-Item $zipPath).Length -eq 0) {
        throw "No se pudo comprobar el ZIP de distribucion. Consulta $logPath"
    }
    Write-Host ""
    Write-Host "COMPILACION COMPLETADA" -ForegroundColor Green
    Write-Host "Version: $version"
    Write-Host "Ejecutable: $(Join-Path $PSScriptRoot 'dist\Yumekai\Yumekai.exe')"
    Write-Host "Distribucion: $((Resolve-Path $zipPath).Path)"
    Write-Host "Registro: $logPath"
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
