@echo off
rem =========================================================
rem  People Counter System - startup script (Windows)
rem  Usage:  start.bat [dev|prod]
rem =========================================================
setlocal EnableDelayedExpansion

set MODE=%1
if "%MODE%"=="" set MODE=prod

cd /d "%~dp0"
set "PROJ_DIR=%~dp0"

echo.
echo =========================================
echo   People Counter System  v4.0
echo =========================================
echo.

rem =========================================================
rem  Python
rem =========================================================
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo [OK] %%v

rem -- Virtual environment --
if not exist ".venv" (
    echo [..] Creating virtual environment .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause & exit /b 1
    )
)
call .venv\Scripts\activate.bat
echo [OK] venv activated

rem -- Python dependencies --
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [..] Installing Python dependencies...
    pip install -r requirements.txt -q
    if errorlevel 1 (
        echo [ERROR] pip install failed
        pause & exit /b 1
    )
    echo [OK] Python dependencies installed
) else (
    echo [OK] Python dependencies OK
)

rem -- Data directory --
if not exist "data" mkdir data
echo [OK] data/ OK

rem =========================================================
rem  YOLOv8 model check
rem =========================================================
set HAS_PT=0
set HAS_ONNX=0
if exist "yolov8n.pt"   set HAS_PT=1
if exist "yolov8n.onnx" set HAS_ONNX=1

if %HAS_PT%==0 if %HAS_ONNX%==0 goto download_model
goto model_ok

:download_model
echo [..] YOLOv8n model not found. Downloading (~6 MB)...
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
if errorlevel 1 (
    echo [ERROR] Failed to download model. Check internet connection.
    pause & exit /b 1
)
set HAS_PT=1
echo [OK] Model downloaded: yolov8n.pt

:model_ok
if %HAS_ONNX%==1 (
    echo [OK] Model: yolov8n.onnx  (ONNX - recommended for Intel CPU)
    goto model_done
)
echo [OK] Model: yolov8n.pt

echo.
echo   For better performance on Intel CPU, export the model to ONNX.
set /p "EXPORT_CHOICE=  Export yolov8n.pt to ONNX now? [y/N]: "
if /i "%EXPORT_CHOICE%"=="y" goto do_export
goto model_done

:do_export
echo [..] Exporting model to ONNX...
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"
if errorlevel 1 (
    echo [WARN] Export failed. Continuing with .pt
    goto model_done
)
echo [OK] yolov8n.onnx created.
echo      Set inference_backend=onnx in the Settings page.

:model_done
echo.

rem =========================================================
rem  Node.js + npm
rem =========================================================
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install Node.js 18+ from https://nodejs.org
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do echo [OK] Node.js %%v

echo [..] npm install (frontend)...
cd /d "%PROJ_DIR%frontend"

rem Remove node_modules if built for a different platform (darwin/linux -> windows)
if exist "node_modules\@rollup" (
    dir /b "node_modules\@rollup" 2>nul | findstr /i "darwin linux" >nul 2>&1
    if not errorlevel 1 (
        echo [..] Found modules from another platform - rebuilding...
        rmdir /s /q node_modules
        if exist "package-lock.json" del /f /q package-lock.json
    )
)

npm install --prefer-offline
if errorlevel 1 (
    echo [RETRY] Retrying npm install without cache...
    npm install
)
if errorlevel 1 (
    echo [ERROR] npm install failed
    cd /d "%PROJ_DIR%"
    pause & exit /b 1
)
echo [OK] npm dependencies OK
cd /d "%PROJ_DIR%"

rem =========================================================
rem  Set PYTHONPATH before if/else block
rem  (quoted set handles spaces in path correctly)
rem =========================================================
set "PYTHONPATH=%PROJ_DIR%"

rem =========================================================
rem  Launch
rem =========================================================
if "%MODE%"=="dev" goto launch_dev
goto launch_prod

:launch_dev
echo.
echo   Backend : http://localhost:8000
echo   Frontend: http://localhost:5173  ^<-- open in browser
echo   API docs: http://localhost:8000/docs
echo.
echo   Close this window to stop
echo.
start "People Counter - Frontend" cmd /k "cd /d ""%PROJ_DIR%frontend"" && npm run dev"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
goto end

:launch_prod
if not exist "frontend\dist" goto build_frontend
echo [OK] Frontend: existing build found at frontend\dist\
goto start_server

:build_frontend
echo [..] Building frontend (tsc + vite)...
echo      This may take 30-60 seconds on first run.
cd /d "%PROJ_DIR%frontend"
npm run build
if errorlevel 1 (
    echo.
    echo [ERROR] Frontend build failed - see errors above
    cd /d "%PROJ_DIR%"
    pause & exit /b 1
)
cd /d "%PROJ_DIR%"
echo [OK] Frontend built successfully

:start_server

echo.
echo   URL: http://localhost:8000
echo.
echo   Close this window (or Ctrl+C) to stop
echo.
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
echo.
echo [!] Server stopped. Exit code: %ERRORLEVEL%

:end
echo.
pause
