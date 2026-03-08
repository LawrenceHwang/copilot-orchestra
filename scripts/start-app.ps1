$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")

Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not installed or not on PATH."
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "npm is not installed or not on PATH."
}

Write-Host "Starting backend on http://127.0.0.1:8000 ..."
$backend = Start-Process -FilePath "uv" -ArgumentList @("run", "uvicorn", "backend.main:app", "--reload", "--port", "8000") -WorkingDirectory $RepoRoot -PassThru

try {
    if (-not (Test-Path (Join-Path $RepoRoot "src/frontend/node_modules"))) {
        Write-Host "Installing frontend dependencies..."
        Push-Location (Join-Path $RepoRoot "src/frontend")
        npm install
        Pop-Location
    }

    Write-Host "Starting frontend on http://localhost:5173 ..."
    Push-Location (Join-Path $RepoRoot "src/frontend")
    npm run dev
    Pop-Location
}
finally {
    if ($backend -and -not $backend.HasExited) {
        Write-Host "Stopping backend (PID $($backend.Id))..."
        Stop-Process -Id $backend.Id -Force
    }
}
