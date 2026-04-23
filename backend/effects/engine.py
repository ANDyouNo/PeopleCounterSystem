"""EffectEngine — asyncio loop that drives showcase lighting effects.

Responsibilities
----------------
* Runs at ~30 fps regardless of whether effects are enabled.
* When enabled + active effect: executes user's tick() and sends PWM.
* When disabled or no active effect: sends KA (keepalive) at 1 fps so
  the ESP watchdog never fires during normal operation.
* On startup/teardown: sends MODE:direct / MODE:auto to the ESP.
"""

from __future__ import annotations
import asyncio
import time
import traceback
from typing import Optional, TYPE_CHECKING

from .effect_store import EffectStore
from .executor import EffectExecutor, ExecutionError
from .models import EffectContext

if TYPE_CHECKING:
    from backend.core.showcase_controller import ShowcaseController
    from backend.state import AppState

FPS          = 30
KA_INTERVAL  = 1.0   # seconds between keepalive packets in idle mode


class EffectEngine:
    def __init__(self, showcase_ctrl: "ShowcaseController", app_state: "AppState"):
        self._ctrl      = showcase_ctrl
        self._state     = app_state
        self._store     = EffectStore(data_dir="data")

        self._enabled       = False       # effects system on/off
        self._active_id: Optional[str] = None   # currently running effect id
        self._executor: Optional[EffectExecutor] = None

        self._t_start   = 0.0
        self._last_error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    # ── Public store proxy ────────────────────────────────────────

    @property
    def store(self) -> EffectStore:
        return self._store

    # ── State ─────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def active_id(self) -> Optional[str]:
        return self._active_id

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def status(self) -> dict:
        effect = self._store.get(self._active_id) if self._active_id else None
        return {
            "enabled":      self._enabled,
            "active_id":    self._active_id,
            "active_name":  effect.name if effect else None,
            "last_error":   self._last_error,
        }

    # ── Control ───────────────────────────────────────────────────

    async def set_enabled(self, enabled: bool):
        async with self._lock:
            if self._enabled == enabled:
                return
            self._enabled = enabled
            if enabled:
                self._ctrl.enable_direct()
                print("  [Effects] Direct mode ON")
            else:
                self._ctrl.disable_direct()
                self._active_id = None
                self._executor  = None
                print("  [Effects] Direct mode OFF")

    async def activate(self, effect_id: str) -> dict:
        """Compile and activate an effect. Returns status dict."""
        async with self._lock:
            effect = self._store.get(effect_id)
            if effect is None:
                return {"ok": False, "error": "Effect not found"}

            executor = EffectExecutor(effect.code)
            if not executor.ok:
                self._last_error = executor.error
                return {"ok": False, "error": executor.error}

            self._executor  = executor
            self._active_id = effect_id
            self._t_start   = time.monotonic()
            self._last_error = None

            if not self._enabled:
                self._enabled = True
                self._ctrl.enable_direct()

            print(f"  [Effects] Activated: {effect.name!r}")
            return {"ok": True}

    async def deactivate(self):
        """Stop the running effect (keep direct mode on, send zeros)."""
        async with self._lock:
            self._active_id = None
            self._executor  = None
            self._last_error = None

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self):
        self._task = asyncio.create_task(self._loop(), name="effect-engine")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._enabled:
            self._ctrl.disable_direct()

    # ── Main loop ─────────────────────────────────────────────────

    async def _loop(self):
        interval     = 1.0 / FPS
        last_ka_time = 0.0

        while True:
            loop_start = time.monotonic()

            try:
                if self._enabled and self._active_id and self._executor:
                    await self._tick_effect()
                else:
                    # Idle: send keepalive once per KA_INTERVAL
                    now = time.monotonic()
                    if now - last_ka_time >= KA_INTERVAL:
                        self._ctrl.send_keepalive()
                        last_ka_time = now
            except Exception:
                traceback.print_exc()

            elapsed = time.monotonic() - loop_start
            await asyncio.sleep(max(0.0, interval - elapsed))

    async def _tick_effect(self):
        t   = time.monotonic() - self._t_start
        n   = self._state.get_setting("showcase_count", 8)
        ppl = getattr(self._state, "people_now", 0)
        ctx = EffectContext(channel_count=n, people=ppl, fps=FPS)

        try:
            values = self._executor.run(t, ctx)
            self._ctrl.send_pwm(values)
            self._last_error = None
        except ExecutionError as e:
            err = str(e)
            if self._last_error != err:
                self._last_error = err
                print(f"  [Effects] Runtime error:\n{err}")
            # On error send zeros to avoid stuck-on state
            self._ctrl.send_pwm([0.0] * n)
