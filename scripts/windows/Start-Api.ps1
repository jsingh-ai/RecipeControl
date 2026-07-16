[CmdletBinding()]
param(
    [string]$BindAddress = "0.0.0.0",
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$Console
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

if (-not (Test-Path ".env")) { throw "Missing .env. Copy .env.windows.example to .env and configure it first." }
if (-not (Test-Path ".venv\Scripts\python.exe")) { throw "Missing virtual environment. Run Install-RecipeControl.ps1 first." }
if (-not (Test-Path "frontend\dist\index.html")) { throw "Missing frontend build. Run Install-RecipeControl.ps1 or npm run build in frontend." }

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$Arguments = @("-m", "uvicorn", "recipecontrol.api:app", "--host", $BindAddress, "--port", $Port.ToString(), "--no-server-header")

if ($Console) {
    & .\.venv\Scripts\python.exe @Arguments
}
else {
    & .\.venv\Scripts\python.exe @Arguments *>> "logs\api.log"
}
exit $LASTEXITCODE
