@echo off
title Community Forest Management - Starting Servers

cls
echo.
echo ========================================
echo  Community Forest Management System
echo  Starting All Servers...
echo ========================================
echo.

REM Stop any existing servers first
echo Stopping any existing servers...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo Done.
echo.

REM Set Python encoding to UTF-8 to avoid charmap errors
set PYTHONIOENCODING=utf-8

REM Start Backend Server in new window (with debug logging)
echo [1/2] Starting Backend Server (Port 8001)...
start "Backend Server - Port 8001" cmd /k "set PYTHONIOENCODING=utf-8 && set DEBUG_VOLUME_CALC=true && cd /d D:\forest_management\backend && ..\venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8001"
echo Backend server window opened
echo.

REM Wait for backend to start
echo Waiting for backend to initialize (3 seconds)...
timeout /t 3 /nobreak >nul
echo.

REM Start Frontend Server in new window
echo [2/2] Starting Frontend Server (Port 3001)...
start "Frontend Server - Port 3001" cmd /k "cd /d D:\forest_management\frontend && npm run dev"
echo Frontend server window opened
echo.

echo ========================================
echo  Servers Started Successfully!
echo ========================================
echo.
echo  Backend:  http://localhost:8001
echo  Docs:     http://localhost:8001/docs
echo  Frontend: http://localhost:3001
echo.
echo  Login:    demo@forest.com / Demo1234
echo.
echo  2 new windows opened - check them!
echo ========================================
echo.
pause
