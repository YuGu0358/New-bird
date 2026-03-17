@echo off
setlocal

set "ROOT_DIR=%~dp0.."
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"
set "BACKEND_DIR=%ROOT_DIR%\backend"
set "FRONTEND_DIR=%ROOT_DIR%\frontend"
set "OUTPUT_DIR=%ROOT_DIR%\output\desktop-windows"
set "APP_NAME=Trading Raven Platform"

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

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

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

call ".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name "%APP_NAME%" ^
  --paths "%BACKEND_DIR%" ^
  --hidden-import aiosqlite ^
  --collect-submodules aiosqlite ^
  --add-data "%FRONTEND_DIR%\dist;frontend_dist" ^
  desktop_app.py

if exist "%OUTPUT_DIR%\%APP_NAME%" rmdir /s /q "%OUTPUT_DIR%\%APP_NAME%"
xcopy "dist\%APP_NAME%" "%OUTPUT_DIR%\%APP_NAME%\" /E /I /Y >nul

echo Desktop app built at: %OUTPUT_DIR%\%APP_NAME%\%APP_NAME%.exe
