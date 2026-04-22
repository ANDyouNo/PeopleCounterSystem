"""
Light Controller — управление общим светом через ESP8266 + реле.

Протокол UDP:
  ESP → PC : broadcast "PCOUNTER_LIGHT" → порт LIGHT_LISTEN_PORT  (анонс)
  PC → ESP : команды на порт LIGHT_COMMAND_PORT:
               ON     — авто-включение (от камеры через offset-задержку)
               OFF    — авто-выключение
               FON    — принудительно включить
               FOFF   — снять принуждение

Логика включения:
  1. Камера фиксирует людей → ShowcaseController получает ON.
  2. Через LIGHT_DELAY_AFTER_SHOWCASES секунд LightController получает ON.
  3. Камера больше не видит людей → ShowcaseController получает OFF,
     LightController получает OFF (с задержкой LIGHT_DELAY_OFF, если задана).

Принудительный режим:
  - force_on()  — свет горит независимо от камеры.
  - force_off() — снять принуждение; если авто выключен — свет гаснет.
"""

import socket
import threading
import time
from typing import Optional

from config import (
    LIGHT_LISTEN_PORT,
    LIGHT_COMMAND_PORT,
    LIGHT_ANNOUNCE_PREFIX,
    LIGHT_DELAY_AFTER_SHOWCASES,
    LIGHT_DELAY_OFF,
)


class LightController:
    """
    Находит Light ESP в сети и управляет реле общего освещения.
    Поддерживает авто-режим (с задержкой после витрин) и принудительный.
    """

    def __init__(self):
        self._esp_ip: Optional[str] = None
        self._ip_lock = threading.Lock()
        self._stop    = threading.Event()

        self._forced = False
        self._state_lock = threading.Lock()

        # Таймеры отложенных команд
        self._on_timer:  Optional[threading.Timer] = None
        self._off_timer: Optional[threading.Timer] = None
        self._timer_lock = threading.Lock()

        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self._listener = threading.Thread(
            target=self._listen_loop, daemon=True, name="light-listener")

    # ── Публичный интерфейс ──────────────────────────────────────

    def start(self):
        self._listener.start()
        print(f"  [LIGHT] Ожидание Light ESP "
              f"(broadcast → порт {LIGHT_LISTEN_PORT})...")

    def shutdown(self):
        """
        Корректное завершение: снять принуждение и выключить свет,
        затем остановить потоки. Вызывать вместо stop() при выходе из программы.
        """
        print("  [LIGHT] Выключение света перед завершением...")
        self._cancel_all_timers()
        self._send("FOFF")
        self._send("OFF")
        time.sleep(0.1)   # Небольшая пауза, чтобы пакеты успели уйти
        self.stop()

    def stop(self):
        self._stop.set()
        self._cancel_all_timers()
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
        """
        Вызывается синхронно с ShowcaseController.set_occupied().
        occupied=True  → через LIGHT_DELAY_AFTER_SHOWCASES сек отправить ON
        occupied=False → отменить ожидающее включение; через LIGHT_DELAY_OFF — OFF
        """
        if occupied:
            self._cancel_off_timer()
            delay = LIGHT_DELAY_AFTER_SHOWCASES
            if delay > 0:
                print(f"  [LIGHT] Команда 'ON' через {delay} с (offset после витрин)")
                t = threading.Timer(delay, self._send, args=("ON",))
                t.daemon = True
                with self._timer_lock:
                    self._on_timer = t
                t.start()
            else:
                self._send("ON")
        else:
            self._cancel_on_timer()
            delay = LIGHT_DELAY_OFF
            if delay > 0:
                print(f"  [LIGHT] Команда 'OFF' через {delay} с")
                t = threading.Timer(delay, self._send, args=("OFF",))
                t.daemon = True
                with self._timer_lock:
                    self._off_timer = t
                t.start()
            else:
                self._send("OFF")

    # ── Принудительное управление ────────────────────────────────

    def force_on(self):
        """Принудительно включить свет (независимо от камеры)."""
        with self._state_lock:
            self._forced = True
        self._cancel_all_timers()
        self._send("FON")
        print("  [LIGHT] ПРИНУДИТЕЛЬНО ВКЛ")

    def force_off(self):
        """Снять принудительное включение. Если авто выключен — свет гаснет."""
        with self._state_lock:
            self._forced = False
        self._send("FOFF")
        print("  [LIGHT] Принуждение снято")

    def toggle_force(self) -> bool:
        """Переключить принудительный режим. Возвращает новое состояние."""
        with self._state_lock:
            new_state = not self._forced
        if new_state:
            self.force_on()
        else:
            self.force_off()
        return new_state

    # ── Приватные методы ─────────────────────────────────────────

    def _cancel_on_timer(self):
        with self._timer_lock:
            if self._on_timer is not None:
                self._on_timer.cancel()
                self._on_timer = None

    def _cancel_off_timer(self):
        with self._timer_lock:
            if self._off_timer is not None:
                self._off_timer.cancel()
                self._off_timer = None

    def _cancel_all_timers(self):
        self._cancel_on_timer()
        self._cancel_off_timer()

    def _send(self, cmd: str):
        with self._ip_lock:
            ip = self._esp_ip
        if ip is None:
            print(f"  [LIGHT] Команда '{cmd}' не отправлена — ESP не обнаружен")
            return
        try:
            self._send_sock.sendto(cmd.encode(), (ip, LIGHT_COMMAND_PORT))
            label = {"ON": "ВКЛ", "OFF": "ВЫКЛ", "FON": "ПРИНУДИТЕЛЬНО ВКЛ",
                     "FOFF": "снято принуждение"}.get(cmd, cmd)
            print(f"  [LIGHT] → {label}  ({ip}:{LIGHT_COMMAND_PORT})")
        except Exception as e:
            print(f"  [LIGHT] Ошибка отправки: {e}")

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('', LIGHT_LISTEN_PORT))
        except OSError as e:
            print(f"  [LIGHT] Не удалось открыть порт {LIGHT_LISTEN_PORT}: {e}")
            return

        while not self._stop.is_set():
            try:
                data, (addr_ip, _) = sock.recvfrom(64)
                msg = data.decode('utf-8', errors='ignore').strip()
                if msg.startswith(LIGHT_ANNOUNCE_PREFIX):
                    with self._ip_lock:
                        if self._esp_ip != addr_ip:
                            self._esp_ip = addr_ip
                            print(f"  [LIGHT] ESP обнаружен: {addr_ip}")
            except socket.timeout:
                continue
            except Exception:
                break
        sock.close()
