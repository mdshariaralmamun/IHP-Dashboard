@echo off
REM Startup script for IHP Design and Construction Platform with RBAC
REM This script will setup and start both backend and frontend servers

echo ============================================================
echo IHP Design and Construction Platform - Startup Script
echo ============================================================
echo.

cd /d "%~dp0"

REM Check if backend virtual environment exists
if not exist "backend\.venv\Scripts\python.exe" (
    echo ERROR: Backend virtual environment not found!
    echo Please run: cd backend && python -m venv .venv && .venv\Scripts\pip install -e .
    pause
    exit /b 1
)

REM Step 1: Run database migrations
echo [1/5] Running database migrations...
cd backend
.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
    echo WARNING: Migration failed or already applied
)
echo.

REM Step 2: Seed RBAC roles (if not already seeded)
echo [2/5] Seeding RBAC roles and permissions...
.venv\Scripts\python.exe -m app.scripts.seed_rbac_roles
if errorlevel 1 (
    echo WARNING: Seeding failed or already completed
)
echo.

REM Step 3: Check if frontend dependencies are installed
cd ..\frontend
if not exist "node_modules" (
    echo [3/5] Installing frontend dependencies...
    call npm install
) else (
    echo [3/5] Frontend dependencies already installed
)
echo.

REM Step 4: Start backend server in new window
echo [4/5] Starting backend server on port 8001...
cd ..\backend
start "IHP Backend Server" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001"
echo Backend server starting... (http://localhost:8001)
echo.

REM Wait a moment for backend to initialize
timeout /t 3 /nobreak >nul

REM Step 5: Start frontend server in new window
echo [5/5] Starting frontend server on port 3000...
cd ..\frontend
start "IHP Frontend Server" cmd /k "npm run dev"
echo Frontend server starting... (http://localhost:3000)
echo.

echo ============================================================
echo SETUP COMPLETE!
echo ============================================================
echo.
echo Backend API:  http://localhost:8001
echo API Docs:     http://localhost:8001/docs
echo Frontend:     http://localhost:3000
echo.
echo RBAC Admin Pages:
echo - Roles:      http://localhost:3000/admin/roles
echo - Users:      http://localhost:3000/admin/users-roles
echo.
echo Two new windows have opened with the servers.
echo Close those windows to stop the servers.
echo.
echo Press any key to open the application in your browser...
pause >nul

REM Open browser to login page
start http://localhost:3000/login

echo.
echo Application opened in browser!
echo Keep the server windows open while using the application.
echo.
pause
