@echo off
rem ──────────────────────────────────────────────────────────
rem  People Counter System — скрипт запуска (Windows)
rem  Использование:  start.bat [dev|prod]
rem ──────────────────────────────────────────────────────────
setlocal EnableDelayedExpansion

set MODE=%1
if "%MODE%"=="" set MODE=prod

cd /d "%~dp0"
set PROJ_DIR=%~dp0

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
call .venv\Scripts\activate.bat
echo [OK] venv активирован

rem ── Python-зависимости ────────────────────────────────
python -c "import fastapi" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Устанавливаем Python-зависимости...
    pip install -r requirements.txt -q
    echo [OK] Python-зависимости установлены
) else (
    echo [OK] Python-зависимости OK
)

rem ── Директория данных ─────────────────────────────────
if not exist "data" mkdir data
echo [OK] data/ OK

rem ════════════════════════════════════════════════════════
rem  Node.js + npm
rem ════════════════════════════════════════════════════════
where node >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Node.js не найден. Установите Node.js 18+ ^(https://nodejs.org^)
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do echo [OK] Node.js %%v

rem npm install — всегда запускаем, чтобы:
rem   • установить зависимости если node_modules отсутствует
rem   • пересобрать нативные модули под текущую платформу
rem npm install быстро завершается если ничего не изменилось.
echo [!] npm install ^(frontend^)...
cd /d "%PROJ_DIR%frontend"
if exist "package-lock.json" (
    rem Удаляем lock-файл если он был создан под другую платформу
    rem ^(например, перенесён с macOS, а запуск на Windows^)
    if exist "node_modules\@rollup" (
        dir /b "node_modules\@rollup" 2>nul | findstr /i "darwin\|linux" >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo [!] Обнаружены модули от другой платформы — пересоздаём...
            rmdir /s /q node_modules
            del /f /q package-lock.json
        )
    )
)
npm install --prefer-offline 2>nul || npm install
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] npm install завершился с ошибкой
    pause & exit /b 1
)
echo [OK] npm-зависимости OK
cd /d "%PROJ_DIR%"

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

    start "People Counter - Frontend" cmd /c "cd /d ""%PROJ_DIR%frontend"" && npm run dev"
    set PYTHONPATH=%PROJ_DIR%
    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

) else (
    if not exist "frontend\dist" (
        echo [!] Собираем фронтенд...
        cd /d "%PROJ_DIR%frontend"
        npm run build
        if %ERRORLEVEL% NEQ 0 (
            echo [ERROR] Сборка фронтенда завершилась с ошибкой
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
    echo   Закройте это окно для остановки
    echo.

    set PYTHONPATH=%PROJ_DIR%
    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
)

pause
