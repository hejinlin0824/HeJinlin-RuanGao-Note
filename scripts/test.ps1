[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ruangao-note-test-" + [guid]::NewGuid().ToString("N"))
$dbPath = Join-Path $tempRoot "migration-test.db"
$previousDatabaseUrl = $env:DATABASE_URL

function Invoke-Check {
    param([string]$Title, [scriptblock]$Command)
    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Title failed with exit code $LASTEXITCODE." }
    Write-Host "[PASS] $Title" -ForegroundColor Green
}

try {
    if (-not (Test-Path $python)) {
        throw "Cannot find .venv Python: $python. Create the environment and install dependencies first."
    }
    Push-Location $root
    Invoke-Check "Python version" {
        & $python -c "import sys; print(sys.version); assert sys.version_info[:3] == (3, 13, 15), 'Expected Python 3.13.15'"
    }
    # Run migrations against a disposable database, never the user data database.
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    $sqlitePath = $dbPath.Replace("\", "/")
    $env:DATABASE_URL = "sqlite:///$sqlitePath"
    Invoke-Check "Alembic upgrade head (temporary SQLite database)" {
        & $python -m alembic upgrade head
    }
    Invoke-Check "Alembic current" {
        & $python -m alembic current
    }
    Invoke-Check "Ruff" {
        & $python -m ruff check .
    }
    Invoke-Check "pytest" {
        & $python -m pytest -v
    }
    Write-Host ""
    Write-Host "All checks passed. Temporary migration database will be removed." -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "[FAILED] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
    else { $env:DATABASE_URL = $previousDatabaseUrl }
    if (Test-Path $tempRoot) { Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
    if ((Get-Location).Path -eq $root) { Pop-Location }
}
