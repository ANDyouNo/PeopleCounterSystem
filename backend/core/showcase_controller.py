"""
Showcase Controller — управление витринами через ESP8266 + PCA9685.

Адаптация для FastAPI: читает задержки из AppState.get_setting() при каждом вызове,
что позволяет менять их на лету без перезапуска.
"""

import socket
import threading
import time
from typing import Optional, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.state import AppState

SHOWCASE_LISTEN_PORT     = 4211
SHOWCASE_COMMAND_PORT    = 4210
SHOWCASE_ANNOUNCE_PREFIX = "PCOUNTER_SHOW"


class ShowcaseController:
    def __init__(self, app_state: "AppState"):
        self._state = app_state
        self._esp_ip: Optional[str] = None
        self._ip_lock = threading.Lock()
        self._stop    = threading.Event()

        self._forced: set[int] = set()        # 0-based индексы
        self._forced_lock = threading.Lock()

        self._pending_timer: Optional[threading.Timer] = None
        self._pending_lock  = threading.Lock()

        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._listener  = threading.Thread(
            target=self._listen_loop, daemon=True, name="showcase-listener")

    # ── Публичный интерфейс ──────────────────────────────────────

    def start(self):
        self._listener.start()

    def shutdown(self):
        self._cancel_pending()
        count = self._state.get_setting("showcase_count", 8)
        self._send("FOFF:" + ",".join(str(i + 1) for i in range(count)))
        self._send("OFF")
        time.sleep(0.15)
        self.stop()

    def stop(self):
        self._stop.set()
        self._cancel_pending()
        try:
            self._send_sock.close()
        except Exception:
            pass

    @property
    def connected(self) -> bool:
        with self._ip_lock:
            return self._esp_ip is not None

    # ── Авто-режим ───────────────────────────────────────────────

    def set_occupied(self, occupied: bool):
        cmd   = "ON" if occupied else "OFF"
        delay = self._state.get_setting(
            "showcase_delay_on" if occupied else "showcase_delay_off", 0)
        self._cancel_pending()
        if delay and delay > 0:
            t = threading.Timer(delay, self._send, args=(cmd,))
            t.daemon = True
            with self._pending_lock:
                self._pending_timer = t
            t.start()
        else:
            self._send(cmd)

    # ── Принудительное управление ────────────────────────────────

    def force_on(self, showcases: Optional[Iterable[int]] = None):
        """showcases — 1-based номера. None = все."""
        count = self._state.get_setting("showcase_count", 8)
        idxs  = list(range(1, count + 1)) if showcases is None else list(showcases)
        idxs  = [s for s in idxs if 1 <= s <= count]
        if not idxs:
            return
        with self._forced_lock:
            for s in idxs:
                self._forced.add(s - 1)
        self._send("FON:" + ",".join(str(s) for s in idxs))

    def force_off(self, showcases: Optional[Iterable[int]] = None):
        """showcases — 1-based номера. None = все."""
        count = self._state.get_setting("showcase_count", 8)
        if showcases is None:
            with self._forced_lock:
                idxs = [i + 1 for i in self._forced]
                self._forced.clear()
        else:
            idxs = [s for s in showcases if 1 <= s <= count]
            with self._forced_lock:
                for s in idxs:
                    self._forced.discard(s - 1)
        if not idxs:
            return
        self._send("FOFF:" + ",".join(str(s) for s in idxs))

    def toggle_force(self, showcase: int) -> bool:
        """Переключить принудительный режим (1-based). Возвращает новое состояние."""
        with self._forced_lock:
            idx = showcase - 1
            forced = idx not in self._forced
            if forced:
                self._forced.add(idx)
            else:
                self._forced.discard(idx)
        if forced:
            self._send(f"FON:{showcase}")
        else:
            self._send(f"FOFF:{showcase}")
        return forced

    def get_forced(self) -> set[int]:
        """Возвращает множество 1-based номеров принудительно включённых витрин."""
        with self._forced_lock:
            return {i + 1 for i in self._forced}

    def send_map(self, mapping: dict[int, int]):
        if not mapping:
            return
        self._send("MAP:" + ",".join(f"{s}={ch}" for s, ch in mapping.items()))

    # ── Приватные ────────────────────────────────────────────────

    def _cancel_pending(self):
        with self._pending_lock:
            if self._pending_timer is not None:
                self._pending_timer.cancel()
                self._pending_timer = None

    def _send(self, cmd: str):
        with self._ip_lock:
            ip = self._esp_ip
        if ip is None:
            return
        try:
            self._send_sock.sendto(cmd.encode(), (ip, SHOWCASE_COMMAND_PORT))
        except Exception as e:
            print(f"  [SHOW] Ошибка отправки: {e}")

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(("", SHOWCASE_LISTEN_PORT))
        except OSError as e:
            print(f"  [SHOW] Не удалось открыть порт {SHOWCASE_LISTEN_PORT}: {e}")
            return
        while not self._stop.is_set():
            try:
                data, (addr_ip, _) = sock.recvfrom(64)
                msg = data.decode("utf-8", errors="ignore").strip()
                if msg.startswith(SHOWCASE_ANNOUNCE_PREFIX):
                    with self._ip_lock:
                        if self._esp_ip != addr_ip:
                            self._esp_ip = addr_ip
                            print(f"  [SHOW] ESP: {addr_ip}")
            except socket.timeout:
                continue
            except Exception:
                break
        sock.close()
