"""
Showcase Controller — управление витринами через ESP8266 + PCA9685.

Протокол UDP:
  ESP → PC : broadcast "PCOUNTER_SHOW" → порт SHOWCASE_LISTEN_PORT  (анонс)
  PC → ESP : команды на порт SHOWCASE_COMMAND_PORT:
               ON            — авто-включение (камера)
               OFF           — авто-выключение (камера)
               FON:1,3,5     — принудительно включить витрины 1,3,5
               FOFF:1,3,5    — снять принуждение с витрин 1,3,5
               MAP:1=0,2=3   — переназначить каналы PCA9685

Режимы:
  - Авто: camera.set_occupied(True/False) управляет витринами с задержками.
  - Принудительный: force_on()/force_off() включают/выключают конкретные
    витрины независимо от состояния камеры.
    Принудительно включённые витрины не гасятся командой OFF.
"""

import socket
import threading
import time
from typing import Optional, Iterable

from config import (
    SHOWCASE_LISTEN_PORT,
    SHOWCASE_COMMAND_PORT,
    SHOWCASE_ANNOUNCE_PREFIX,
    SHOWCASE_DELAY_ON,
    SHOWCASE_DELAY_OFF,
    SHOWCASE_COUNT,
)


class ShowcaseController:
    """
    Находит Showcase ESP в сети и отправляет ему команды управления витринами.

    Состояние принудительного включения хранится на стороне Python (set),
    чтобы main.py мог отображать его в терминале без запроса к ESP.
    """

    def __init__(self):
        self._esp_ip: Optional[str] = None
        self._ip_lock = threading.Lock()
        self._stop    = threading.Event()

        # Принудительно включённые витрины (0-based индексы)
        self._forced: set[int] = set()
        self._forced_lock = threading.Lock()

        # Отложенные авто-команды
        self._pending_timer: Optional[threading.Timer] = None
        self._pending_lock  = threading.Lock()

        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self._listener = threading.Thread(
            target=self._listen_loop, daemon=True, name="showcase-listener")

    # ── Публичный интерфейс ──────────────────────────────────────

    def start(self):
        self._listener.start()
        print(f"  [SHOW] Ожидание Showcase ESP "
              f"(broadcast → порт {SHOWCASE_LISTEN_PORT})...")

    def shutdown(self):
        """
        Корректное завершение: снять принуждение и выключить все витрины,
        затем остановить потоки. Вызывать вместо stop() при выходе из программы.
        """
        print("  [SHOW] Выключение витрин перед завершением...")
        self._cancel_pending()
        # Снимаем принудительный режим и гасим всё
        self._send("FOFF:" + ",".join(str(i+1) for i in range(SHOWCASE_COUNT)))
        self._send("OFF")
        time.sleep(0.1)   # Небольшая пауза, чтобы пакеты успели уйти
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

    # ── Авто-режим (вызывается из main.py при смене состояния зала) ──

    def set_occupied(self, occupied: bool):
        """
        occupied=True  → через SHOWCASE_DELAY_ON  сек отправить ON
        occupied=False → через SHOWCASE_DELAY_OFF сек отправить OFF
        При смене состояния пока идёт задержка — предыдущая команда отменяется.
        """
        cmd   = "ON" if occupied else "OFF"
        delay = SHOWCASE_DELAY_ON if occupied else SHOWCASE_DELAY_OFF
        self._cancel_pending()

        if delay > 0:
            print(f"  [SHOW] Команда '{cmd}' через {delay} с")
            t = threading.Timer(delay, self._send, args=(cmd,))
            t.daemon = True
            with self._pending_lock:
                self._pending_timer = t
            t.start()
        else:
            self._send(cmd)

    # ── Принудительное управление ────────────────────────────────

    def force_on(self, showcases: Optional[Iterable[int]] = None):
        """
        Принудительно включить витрины.
        showcases — список 1-based номеров (1..SHOWCASE_COUNT).
        None или пустой список → ВСЕ витрины.
        """
        if showcases is None:
            idxs = list(range(1, SHOWCASE_COUNT + 1))  # 1-based
        else:
            idxs = [s for s in showcases if 1 <= s <= SHOWCASE_COUNT]

        if not idxs:
            return

        with self._forced_lock:
            for s in idxs:
                self._forced.add(s - 1)   # храним 0-based

        arg = ",".join(str(s) for s in idxs)
        self._send(f"FON:{arg}")
        print(f"  [SHOW] ПРИНУДИТЕЛЬНО ВКЛ витрины: {idxs}")

    def force_off(self, showcases: Optional[Iterable[int]] = None):
        """
        Снять принудительное включение.
        showcases — список 1-based номеров.
        None или пустой список → снять со ВСЕХ витрин.
        """
        if showcases is None:
            with self._forced_lock:
                idxs = [i + 1 for i in self._forced]  # 1-based
                self._forced.clear()
        else:
            idxs = [s for s in showcases if 1 <= s <= SHOWCASE_COUNT]
            with self._forced_lock:
                for s in idxs:
                    self._forced.discard(s - 1)

        if not idxs:
            return

        arg = ",".join(str(s) for s in idxs)
        self._send(f"FOFF:{arg}")
        print(f"  [SHOW] Снято принуждение витрин: {idxs}")

    def get_forced(self) -> set[int]:
        """Возвращает множество 1-based номеров принудительно включённых витрин."""
        with self._forced_lock:
            return {i + 1 for i in self._forced}

    def toggle_force(self, showcase: int) -> bool:
        """
        Переключить принудительный режим витрины (1-based).
        Возвращает новое состояние: True = принудительно включена.
        """
        with self._forced_lock:
            idx = showcase - 1
            if idx in self._forced:
                self._forced.discard(idx)
                forced = False
            else:
                self._forced.add(idx)
                forced = True

        if forced:
            self._send(f"FON:{showcase}")
            print(f"  [SHOW] Витрина {showcase} → ПРИНУДИТЕЛЬНО ВКЛ")
        else:
            self._send(f"FOFF:{showcase}")
            print(f"  [SHOW] Витрина {showcase} → принуждение снято")
        return forced

    def send_map(self, mapping: dict[int, int]):
        """
        Переназначить каналы PCA9685.
        mapping: {showcase_1based: pca_channel_0based, ...}
        Пример: {1: 3, 2: 0} — витрина 1 → канал 3, витрина 2 → канал 0
        """
        if not mapping:
            return
        arg = ",".join(f"{s}={ch}" for s, ch in mapping.items())
        self._send(f"MAP:{arg}")
        print(f"  [SHOW] MAP: {mapping}")

    # ── Приватные методы ─────────────────────────────────────────

    def _cancel_pending(self):
        with self._pending_lock:
            if self._pending_timer is not None:
                self._pending_timer.cancel()
                self._pending_timer = None

    def _send(self, cmd: str):
        with self._ip_lock:
            ip = self._esp_ip
        if ip is None:
            print(f"  [SHOW] Команда '{cmd}' не отправлена — ESP не обнаружен")
            return
        try:
            self._send_sock.sendto(cmd.encode(), (ip, SHOWCASE_COMMAND_PORT))
            print(f"  [SHOW] → '{cmd}'  ({ip}:{SHOWCASE_COMMAND_PORT})")
        except Exception as e:
            print(f"  [SHOW] Ошибка отправки: {e}")

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('', SHOWCASE_LISTEN_PORT))
        except OSError as e:
            print(f"  [SHOW] Не удалось открыть порт {SHOWCASE_LISTEN_PORT}: {e}")
            return

        while not self._stop.is_set():
            try:
                data, (addr_ip, _) = sock.recvfrom(64)
                msg = data.decode('utf-8', errors='ignore').strip()
                if msg.startswith(SHOWCASE_ANNOUNCE_PREFIX):
                    with self._ip_lock:
                        if self._esp_ip != addr_ip:
                            self._esp_ip = addr_ip
                            print(f"  [SHOW] ESP обнаружен: {addr_ip}")
            except socket.timeout:
                continue
            except Exception:
                break
        sock.close()
