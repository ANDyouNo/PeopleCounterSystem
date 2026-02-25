"""
ESP8266 Controller — управление пином через UDP.

Протокол:
  ESP → PC  : UDP broadcast "PCOUNTER_ESP" на порт ESP_LISTEN_PORT каждые ~5 сек
              (так PC узнаёт IP-адрес ESP)
  PC  → ESP : UDP пакет "1" или "0" на IP ESP, порт ESP_COMMAND_PORT
              "1" = включить пин, "0" = выключить

Задержки (из config.py):
  ESP_DELAY_ON  — сек между "стало занято" и отправкой "1"
  ESP_DELAY_OFF — сек между "стало пусто" и отправкой "0"
  При изменении состояния в период ожидания — отложенная команда отменяется.
"""

import socket
import threading
import time
from typing import Optional

from config import (
    ESP_LISTEN_PORT,
    ESP_COMMAND_PORT,
    ESP_DELAY_ON,
    ESP_DELAY_OFF,
    ESP_ANNOUNCE_PREFIX,
)


class EspController:
    """Находит ESP8266 в сети и отправляет ему команды включения/выключения пина."""

    def __init__(self):
        self._esp_ip: Optional[str] = None
        self._ip_lock = threading.Lock()

        self._stop = threading.Event()

        # Отложенная команда
        self._pending_timer: Optional[threading.Timer] = None
        self._pending_lock  = threading.Lock()

        # Сокет для отправки команд
        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Поток прослушивания анонсов от ESP
        self._listener = threading.Thread(
            target=self._listen_loop, daemon=True, name="esp-listener")

    # ── Публичный интерфейс ──────────────────────────────

    def start(self):
        self._listener.start()
        print(f"  [ESP] Ожидание ESP8266 (broadcast → порт {ESP_LISTEN_PORT})...")

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

    def set_occupied(self, occupied: bool):
        """
        Вызвать при смене состояния зала.
          occupied=True  → через ESP_DELAY_ON  сек отправить "1"
          occupied=False → через ESP_DELAY_OFF сек отправить "0"
        Если состояние снова меняется пока идёт задержка — команда отменяется.
        """
        cmd   = "1" if occupied else "0"
        delay = ESP_DELAY_ON if occupied else ESP_DELAY_OFF
        label = "включения" if occupied else "выключения"

        self._cancel_pending()

        if delay > 0:
            print(f"  [ESP] Команда '{cmd}' через {delay} сек")
            t = threading.Timer(delay, self._send, args=(cmd,))
            t.daemon = True
            with self._pending_lock:
                self._pending_timer = t
            t.start()
        else:
            self._send(cmd)

    # ── Приватные методы ────────────────────────────────

    def _cancel_pending(self):
        with self._pending_lock:
            if self._pending_timer is not None:
                self._pending_timer.cancel()
                self._pending_timer = None

    def _send(self, cmd: str):
        with self._ip_lock:
            ip = self._esp_ip
        if ip is None:
            print(f"  [ESP] Команда '{cmd}' не отправлена — ESP не обнаружен")
            return
        try:
            self._send_sock.sendto(cmd.encode(), (ip, ESP_COMMAND_PORT))
            label = "ВКЛ" if cmd == "1" else "ВЫКЛ"
            print(f"  [ESP] → {label}  ({ip}:{ESP_COMMAND_PORT})")
        except Exception as e:
            print(f"  [ESP] Ошибка отправки: {e}")

    def _listen_loop(self):
        """Слушаем UDP broadcast-анонсы от ESP8266."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(('', ESP_LISTEN_PORT))
        except OSError as e:
            print(f"  [ESP] Не удалось открыть порт {ESP_LISTEN_PORT}: {e}")
            return

        while not self._stop.is_set():
            try:
                data, (addr_ip, _) = sock.recvfrom(64)
                msg = data.decode('utf-8', errors='ignore').strip()
                if msg.startswith(ESP_ANNOUNCE_PREFIX):
                    with self._ip_lock:
                        if self._esp_ip != addr_ip:
                            self._esp_ip = addr_ip
                            print(f"  [ESP] Обнаружен: {addr_ip}")
            except socket.timeout:
                continue
            except Exception:
                break

        sock.close()
