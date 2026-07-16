[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

if (-not (Test-Path ".env")) { throw "Missing .env. Copy .env.windows.example to .env and configure it first." }
if (-not (Test-Path ".venv\Scripts\python.exe")) { throw "Missing virtual environment. Run Install-RecipeControl.ps1 first." }

& .\.venv\Scripts\python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Alembic migration failed. No application process was started." }
