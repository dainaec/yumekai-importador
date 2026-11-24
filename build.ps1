
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"

Write-Host "Compilando Yumekai..." -ForegroundColor Cyan

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

Write-Host ""
Write-Host "Compilacion completada correctamente." -ForegroundColor Green
Write-Host "Ejecutable: dist\Yumekai\Yumekai.exe"
