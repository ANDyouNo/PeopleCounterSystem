#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  People Counter System — скрипт запуска (Linux / macOS)
#  Использование:  ./start.sh [dev|prod]
# ──────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-prod}"

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
#  Модель YOLOv8
# ════════════════════════════════════════════════════════
HAS_PT=0
HAS_ONNX=0
[ -f "yolov8n.pt" ]   && HAS_PT=1
[ -f "yolov8n.onnx" ] && HAS_ONNX=1

if [ $HAS_PT -eq 0 ] && [ $HAS_ONNX -eq 0 ]; then
    warn "Модель YOLOv8n не найдена. Скачиваем (~6 MB)..."
    python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" \
        || error "Не удалось скачать модель. Проверьте соединение с интернетом."
    HAS_PT=1
    info "Модель скачана: yolov8n.pt"
fi

if [ $HAS_ONNX -eq 1 ]; then
    info "Модель: yolov8n.onnx  (ONNX — оптимально для Intel CPU)"
else
    info "Модель: yolov8n.pt"
    echo ""
    echo "  Для ускорения на Intel CPU рекомендуется экспорт в ONNX."
    read -r -p "  Экспортировать в ONNX прямо сейчас? [y/N]: " EXPORT_CHOICE
    if [[ "${EXPORT_CHOICE,,}" == "y" ]]; then
        warn "Экспорт модели в ONNX..."
        if python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"; then
            info "yolov8n.onnx создан. Установите inference_backend=onnx в настройках."
            HAS_ONNX=1
        else
            echo -e "${YELLOW}[!]${NC} Экспорт не удался. Продолжаем с .pt"
        fi
    fi
fi
echo ""

# ════════════════════════════════════════════════════════
#  Node.js + npm
# ════════════════════════════════════════════════════════
if ! command -v node &>/dev/null; then
    error "Node.js не найден. Установите Node.js 18+ (https://nodejs.org)"
fi
info "Node.js: $(node --version)  npm: $(npm --version)"

warn "npm install (frontend)..."
cd "$SCRIPT_DIR/frontend"

# Если package-lock.json создан под другую платформу — удаляем,
# чтобы npm пересчитал нативные опциональные зависимости (rollup, esbuild и т.д.)
if [ -f "package-lock.json" ]; then
    LOCK_PLATFORM=$(node -e "
        try {
            const l = require('./package-lock.json');
            const p = Object.keys(l.packages || {}).find(k => k.includes('@rollup/rollup-'));
            console.log(p || '');
        } catch(e) { console.log(''); }
    " 2>/dev/null || echo "")
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
        --host 0.0.0.0 --port 8000
fi
