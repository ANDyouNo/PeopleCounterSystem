"""
People Counter System — FastAPI Backend v4.0

Запуск (dev):
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Запуск (prod, обслуживает собранный фронтенд):
    uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.state import AppState
from backend.db.database import Database
from backend.api.routes import settings, control, stats, stream, zones
from backend.api.routes import effects as effects_router

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
DOCS_DIR      = Path(__file__).parent.parent / "docs"


# ─── Lifespan ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте, очистка при остановке."""
    state: AppState = app.state.app

    # ── БД ──
    print("[startup] Инициализация БД...")
    db = Database()
    state.db = db
    state.load_settings(db)
    print(f"[startup] Настройки загружены: {len(state.get_all_settings())} ключей")

    # ── Камера ──
    cam_idx = state.get_setting("camera_index", 0)
    w       = state.get_setting("frame_width", 640)
    h       = state.get_setting("frame_height", 480)
    print(f"[startup] Камера {cam_idx}  ({w}×{h})...")
    cap = cv2.VideoCapture(cam_idx)
    if not cap.isOpened():
        print(f"[startup] ОШИБКА: камера {cam_idx} недоступна. Детекция отключена.")
        cap = None
    else:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        # Один тестовый кадр
        ret, _ = cap.read()
        if not ret:
            print("[startup] ОШИБКА: камера открыта, но кадр не читается.")
            cap.release()
            cap = None
        else:
            print(f"[startup] Камера OK  "
                  f"({int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}×"
                  f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))})")

    # ── ROI Manager ──
    from backend.core.roi_manager import ROIManager
    roi_mgr = ROIManager(config_path="data/exclusion_zones.json")
    roi_mgr.load()
    state.roi_mgr = roi_mgr  # expose for /api/zones
    if roi_mgr.zones and cap is not None:
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        roi_mgr.build_mask(actual_h, actual_w)
        print(f"[startup] Зон исключения: {len(roi_mgr.zones)}")

    # ── Модель ──
    engine = None
    if cap is not None:
        from backend.core.detection_engine import DetectionEngine, load_model
        model_size = state.get_setting("model_size", "n")
        backend_type = state.get_setting("inference_backend", "auto")
        print(f"[startup] Модель YOLOv8{model_size} ({backend_type})...")
        try:
            model = load_model(model_size, backend_type)
            engine = DetectionEngine(cap, model, roi_mgr, db, state)
            state.engine = engine
            engine.start()
            print("[startup] DetectionEngine запущен")
        except Exception as e:
            print(f"[startup] Ошибка загрузки модели: {e}")

    # ── Showcase ESP ──
    if state.get_setting("showcase_esp_enabled", True):
        from backend.core.showcase_controller import ShowcaseController
        showcase = ShowcaseController(state)
        state.showcase = showcase
        showcase.start()
        print("[startup] ShowcaseController запущен")

    # ── Light ESP ──
    if state.get_setting("light_esp_enabled", True):
        from backend.core.light_controller import LightController
        light = LightController(state)
        state.light = light
        light.start()
        print("[startup] LightController запущен")

    # ── Effect Engine ──
    if state.showcase:
        from backend.effects import EffectEngine
        effect_engine = EffectEngine(state.showcase, state)
        app.state.effect_engine = effect_engine
        await effect_engine.start()
        print("[startup] EffectEngine запущен")

    # ── Asyncio loop в AppState ──
    state._loop = asyncio.get_running_loop()

    print("[startup] ✓ Система запущена. http://localhost:8000")
    print("[startup]   Dev frontend: http://localhost:5173")
    print()

    yield  # ← приложение работает

    # ─── Завершение ───────────────────────────────────────────
    print("\n[shutdown] Завершение...")

    effect_engine = getattr(app.state, "effect_engine", None)
    if effect_engine:
        await effect_engine.stop()

    if state.showcase:
        state.showcase.shutdown()
    if state.light:
        state.light.shutdown()
    if engine:
        engine.stop()
        engine.join(timeout=5)
    if cap is not None:
        cap.release()
    if db:
        db.close()

    print("[shutdown] Готово.")


# ─── FastAPI app ───────────────────────────────────────────────

app = FastAPI(
    title="People Counter API",
    version="4.0.0",
    lifespan=lifespan,
)

# Инициализируем AppState заранее (до lifespan)
app.state.app = AppState()

# ── CORS (для Vite dev server) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API роуты ──
app.include_router(stream.router)
app.include_router(settings.router)
app.include_router(control.router)
app.include_router(stats.router)
app.include_router(zones.router)
app.include_router(effects_router.router)


# ── Документация ──
from fastapi.responses import FileResponse as _FR
from fastapi.staticfiles import StaticFiles as _SS

if DOCS_DIR.exists():
    app.mount("/docs", _SS(directory=str(DOCS_DIR), html=False), name="docs")

# ── Статический фронтенд (только если собран) ──
if FRONTEND_DIST.exists():
    from fastapi.responses import FileResponse

    @app.get("/")
    async def serve_index():
        return FileResponse(FRONTEND_DIST / "index.html")

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """SPA fallback: все unknown маршруты → index.html."""
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        from fastapi import HTTPException
        raise HTTPException(404)
else:
    @app.get("/")
    async def dev_root():
        return {
            "status": "running",
            "frontend": "Запустите: cd frontend && npm run dev",
            "api_docs": "http://localhost:8000/docs",
        }
