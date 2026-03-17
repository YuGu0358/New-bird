@echo off
setlocal

set "ROOT_DIR=%~dp0.."
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"
set "BACKEND_DIR=%ROOT_DIR%\backend"
set "FRONTEND_DIR=%ROOT_DIR%\frontend"

cd /d "%BACKEND_DIR%"

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
)

call ".venv\Scripts\python.exe" -m pip install -r requirements-desktop.txt >nul

cd /d "%FRONTEND_DIR%"

if not exist "node_modules\vite\bin\vite.js" (
  call npm install >nul
)

call npm run build >nul

cd /d "%BACKEND_DIR%"
call ".venv\Scripts\python.exe" desktop_app.py
