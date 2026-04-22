"""
API управления зонами исключения (ROI).

GET  /api/zones           — получить список зон
PUT  /api/zones           — сохранить зоны (перезаписывает всё)
GET  /api/zones/snapshot  — один кадр с камеры (JPEG) для отображения в редакторе
"""

import cv2
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List

from backend.state import AppState

router = APIRouter(prefix="/api/zones", tags=["zones"])


def _app(request: Request) -> AppState:
    return request.app.state.app


# ── Schemas ──────────────────────────────────────────────────

class ZoneIn(BaseModel):
    name: str
    pt1: List[int]   # [x1, y1]
    pt2: List[int]   # [x2, y2]
    enabled: bool = True


class ZonesPayload(BaseModel):
    zones: List[ZoneIn]


# ── Endpoints ────────────────────────────────────────────────

@router.get("")
async def get_zones(request: Request):
    """Текущие зоны исключения."""
    app = _app(request)
    roi = getattr(app, "roi_mgr", None)
    if roi is None:
        return {"zones": []}
    return {"zones": [z.to_dict() for z in roi.zones]}


@router.put("")
async def save_zones(request: Request, payload: ZonesPayload):
    """Сохранить зоны (полная замена списка)."""
    from backend.core.roi_manager import ExclusionZone, ROIManager

    app = _app(request)
    roi = getattr(app, "roi_mgr", None)
    if roi is None:
        raise HTTPException(503, "ROIManager не инициализирован")

    # Пересобираем список зон
    roi.zones = [
        ExclusionZone(
            name=z.name,
            pt1=tuple(z.pt1),
            pt2=tuple(z.pt2),
            enabled=z.enabled,
        )
        for z in payload.zones
    ]
    roi.save()

    # Перестраиваем маску, если движок работает
    engine = getattr(app, "engine", None)
    if engine is not None:
        frame = engine.get_latest_frame()
        if frame is not None:
            h, w = frame.shape[:2]
            roi.build_mask(h, w)

    return {"saved": len(roi.zones)}


@router.get("/snapshot")
async def get_snapshot(request: Request):
    """Один JPEG-кадр с камеры (без детекций и зон) для редактора."""
    app = _app(request)
    engine = getattr(app, "engine", None)

    frame = None
    if engine is not None:
        frame = engine.get_latest_frame()

    if frame is None:
        # Если камера недоступна — возвращаем серый placeholder 640x480
        import numpy as np
        frame = (
            __import__("numpy").zeros((480, 640, 3), dtype=__import__("numpy").uint8) + 60
        )
        cv2.putText(
            frame,
            "Camera unavailable",
            (180, 250),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (180, 180, 180),
            2,
        )

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(500, "Не удалось закодировать кадр")

    return Response(content=buf.tobytes(), media_type="image/jpeg")
