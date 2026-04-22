@echo off
rem ──────────────────────────────────────────────────────────
rem  People Counter System — скрипт запуска (Windows)
rem  Использование:  start.bat [dev|prod]
rem ──────────────────────────────────────────────────────────
setlocal EnableDelayedExpansion

set MODE=%1
if "%MODE%"=="" set MODE=prod

cd /d "%~dp0"
rem Используем set "VAR=..." чтобы корректно обрабатывать пути с пробелами
set "PROJ_DIR=%~dp0"

echo.
echo ╔══════════════════════════════════════════╗
echo ║    People Counter System  v4.0           ║
echo ╚══════════════════════════════════════════╝
echo.

rem ════════════════════════════════════════════════════════
rem  Python
rem ════════════════════════════════════════════════════════
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python не найден. Установите Python 3.10+
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo [OK] %%v

rem ── Виртуальное окружение ─────────────────────────────
if not exist ".venv" (
    echo [!] Создаём виртуальное окружение .venv...
    python -m venv .venv
)
call ".venv\Scripts\activate.bat"
echo [OK] venv активирован

rem ── Python-зависимости ────────────────────────────────
python -c "import fastapi" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Устанавливаем Python-зависимости...
    pip install -r requirements.txt -q
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] pip install завершился с ошибкой
        pause & exit /b 1
    )
    echo [OK] Python-зависимости установлены
) else (
    echo [OK] Python-зависимости OK
)

rem ── Директория данных ─────────────────────────────────
if not exist "data" mkdir data
echo [OK] data/ OK

rem ════════════════════════════════════════════════════════
rem  Модель YOLOv8
rem ════════════════════════════════════════════════════════
set HAS_PT=0
set HAS_ONNX=0
if exist "yolov8n.pt"   set HAS_PT=1
if exist "yolov8n.onnx" set HAS_ONNX=1

if !HAS_PT!==0 if !HAS_ONNX!==0 (
    echo [!] Модель YOLOv8n не найдена. Скачиваем (~6 MB)...
    python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Не удалось скачать модель. Проверьте соединение с интернетом.
        pause & exit /b 1
    )
    set HAS_PT=1
    echo [OK] Модель скачана: yolov8n.pt
)

if !HAS_ONNX!==1 (
    echo [OK] Модель: yolov8n.onnx  (ONNX — оптимально для Intel CPU^)
) else if !HAS_PT!==1 (
    echo [OK] Модель: yolov8n.pt
    echo.
    echo   Для ускорения на Intel CPU рекомендуется экспорт в ONNX.
    set /p "EXPORT_CHOICE=  Экспортировать в ONNX прямо сейчас? [y/N]: "
    if /i "!EXPORT_CHOICE!"=="y" (
        echo [!] Экспорт модели в ONNX...
        python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"
        if !ERRORLEVEL! EQU 0 (
            echo [OK] yolov8n.onnx создан. Установите inference_backend=onnx в настройках.
            set HAS_ONNX=1
        ) else (
            echo [WARN] Экспорт не удался. Продолжаем с .pt
        )
    )
)
echo.

rem ════════════════════════════════════════════════════════
rem  Node.js + npm
rem ════════════════════════════════════════════════════════
where node >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Node.js не найден. Установите Node.js 18+ ^(https://nodejs.org^)
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do echo [OK] Node.js %%v

echo [!] npm install (frontend)...
cd /d "%PROJ_DIR%frontend"

rem Удаляем node_modules если созданы под другую платформу (darwin/linux)
if exist "node_modules\@rollup" (
    dir /b "node_modules\@rollup" 2>nul | findstr /i "darwin linux" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo [!] Обнаружены модули от другой платформы — пересоздаём...
        rmdir /s /q node_modules
        if exist "package-lock.json" del /f /q package-lock.json
    )
)

npm install --prefer-offline 2>nul
if %ERRORLEVEL% NEQ 0 npm install
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] npm install завершился с ошибкой
    pause & exit /b 1
)
echo [OK] npm-зависимости OK
cd /d "%PROJ_DIR%"

rem ════════════════════════════════════════════════════════
rem  PYTHONPATH — устанавливаем ДО блока if/else
rem  (set "VAR=..." — кавычки снаружи, чтобы пробелы в пути работали)
rem ════════════════════════════════════════════════════════
set "PYTHONPATH=%PROJ_DIR%"

rem ════════════════════════════════════════════════════════
rem  Режим запуска
rem ════════════════════════════════════════════════════════
if "%MODE%"=="dev" (
    echo.
    echo   Backend : http://localhost:8000
    echo   Frontend: http://localhost:5173  ^<-- открыть в браузере
    echo   API docs: http://localhost:8000/docs
    echo.
    echo   Закройте это окно для остановки
    echo.

    start "People Counter - Frontend" cmd /k "cd /d ""%PROJ_DIR%frontend"" && npm run dev"
    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

) else (
    if not exist "frontend\dist" (
        echo [!] Собираем фронтенд...
        cd /d "%PROJ_DIR%frontend"
        npm run build
        if !ERRORLEVEL! NEQ 0 (
            echo [ERROR] Сборка фронтенда завершилась с ошибкой
            cd /d "%PROJ_DIR%"
            pause & exit /b 1
        )
        cd /d "%PROJ_DIR%"
        echo [OK] Фронтенд собран
    ) else (
        echo [OK] Фронтенд: найдена сборка frontend\dist\
    )

    echo.
    echo   URL: http://localhost:8000
    echo.
    echo   Закройте это окно (или Ctrl+C) для остановки
    echo.

    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
    echo.
    echo [!] Сервер остановлен. Код выхода: %ERRORLEVEL%
)

echo.
pause
