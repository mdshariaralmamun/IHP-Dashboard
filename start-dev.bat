@echo off
REM Start the IHP dev servers (backend :8001, frontend :3000).
REM Port 8000 is occupied by another local service on this machine.
set ROOT=%~dp0
start "IHP Backend  :8001" cmd /k "cd /d "%ROOT%backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001"
start "IHP Frontend :3000" cmd /k "cd /d "%ROOT%frontend" && npm run dev"
echo Starting backend on http://localhost:8001 and frontend on http://localhost:3000
echo Close the two new windows to stop the servers.
