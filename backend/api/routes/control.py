"""
API управления витринами и общим светом.
"""

from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from backend.state import AppState

router = APIRouter(prefix="/api/control", tags=["control"])


def _app(request: Request) -> AppState:
    return request.app.state.app


# ── Schemas ──────────────────────────────────────────────────

class ShowcaseIds(BaseModel):
    ids: Optional[list[int]] = None  # 1-based, None = все


# ── State ───────────────────────────────────────────────────

@router.get("/state")
async def get_state(request: Request):
    """Текущее полное состояние системы."""
    return _app(request).get_full_state()


# ── Showcases ────────────────────────────────────────────────

@router.post("/showcases/force_on")
async def showcase_force_on(request: Request, body: ShowcaseIds):
    app = _app(request)
    if not app.showcase:
        raise HTTPException(503, "Showcase ESP не включён")
    app.showcase.force_on(body.ids)
    return {"forced": sorted(app.showcase.get_forced())}


@router.post("/showcases/force_off")
async def showcase_force_off(request: Request, body: ShowcaseIds):
    app = _app(request)
    if not app.showcase:
        raise HTTPException(503, "Showcase ESP не включён")
    app.showcase.force_off(body.ids)
    return {"forced": sorted(app.showcase.get_forced())}


@router.post("/showcases/{showcase_id}/toggle")
async def showcase_toggle(request: Request, showcase_id: int):
    app = _app(request)
    if not app.showcase:
        raise HTTPException(503, "Showcase ESP не включён")
    count = app.get_setting("showcase_count", 8)
    if showcase_id < 1 or showcase_id > count:
        raise HTTPException(400, f"showcase_id должен быть от 1 до {count}")
    forced = app.showcase.toggle_force(showcase_id)
    return {"id": showcase_id, "forced": forced,
            "all_forced": sorted(app.showcase.get_forced())}


# ── Light ────────────────────────────────────────────────────

@router.post("/light/force_on")
async def light_force_on(request: Request):
    app = _app(request)
    if not app.light:
        raise HTTPException(503, "Light ESP не включён")
    app.light.force_on()
    return {"forced": True}


@router.post("/light/force_off")
async def light_force_off(request: Request):
    app = _app(request)
    if not app.light:
        raise HTTPException(503, "Light ESP не включён")
    app.light.force_off()
    return {"forced": False}


@router.post("/light/toggle")
async def light_toggle(request: Request):
    app = _app(request)
    if not app.light:
        raise HTTPException(503, "Light ESP не включён")
    forced = app.light.toggle_force()
    return {"forced": forced}
