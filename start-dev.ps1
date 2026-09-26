# PowerShell launcher for IHP Dev Servers
# Backend runs on port 8001, Frontend runs on port 3000

$root = $PSScriptRoot

Write-Host "Starting IHP Backend on http://localhost:8001..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; & '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --reload --port 8001"

Write-Host "Starting IHP Frontend on http://localhost:3000..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"

Write-Host "`nDev servers are launching!" -ForegroundColor Yellow
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host "Backend:  http://localhost:8001 (Docs: http://localhost:8001/docs)" -ForegroundColor Cyan
