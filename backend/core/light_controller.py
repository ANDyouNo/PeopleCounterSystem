"""
Light Controller — управление общим светом через ESP8266 + реле.
Адаптация для FastAPI: читает задержки из AppState.get_setting() при каждом вызове.
"""

import socket
import threading
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.state import AppState

LIGHT_LISTEN_PORT     = 4213
LIGHT_COMMAND_PORT    = 4212
LIGHT_ANNOUNCE_PREFIX = "PCOUNTER_LIGHT"


class LightController:
    def __init__(self, app_state: "AppState"):
        self._state = app_state
        self._esp_ip: Optional[str] = None
        self._ip_lock = threading.Lock()
        self._stop    = threading.Event()

        self._forced = False
        self._state_lock = threading.Lock()

        self._on_timer:  Optional[threading.Timer] = None
        self._off_timer: Optional[threading.Timer] = None
        self._timer_lock = threading.Lock()

        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._listener  = threading.Thread(
            target=self._listen_loop, daemon=True, name="light-listener")

    # ── Публичный интерфейс ──────────────────────────────────────

    def start(self):
        self._listener.start()

    def shutdown(self):
        self._cancel_all()
        self._send("FOFF")
        self._send("OFF")
        time.sleep(0.15)
        self.stop()

    def stop(self):
        self._stop.set()
        self._cancel_all()
        try:
            self._send_sock.close()
        except Exception:
            pass

    @property
    def connected(self) -> bool:
        with self._ip_lock:
            return self._esp_ip is not None

    @property
    def is_forced(self) -> bool:
        with self._state_lock:
            return self._forced

    # ── Авто-режим ───────────────────────────────────────────────

    def set_occupied(self, occupied: bool):
        if occupied:
            self._cancel_off()
            delay = self._state.get_setting("light_delay_after_showcases", 5)
            if delay and delay > 0:
                t = threading.Timer(delay, self._send, args=("ON",))
                t.daemon = True
                with self._timer_lock:
                    self._on_timer = t
                t.start()
            else:
                self._send("ON")
        else:
            self._cancel_on()
            delay = self._state.get_setting("light_delay_off", 0)
            if delay and delay > 0:
                t = threading.Timer(delay, self._send, args=("OFF",))
                t.daemon = True
                with self._timer_lock:
                    self._off_timer = t
                t.start()
            else:
                self._send("OFF")

    # ── Принудительное управление ────────────────────────────────

    def force_on(self):
        with self._state_lock:
            self._forced = True
        self._cancel_all()
        self._send("FON")

    def force_off(self):
        with self._state_lock:
            self._forced = False
        self._send("FOFF")

    def toggle_force(self) -> bool:
        with self._state_lock:
            new = not self._forced
        if new:
            self.force_on()
        else:
            self.force_off()
        return new

    # ── Приватные ────────────────────────────────────────────────

    def _cancel_on(self):
        with self._timer_lock:
            if self._on_timer:
                self._on_timer.cancel()
                self._on_timer = None

    def _cancel_off(self):
        with self._timer_lock:
            if self._off_timer:
                self._off_timer.cancel()
                self._off_timer = None

    def _cancel_all(self):
        self._cancel_on()
        self._cancel_off()

    def _send(self, cmd: str):
        with self._ip_lock:
            ip = self._esp_ip
        if ip is None:
            return
        try:
            self._send_sock.sendto(cmd.encode(), (ip, LIGHT_COMMAND_PORT))
        except Exception as e:
            print(f"  [LIGHT] Ошибка отправки: {e}")

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(("", LIGHT_LISTEN_PORT))
        except OSError as e:
            print(f"  [LIGHT] Не удалось открыть порт {LIGHT_LISTEN_PORT}: {e}")
            return
        while not self._stop.is_set():
            try:
                data, (addr_ip, _) = sock.recvfrom(64)
                msg = data.decode("utf-8", errors="ignore").strip()
                if msg.startswith(LIGHT_ANNOUNCE_PREFIX):
                    with self._ip_lock:
                        if self._esp_ip != addr_ip:
                            self._esp_ip = addr_ip
                            print(f"  [LIGHT] ESP: {addr_ip}")
            except socket.timeout:
                continue
            except Exception:
                break
        sock.close()
