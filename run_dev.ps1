# Launch the backend and frontend for local development.
#   .\run_dev.ps1
$py = "C:\Users\tharu\miniforge3\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

if (-not (Test-Path "examples\motor_adapter\sketch.png")) {
    Write-Host "generating demo inputs..." -ForegroundColor Cyan
    & $py examples\motor_adapter\generate_inputs.py
}

Write-Host "backend  -> http://127.0.0.1:8000" -ForegroundColor Green
Start-Process -NoNewWindow $py -ArgumentList "-m","uvicorn","api.main:app","--host","127.0.0.1","--port","8000"

if (-not (Test-Path "web\node_modules")) {
    Write-Host "installing web dependencies..." -ForegroundColor Cyan
    Push-Location web; npm install; Pop-Location
}

Write-Host "frontend -> http://localhost:5173" -ForegroundColor Green
Push-Location web; npm run dev; Pop-Location
