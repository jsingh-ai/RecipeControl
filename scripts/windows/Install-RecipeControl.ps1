[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher (py.exe) was not found. Install 64-bit Python 3.12 and enable the Python Launcher."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install the Node.js 20 LTS release and reopen PowerShell."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Creating the Python 3.12 virtual environment failed." }
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Updating pip failed." }
& .\.venv\Scripts\python.exe -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "Installing RecipeControl failed." }

Push-Location frontend
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) { throw "Installing frontend packages failed." }
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "Building the production frontend failed." }
}
finally {
    Pop-Location
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.windows.example" ".env"
    Write-Warning "Created .env from the safe template. Edit it before migration or startup."
}

New-Item -ItemType Directory -Force -Path "logs", "backups" | Out-Null
Write-Host "Installation and frontend build completed. Next, edit .env and run Invoke-Migrations.ps1."
