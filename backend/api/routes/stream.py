"""
MJPEG стрим и WebSocket.
"""

import asyncio
import time
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import StreamingResponse

from backend.state import AppState

router = APIRouter()


def get_state(request: Request) -> AppState:
    return request.app.state.app


# ── Placeholder кадр (камера ещё не готова / недоступна) ──────

def _make_placeholder(text: str = "No signal") -> bytes:
    """Возвращает JPEG-буфер с серым кадром-заглушкой."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = (30, 30, 30)
    font = cv2.FONT_HERSHEY_SIMPLEX
    tw, th = cv2.getTextSize(text, font, 1.0, 2)[0]
    tx = (640 - tw) // 2
    ty = (480 + th) // 2
    cv2.putText(img, text, (tx, ty), font, 1.0, (100, 100, 100), 2)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return buf.tobytes() if ok else b""

_PLACEHOLDER_STARTING  = _make_placeholder("Camera starting…")
_PLACEHOLDER_NO_SIGNAL = _make_placeholder("No signal")


# ── MJPEG стрим ──────────────────────────────────────────────

async def _mjpeg_generator(app_state: AppState):
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"

    # Ждём первый реальный кадр не более 8 секунд,
    # каждую секунду отправляем заглушку чтобы браузер не завис.
    wait_start = time.monotonic()
    while True:
        frame = app_state.engine.get_latest_frame() if app_state.engine else None
        if frame is not None:
            break
        waited = time.monotonic() - wait_start
        if waited >= 8:
            # Камера так и не дала кадр — продолжаем слать заглушку в основном цикле
            break
        # Шлём placeholder раз в секунду пока ждём
        label = _PLACEHOLDER_STARTING if app_state.engine else _PLACEHOLDER_NO_SIGNAL
        yield boundary + label + b"\r\n"
        await asyncio.sleep(1.0)

    # Основной цикл стрима
    no_frame_streak = 0
    while True:
        frame = app_state.engine.get_latest_frame() if app_state.engine else None

        if frame is None:
            no_frame_streak += 1
            # После 2 секунд без кадра — шлём заглушку вместо ожидания
            if no_frame_streak >= 10:
                label = _PLACEHOLDER_NO_SIGNAL
                yield boundary + label + b"\r\n"
                no_frame_streak = 0
            await asyncio.sleep(0.2)
            continue

        no_frame_streak = 0
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            await asyncio.sleep(0.05)
            continue
        yield boundary + buf.tobytes() + b"\r\n"
        await asyncio.sleep(1 / 25)  # ~25 fps для стрима


@router.get("/stream/video")
async def video_stream(request: Request):
    app_state = get_state(request)
    return StreamingResponse(
        _mjpeg_generator(app_state),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── WebSocket ────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    app_state: AppState = websocket.app.state.app
    await app_state.add_ws_client(websocket)

    # Отправить текущее состояние сразу при подключении
    import json
    try:
        await websocket.send_text(json.dumps({
            "type": "state",
            "data": app_state.get_full_state(),
        }))
        # Держим соединение открытым — сервер сам пушит обновления
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Ping-pong чтобы не закрылось по таймауту
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await app_state.remove_ws_client(websocket)
