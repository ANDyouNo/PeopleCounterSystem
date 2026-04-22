"""
AppState — центральное хранилище состояния приложения.

Создаётся один экземпляр при запуске FastAPI (lifespan).
Передаётся в роуты через dependency injection.
Хранит:
  - настройки (dict, читаются из БД, обновляются через API)
  - ссылки на движок детекции и контроллеры ESP
  - текущее состояние детекции (thread-safe)
  - множество подключённых WebSocket клиентов
"""

import asyncio
import json
import threading
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.detection_engine import DetectionEngine
    from backend.core.showcase_controller import ShowcaseController
    from backend.core.light_controller import LightController
    from backend.db.database import Database


class AppState:
    def __init__(self):
        # ── Компоненты (инициализируются в lifespan) ──
        self.db: Optional["Database"] = None
        self.engine: Optional["DetectionEngine"] = None
        self.showcase: Optional["ShowcaseController"] = None
        self.light: Optional["LightController"] = None

        # ── Настройки (загружаются из БД при старте) ──
        self._settings: dict = {}
        self._settings_lock = threading.Lock()

        # ── Состояние детекции (обновляется из потока движка) ──
        self._detection_state: dict = {
            "people_now": 0,
            "fps": 0.0,
            "inference_ms": 0.0,
            "total_unique": 0,
            "today_visits": 0,
            "today_minutes": 0.0,
            "max_people_today": 0,
        }
        self._state_lock = threading.Lock()

        # ── WebSocket клиенты ──
        self._ws_clients: set = set()
        self._ws_lock = asyncio.Lock()

        # ── Предыдущее состояние занятости (для трекинга изменений) ──
        self._prev_occupied = False

        # ── Asyncio loop (устанавливается при старте) ──
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Настройки ────────────────────────────────────────────────

    def load_settings(self, db: "Database"):
        with self._settings_lock:
            self._settings = db.get_settings_values()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._settings_lock:
            return self._settings.get(key, default)

    def get_all_settings(self) -> dict:
        with self._settings_lock:
            return dict(self._settings)

    def update_settings(self, updates: dict):
        """Обновить настройки в памяти (после записи в БД)."""
        with self._settings_lock:
            self._settings.update(updates)
        # Применить те настройки, что работают на лету
        self._apply_live_settings(updates)

    def _apply_live_settings(self, updates: dict):
        """Применить изменения настроек к работающим компонентам."""
        # Контроллеры читают задержки из self._settings при каждом вызове set_occupied(),
        # поэтому ничего дополнительного не нужно — они уже используют актуальные значения.
        pass

    # ── Состояние детекции ───────────────────────────────────────

    def update_detection_state(self, **kwargs):
        """Вызывается из потока DetectionEngine."""
        with self._state_lock:
            self._detection_state.update(kwargs)
        # Сообщаем asyncio-loop о новом состоянии (thread-safe)
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._broadcast_state(), self._loop
            )

    def get_detection_state(self) -> dict:
        with self._state_lock:
            return dict(self._detection_state)

    # ── Полное состояние для API/WS ──────────────────────────────

    def get_full_state(self) -> dict:
        state = self.get_detection_state()
        state["showcase_connected"] = (
            self.showcase.connected if self.showcase else False)
        state["light_connected"] = (
            self.light.connected if self.light else False)
        state["showcase_forced"] = (
            sorted(self.showcase.get_forced()) if self.showcase else [])
        state["light_forced"] = (
            self.light.is_forced if self.light else False)
        return state

    # ── WebSocket ────────────────────────────────────────────────

    async def add_ws_client(self, ws):
        async with self._ws_lock:
            self._ws_clients.add(ws)

    async def remove_ws_client(self, ws):
        async with self._ws_lock:
            self._ws_clients.discard(ws)

    async def _broadcast_state(self):
        """Разослать текущее состояние всем WebSocket клиентам."""
        if not self._ws_clients:
            return
        message = json.dumps({
            "type": "state",
            "data": self.get_full_state(),
        })
        dead = set()
        async with self._ws_lock:
            clients = set(self._ws_clients)
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        if dead:
            async with self._ws_lock:
                self._ws_clients -= dead

    async def broadcast_log(self, message: str, level: str = "info"):
        """Разослать лог-сообщение всем WebSocket клиентам."""
        if not self._ws_clients:
            return
        payload = json.dumps({
            "type": "log",
            "data": {"message": message, "level": level},
        })
        async with self._ws_lock:
            clients = set(self._ws_clients)
        dead = set()
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        if dead:
            async with self._ws_lock:
                self._ws_clients -= dead

    # ── Трекинг смены занятости ─────────────────────────────────

    def check_occupancy_change(self, people_now: int):
        """Вызывается из потока DetectionEngine при каждом обновлении."""
        occupied = people_now > 0
        if occupied == self._prev_occupied:
            return
        self._prev_occupied = occupied

        if self.showcase:
            self.showcase.set_occupied(occupied)
        if self.light:
            self.light.set_occupied(occupied)
