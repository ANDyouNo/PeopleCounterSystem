#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  People Counter System — скрипт запуска (Linux / macOS)
#  Использование:  ./start.sh [dev|prod]
# ──────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-prod}"   # prod | dev

# ── Цвета ──
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║    People Counter System  v4.0           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ════════════════════════════════════════════════════════
#  Python
# ════════════════════════════════════════════════════════
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    error "Python не найден. Установите Python 3.10+"
fi
info "Python: $($PYTHON --version)"

# ── Виртуальное окружение ───────────────────────────────
if [ ! -d ".venv" ]; then
    warn "Создаём виртуальное окружение .venv..."
    $PYTHON -m venv .venv
fi
source .venv/bin/activate
info "venv активирован"

# ── Python-зависимости ──────────────────────────────────
if ! python -c "import fastapi" &>/dev/null; then
    warn "Устанавливаем Python-зависимости..."
    pip install -r requirements.txt -q
    info "Python-зависимости установлены"
else
    info "Python-зависимости OK"
fi

# ── Директория данных ───────────────────────────────────
mkdir -p data
info "data/ OK"

# ════════════════════════════════════════════════════════
#  Node.js + npm
# ════════════════════════════════════════════════════════
if ! command -v node &>/dev/null; then
    error "Node.js не найден. Установите Node.js 18+ (https://nodejs.org)"
fi
info "Node.js: $(node --version)  npm: $(npm --version)"

# npm install — всегда запускаем, чтобы:
#   • установить зависимости если node_modules отсутствует
#   • пересобрать нативные модули под текущую платформу
#     (например, после переноса проекта с Linux на macOS ARM64)
# npm install быстро завершается если ничего не изменилось.
warn "npm install (frontend)..."
cd "$SCRIPT_DIR/frontend"
# Если package-lock.json создан под другую платформу — удаляем его,
# чтобы npm пересчитал нативные опциональные зависимости (rollup, esbuild и т.д.)
if [ -f "package-lock.json" ]; then
    # Определяем платформу из lock-файла и сравниваем с текущей
    LOCK_PLATFORM=$(node -e "try{const l=require('./package-lock.json');const p=Object.keys(l.packages||{}).find(k=>k.includes('@rollup/rollup-'));console.log(p||'')}catch(e){console.log('')}" 2>/dev/null || echo "")
    CURRENT_PLATFORM="node_modules/@rollup/rollup-$(node -e 'console.log(process.platform+"-"+process.arch)' 2>/dev/null || echo 'unknown')"
    if [ -n "$LOCK_PLATFORM" ] && [ "$LOCK_PLATFORM" != "$CURRENT_PLATFORM" ]; then
        warn "Обнаружен package-lock.json от другой платформы — пересоздаём..."
        rm -f package-lock.json
        rm -rf node_modules
    fi
fi
npm install --prefer-offline 2>/dev/null || npm install
info "npm-зависимости OK"
cd "$SCRIPT_DIR"

# ════════════════════════════════════════════════════════
#  Режим запуска
# ════════════════════════════════════════════════════════
if [ "$MODE" = "dev" ]; then
    # ── DEV: FastAPI + Vite dev server параллельно ──────
    echo ""
    echo "  Backend : http://localhost:8000"
    echo "  Frontend: http://localhost:5173  ← открыть в браузере"
    echo "  API docs: http://localhost:8000/docs"
    echo ""
    echo "  Ctrl+C для остановки"
    echo ""

    trap 'kill 0' INT TERM EXIT
    PYTHONPATH="$SCRIPT_DIR" python -m uvicorn backend.main:app \
        --host 0.0.0.0 --port 8000 --reload &
    cd "$SCRIPT_DIR/frontend" && npm run dev &
    wait

else
    # ── PROD: сборка фронтенда + один uvicorn ───────────
    if [ ! -d "frontend/dist" ]; then
        warn "Собираем фронтенд..."
        cd "$SCRIPT_DIR/frontend" && npm run build && cd "$SCRIPT_DIR"
        info "Фронтенд собран"
    else
        info "Фронтенд: найдена сборка frontend/dist/"
    fi

    echo ""
    echo "  URL: http://localhost:8000"
    echo ""
    echo "  Ctrl+C для остановки"
    echo ""

    PYTHONPATH="$SCRIPT_DIR" exec python -m uvicorn backend.main:app \
        --host 0.0.0.0 --port 8000 --workers 1
fi
