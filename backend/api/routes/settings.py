"""
API настроек: GET /api/settings, PUT /api/settings.
"""

from fastapi import APIRouter, Request, HTTPException

from backend.state import AppState

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _app(request: Request) -> AppState:
    return request.app.state.app


@router.get("")
async def get_settings(request: Request):
    """Вернуть все настройки с метаданными."""
    app = _app(request)
    return app.db.get_all_settings()


@router.put("")
async def update_settings(request: Request, body: dict):
    """
    Обновить одну или несколько настроек.
    Body: { "key": value, ... }
    """
    app = _app(request)
    updated = app.db.set_settings(body)
    if not updated:
        raise HTTPException(status_code=400, detail="Нет известных ключей для обновления")
    # Применить в памяти (живые настройки обновятся немедленно)
    live_updates = {k: v for k, v in body.items() if k in updated}
    app.update_settings(live_updates)
    return {"updated": updated}
