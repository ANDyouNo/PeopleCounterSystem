"""REST API for the Effects system.

Endpoints
---------
GET    /api/effects              — list all effects
POST   /api/effects              — create a new effect
GET    /api/effects/status       — engine status (enabled, active_id, error)
PUT    /api/effects/enabled      — enable / disable effects system
POST   /api/effects/{id}/activate — activate an effect
POST   /api/effects/deactivate   — stop current effect
GET    /api/effects/{id}         — get one effect
PUT    /api/effects/{id}         — update effect (name/code/description)
DELETE /api/effects/{id}         — delete effect
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/effects", tags=["effects"])


# ── Schemas ───────────────────────────────────────────────────────

class EffectCreate(BaseModel):
    name: str
    code: str
    description: str = ""

class EffectUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None

class EnabledPayload(BaseModel):
    enabled: bool


# ── Helpers ───────────────────────────────────────────────────────

def _engine(request: Request):
    engine = getattr(request.app.state, "effect_engine", None)
    if engine is None:
        raise HTTPException(503, "Effect engine not initialised")
    return engine


# ── Routes ────────────────────────────────────────────────────────

@router.get("")
def list_effects(request: Request):
    engine = _engine(request)
    return [e.to_dict() for e in engine.store.all()]


@router.post("", status_code=201)
def create_effect(payload: EffectCreate, request: Request):
    engine = _engine(request)
    effect = engine.store.create(
        name=payload.name,
        code=payload.code,
        description=payload.description,
    )
    return effect.to_dict()


@router.get("/status")
def get_status(request: Request):
    return _engine(request).status()


@router.put("/enabled")
async def set_enabled(payload: EnabledPayload, request: Request):
    engine = _engine(request)
    await engine.set_enabled(payload.enabled)
    return engine.status()


@router.post("/deactivate")
async def deactivate(request: Request):
    await _engine(request).deactivate()
    return {"ok": True}


@router.get("/{effect_id}")
def get_effect(effect_id: str, request: Request):
    engine = _engine(request)
    effect = engine.store.get(effect_id)
    if effect is None:
        raise HTTPException(404, "Effect not found")
    return effect.to_dict()


@router.put("/{effect_id}")
def update_effect(effect_id: str, payload: EffectUpdate, request: Request):
    engine = _engine(request)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    effect = engine.store.update(effect_id, **updates)
    if effect is None:
        raise HTTPException(404, "Effect not found")
    return effect.to_dict()


@router.delete("/{effect_id}", status_code=204)
async def delete_effect(effect_id: str, request: Request):
    engine = _engine(request)
    # Deactivate if this was the running effect
    if engine.active_id == effect_id:
        await engine.deactivate()
    if not engine.store.delete(effect_id):
        raise HTTPException(404, "Effect not found")


@router.post("/{effect_id}/activate")
async def activate_effect(effect_id: str, request: Request):
    engine = _engine(request)
    result = await engine.activate(effect_id)
    if not result["ok"]:
        raise HTTPException(400, result.get("error", "Activation failed"))
    return engine.status()
