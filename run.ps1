# Start the mission-preparation front-end.
#   .\run.ps1            -> mock mode (no backend needed)
#   .\run.ps1 -Live      -> live mode against $env:AUDIT_API_BASE_URL
param([switch]$Live)

if (-not (Test-Path .venv)) {
    Write-Host "Creating the virtual environment..." -ForegroundColor Cyan
    uv venv --python 3.13
    uv pip install -e ".[dev]"
}

$env:AUDIT_BACKEND_MODE = if ($Live) { "live" } else { "mock" }
Write-Host "Backend mode: $env:AUDIT_BACKEND_MODE" -ForegroundColor Cyan
.venv\Scripts\streamlit.exe run app.py
