"""UDP-контроллер оповещателя посетителей на ESP32-C3.

ESP анонсирует себя строкой ``PCOUNTER_NOTIFIER:<millivolts>`` на UDP-порт
4215. Сервер отвечает на порт 4214 командами состояния и раз в секунду
отправляет ``KA``. Отсутствие ``KA`` намеренно распознаётся самой ESP как
потеря связи с программой ПК.
"""

import socket
import threading
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.state import AppState


NOTIFIER_LISTEN_PORT = 4215
NOTIFIER_COMMAND_PORT = 4214
NOTIFIER_ANNOUNCE_PREFIX = "PCOUNTER_NOTIFIER"
HEARTBEAT_INTERVAL = 1.0
OFFLINE_AFTER = 15.0


class NotifierController:
    """Обнаруживает ESP32-C3, передаёт состояние помещения и heartbeat."""

    def __init__(self, app_state: "AppState"):
        self._state = app_state
        self._esp_ip: Optional[str] = None
        self._battery_mv: Optional[int] = None
        self._last_seen = 0.0
        self._occupied = False
        self._occupancy_generation = 0
        self._lock = threading.Lock()
        self._off_timer: Optional[threading.Timer] = None
        self._timer_lock = threading.Lock()
        self._stop = threading.Event()
        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._listener = threading.Thread(
            target=self._listen_loop, daemon=True, name="notifier-listener")

    def start(self):
        self._listener.start()

    def shutdown(self):
        # Сбрасываем индикатор людей. После остановки heartbeat ESP корректно
        # перейдёт в режим предупреждения о потере соединения с ПК.
        self._cancel_off_timer()
        self._send("STATE:0:0")
        self.stop()

    def stop(self):
        self._stop.set()
        self._cancel_off_timer()
        try:
            self._send_sock.close()
        except OSError:
            pass

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._esp_ip is not None and time.monotonic() - self._last_seen < OFFLINE_AFTER

    @property
    def battery_mv(self) -> Optional[int]:
        with self._lock:
            return self._battery_mv

    @property
    def battery_low(self) -> bool:
        # ~19 % для Li-ion 1S при линейной шкале 3.0…4.2 В в прошивке.
        with self._lock:
            return self._battery_mv is not None and self._battery_mv < 3230

    def set_occupied(self, occupied: bool):
        """Передать состояние с задержкой выключения при потере детекции."""
        with self._lock:
            self._occupancy_generation += 1
            generation = self._occupancy_generation

        if not occupied:
            delay = self._state.get_setting("notifier_delay_off", 10)
            self._cancel_off_timer()
            if delay and delay > 0:
                timer = threading.Timer(delay, self._apply_empty, args=(generation,))
                timer.daemon = True
                with self._timer_lock:
                    self._off_timer = timer
                timer.start()
            else:
                self._apply_empty(generation)
            return

        self._cancel_off_timer()
        with self._lock:
            changed_to_occupied = occupied and not self._occupied
            self._occupied = occupied
        # Третий параметр — флаг звукового оповещения. Повторная синхронизация
        # при подключении ESP использует 0, поэтому не создаёт ложный сигнал.
        self._send(f"STATE:{1 if occupied else 0}:{1 if changed_to_occupied else 0}")

    def _apply_empty(self, generation: int):
        """Выключить LED людей, только если после запуска таймера не было людей."""
        with self._lock:
            if generation != self._occupancy_generation:
                return
            self._occupied = False
        with self._timer_lock:
            self._off_timer = None
        self._send("STATE:0:0")

    def _cancel_off_timer(self):
        with self._timer_lock:
            if self._off_timer is not None:
                self._off_timer.cancel()
                self._off_timer = None

    def _send(self, cmd: str):
        with self._lock:
            ip = self._esp_ip
        if not ip:
            return
        try:
            self._send_sock.sendto(cmd.encode("ascii"), (ip, NOTIFIER_COMMAND_PORT))
        except OSError as e:
            if not self._stop.is_set():
                print(f"  [NOTIFIER] Ошибка отправки: {e}")

    def _handle_announce(self, msg: str, addr_ip: str):
        battery_mv: Optional[int] = None
        parts = msg.split(":", 1)
        if len(parts) == 2:
            try:
                battery_mv = max(0, int(parts[1]))
            except ValueError:
                pass

        was_connected = self.connected
        with self._lock:
            changed = self._esp_ip != addr_ip or self._battery_mv != battery_mv
            self._esp_ip = addr_ip
            self._battery_mv = battery_mv
            self._last_seen = time.monotonic()
            occupied = self._occupied

        if not was_connected:
            print(f"  [NOTIFIER] ESP32-C3: {addr_ip}")
            changed = True

        # Сразу синхронизируем LED "люди" без звука и подтверждаем, что ПК жив.
        self._send(f"STATE:{1 if occupied else 0}:0")
        self._send("KA")
        if changed:
            self._state.request_state_broadcast()

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        try:
            sock.bind(("", NOTIFIER_LISTEN_PORT))
        except OSError as e:
            print(f"  [NOTIFIER] Не удалось открыть порт {NOTIFIER_LISTEN_PORT}: {e}")
            return

        next_heartbeat = time.monotonic()
        reported_connected = False
        while not self._stop.is_set():
            try:
                data, (addr_ip, _) = sock.recvfrom(128)
                msg = data.decode("utf-8", errors="ignore").strip()
                if msg.startswith(NOTIFIER_ANNOUNCE_PREFIX):
                    self._handle_announce(msg, addr_ip)
            except socket.timeout:
                pass
            except OSError:
                break

            now = time.monotonic()
            is_connected = self.connected
            if is_connected and now >= next_heartbeat:
                self._send("KA")
                next_heartbeat = now + HEARTBEAT_INTERVAL
            if is_connected != reported_connected:
                reported_connected = is_connected
                self._state.request_state_broadcast()

        sock.close()
