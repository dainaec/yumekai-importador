
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"

# Obtener la version del programa
$version = & $python -c "from yumekai_importer.version import APP_VERSION; print(APP_VERSION)"

if ($LASTEXITCODE -ne 0 -or -not $version) {
    throw "No se pudo obtener la version."
}

$version = $version.Trim()

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  YUMEKAI - Compilacion v$version" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# Compilar
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

if ($LASTEXITCODE -ne 0) {
    throw "No se pudo compilar Yumekai."
}

if (-not (Test-Path ".\dist\Yumekai\Yumekai.exe")) {
    throw "No se encontro el ejecutable."
}

# Preparar carpeta de distribuciones
New-Item -ItemType Directory -Force releases | Out-Null

$zipPath = ".\releases\Yumekai-v$version-Windows.zip"

# Generar ZIP
Write-Host "Preparando archivo ZIP..." -ForegroundColor Cyan

Compress-Archive `
    -Path ".\dist\Yumekai" `
    -DestinationPath $zipPath `
    -Force

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  COMPILACION COMPLETADA" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Version: $version"
Write-Host "Ejecutable: dist\Yumekai\Yumekai.exe"
Write-Host "Distribucion: $zipPath"
Write-Host ""
