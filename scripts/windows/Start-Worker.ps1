[CmdletBinding()]
param([switch]$Console)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

if (-not (Test-Path ".env")) { throw "Missing .env. Copy .env.windows.example to .env and configure it first." }
if (-not (Test-Path ".venv\Scripts\python.exe")) { throw "Missing virtual environment. Run Install-RecipeControl.ps1 first." }

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
if ($Console) {
    & .\.venv\Scripts\python.exe -m recipecontrol.worker
}
else {
    & .\.venv\Scripts\python.exe -m recipecontrol.worker *>> "logs\worker.log"
}
exit $LASTEXITCODE
