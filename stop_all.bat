@echo off
title Community Forest Management - Stopping Servers

cls
echo.
echo ========================================
echo  Stopping All Servers...
echo ========================================
echo.

echo Stopping Backend (Python)...
taskkill /F /IM python.exe 2>nul
if errorlevel 1 (
    echo No backend running
) else (
    echo Backend stopped
)
echo.

echo Stopping Frontend (Node)...
taskkill /F /IM node.exe 2>nul
if errorlevel 1 (
    echo No frontend running
) else (
    echo Frontend stopped
)
echo.

echo ========================================
echo  All Servers Stopped!
echo ========================================
echo.
pause
