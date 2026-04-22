"""
People Counter System v4.0
Подсчёт людей через камеру. Управление витринами и общим светом.

Все настройки — в config.py.

Запуск:  python main.py

─── Клавиши (без Enter) ────────────────────────────────────────
  t       — открыть / закрыть окно превью
  q / Esc — завершить

  Витрины (showcase):
  a       — принудительно ВКЛ ВСЕ витрины
  z       — снять принуждение со ВСЕХ витрин
  m       — режим выбора витрины (затем нажмите 1–8 для переключения)

  Общий свет:
  l       — принудительно ВКЛ / ВЫКЛ общий свет (переключение)
────────────────────────────────────────────────────────────────
"""

import os
import platform
import signal
import sys
import time
import threading
from queue import Queue, Empty
from typing import Optional

import cv2

_IS_MACOS = platform.system() == "Darwin"

from roi_manager import ROIManager
from database import Database
from detection_engine import DetectionEngine, load_model
from config import (
    CAMERA_INDEX,
    FRAME_WIDTH, FRAME_HEIGHT,
    MODEL_SIZE, INFERENCE_SIZE, SKIP_FRAMES, INFERENCE_BACKEND,
    DEBOUNCE_FRAMES,
    EXCLUSION_ZONES_FILE, SETUP_ZONES_ON_START, CLEAR_ZONES_ON_START,
    DB_FILE, CLEAR_DB_ON_START,
    SHOWCASE_ESP_ENABLED,
    LIGHT_ESP_ENABLED,
    SHOWCASE_COUNT,
    LIGHT_DELAY_AFTER_SHOWCASES,
)

PREVIEW_WIN = "People Counter — Preview"


# ═══════════════════════════════════════════════════════
#  Чтение клавиш из терминала (без Enter)
# ═══════════════════════════════════════════════════════

class KeyboardReader:
    """
    Читает одиночные нажатия из терминала без Enter.
      macOS / Linux : tty.setcbreak + select
      Windows       : msvcrt
    """

    def __init__(self):
        self.queue: Queue = Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="kbd")
        self._thread.start()

    def _run(self):
        if not self._try_tty():
            self._try_msvcrt()

    def _try_tty(self) -> bool:
        try:
            import tty, termios, select as sel

            fd  = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)

            try:
                while not self._stop.is_set():
                    r, _, _ = sel.select([sys.stdin], [], [], 0.05)
                    if r:
                        ch = sys.stdin.read(1)
                        if ch:
                            self.queue.put(ch.lower())
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

            return True
        except Exception:
            return False

    def _try_msvcrt(self):
        try:
            import msvcrt
            while not self._stop.is_set():
                if msvcrt.kbhit():
                    raw = msvcrt.getch()
                    ch  = raw.decode('utf-8', errors='ignore').lower()
                    if ch:
                        self.queue.put(ch)
                else:
                    time.sleep(0.05)
        except Exception:
            pass

    def get(self) -> Optional[str]:
        try:
            return self.queue.get_nowait()
        except Empty:
            return None

    def stop(self):
        self._stop.set()


# ═══════════════════════════════════════════════════════
#  Камера
# ═══════════════════════════════════════════════════════

def open_camera(idx: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(idx)
    if not cap.isOpened():
        print(f"  ОШИБКА: Не удалось открыть камеру {idx}.")
        print(f"  Проверьте CAMERA_INDEX в config.py")
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    ret, _ = cap.read()
    if not ret:
        print(f"  ОШИБКА: Камера {idx} открыта, но кадр не читается.")
        sys.exit(1)
    return cap


# ═══════════════════════════════════════════════════════
#  Превью
# ═══════════════════════════════════════════════════════

_cv2_flush_remaining: int = 0


def _open_preview():
    print("  [t] Превью открыто  (закрыть: t)")


def _close_preview():
    global _cv2_flush_remaining
    if _IS_MACOS:
        try:
            cv2.destroyWindow(PREVIEW_WIN)
        except Exception:
            pass
        _cv2_flush_remaining = 5
    else:
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
    print("  [t] Превью закрыто")


# ═══════════════════════════════════════════════════════
#  Вывод в терминал
# ═══════════════════════════════════════════════════════

def _print_banner():
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║       People Counter  v4.0  —  Showcase + Light     ║")
    print("║  YOLOv8 + ByteTrack + SQLite + PCA9685 + Реле       ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

def _print_help(showcase_enabled: bool, light_enabled: bool):
    print("  Клавиши:")
    print("    t       — превью            q/Esc — выход")
    if showcase_enabled:
        print("    a       — принудительно ВКЛ ВСЕ витрины")
        print("    z       — снять принуждение со ВСЕХ витрин")
        print("    m       — режим выбора витрины (затем 1–8)")
    if light_enabled:
        print("    l       — принудительно ВКЛ/ВЫКЛ общий свет")
    print()

def _print_status(state: dict, showcase=None, light=None):
    people = state.get('people_now', 0)
    fps    = state.get('fps', 0.0)
    inf_ms = state.get('inference_ms', 0.0)
    unique = state.get('total_unique', 0)
    today  = state.get('today_summary', {})
    visits = today.get('total_visits', 0)

    mark  = "●" if people > 0 else "○"
    label = f"ЕСТЬ ЛЮДИ ({people} чел)" if people > 0 else "пусто"
    line  = (f"  {mark} {label}  |  сессия: {unique} уник.  |  "
             f"сегодня: {visits} визитов  |  FPS {fps:.0f}  inf {inf_ms:.0f}ms")

    if showcase is not None:
        forced = showcase.get_forced()
        if forced:
            showcases_str = ",".join(str(s) for s in sorted(forced))
            line += f"  |  витрины[F]: {showcases_str}"
        else:
            line += "  |  витрины[авто]"

    if light is not None:
        lf = "СВЕТ[F]" if light.is_forced else "свет[авто]"
        line += f"  |  {lf}"

    print(line)


# ═══════════════════════════════════════════════════════
#  main
# ═══════════════════════════════════════════════════════

def main():
    _print_banner()

    # ── 1. Камера ──────────────────────────────────────
    print(f"[1/4] Камера {CAMERA_INDEX}...")
    cap      = open_camera(CAMERA_INDEX)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"  OK  {actual_w}×{actual_h}")

    # ── 2. Модель ──────────────────────────────────────
    print(f"\n[2/4] Модель YOLOv8{MODEL_SIZE}...")
    model = load_model(MODEL_SIZE, INFERENCE_BACKEND)
    print(f"  ImgSize: {INFERENCE_SIZE}  Skip: {SKIP_FRAMES}  Debounce: {DEBOUNCE_FRAMES}")

    # ── 3. Зоны исключения ─────────────────────────────
    print(f"\n[3/4] Зоны исключения...")

    if CLEAR_ZONES_ON_START:
        if os.path.exists(EXCLUSION_ZONES_FILE):
            os.remove(EXCLUSION_ZONES_FILE)
            print(f"  Зоны очищены (удалён {EXCLUSION_ZONES_FILE})")
        else:
            print(f"  Зоны уже пусты")

    roi_mgr      = ROIManager(config_path=EXCLUSION_ZONES_FILE)
    zones_loaded = roi_mgr.load()

    if SETUP_ZONES_ON_START or not zones_loaded:
        if not zones_loaded:
            print("  Файл зон не найден. Запускаем настройку...")
        else:
            print("  SETUP_ZONES_ON_START=True, открываем настройку...")

        ret, first_frame = cap.read()
        if ret:
            roi_mgr.interactive_setup(first_frame)
        else:
            print("  ОШИБКА: не удалось получить кадр для настройки зон")

    if roi_mgr.zones:
        roi_mgr.build_mask(actual_h, actual_w)
        print(f"  Активных зон: {len(roi_mgr.zones)}")
    else:
        print("  Зон нет — вся область активна")

    # ── 4. БД + Engine ─────────────────────────────────
    print(f"\n[4/4] Запуск...")

    if CLEAR_DB_ON_START:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            print(f"  БД очищена (удалён {DB_FILE})")
        else:
            print(f"  БД уже пуста")

    db    = Database(DB_FILE)
    today = db.get_today_summary()
    print(f"  БД: {DB_FILE}  (сегодня: {today['total_visits']} визитов)")

    engine = DetectionEngine(cap, model, roi_mgr, db)
    engine.start()

    # ── Showcase ESP ────────────────────────────────────
    showcase: Optional[object] = None
    if SHOWCASE_ESP_ENABLED:
        from showcase_controller import ShowcaseController
        showcase = ShowcaseController()
        showcase.start()
        print(f"  Витрин: {SHOWCASE_COUNT}  |  Light offset: {LIGHT_DELAY_AFTER_SHOWCASES} с")

    # ── Light ESP ───────────────────────────────────────
    light: Optional[object] = None
    if LIGHT_ESP_ENABLED:
        from light_controller import LightController
        light = LightController()
        light.start()

    kbd = KeyboardReader()
    kbd.start()

    print(f"\n  Детекция запущена.")
    _print_help(SHOWCASE_ESP_ENABLED, LIGHT_ESP_ENABLED)

    # ── Состояние ──
    global _cv2_flush_remaining
    preview_on    = False
    running       = True
    status_timer  = time.time()
    prev_occupied = False

    # Режим выбора витрины (после нажатия 'm')
    showcase_select_mode = False
    showcase_select_time = 0.0

    def _sigint(sig, frm):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _sigint)

    # ════════════════════════════════════════════════════
    #  Главный цикл
    # ════════════════════════════════════════════════════
    while running:

        # ── Считать клавишу ──
        key = kbd.get()

        # ── Превью + cv2 события ──
        if preview_on:
            frame = engine.get_latest_frame()
            if frame is not None:
                cv2.imshow(PREVIEW_WIN, frame)
            cv_key = cv2.waitKey(30) & 0xFF
            if key is None and cv_key not in (255, 0xFF, 0) and cv_key < 128:
                key = chr(cv_key).lower()
        else:
            if _cv2_flush_remaining > 0:
                cv2.waitKey(1)
                _cv2_flush_remaining -= 1
            else:
                time.sleep(0.03)

        # ── Таймаут режима выбора витрины ──
        if showcase_select_mode and time.time() - showcase_select_time > 5.0:
            showcase_select_mode = False
            print("  [m] Режим выбора витрины истёк")

        # ── Обработка клавиш ──
        if key is not None:

            if showcase_select_mode and key in '12345678':
                # Нажата цифра в режиме выбора витрины
                num = int(key)
                if showcase:
                    new_state = showcase.toggle_force(num)
                    state_str = "ПРИНУДИТЕЛЬНО ВКЛ" if new_state else "авто"
                    print(f"  [m] Витрина {num} → {state_str}")
                showcase_select_mode = False

            elif key in ('q', '\x1b'):          # q или Esc
                running = False

            elif key == 't':
                if preview_on:
                    _close_preview()
                    preview_on = False
                else:
                    _open_preview()
                    preview_on = True

            elif key == 'a' and showcase:
                # Принудительно ВКЛ ВСЕ витрины
                showcase.force_on()
                print("  [a] ВСЕ витрины → ПРИНУДИТЕЛЬНО ВКЛ")

            elif key == 'z' and showcase:
                # Снять принуждение со ВСЕХ витрин
                showcase.force_off()
                print("  [z] ВСЕ витрины → принуждение снято")

            elif key == 'm' and showcase:
                # Войти в режим выбора витрины
                showcase_select_mode = True
                showcase_select_time = time.time()
                forced = showcase.get_forced()
                forced_str = (",".join(str(s) for s in sorted(forced))
                              if forced else "нет")
                print(f"  [m] Выбор витрины: нажмите 1–{SHOWCASE_COUNT} "
                      f"(принудительно: {forced_str}, таймаут 5 с)")

            elif key == 'l' and light:
                # Переключить принудительный режим общего света
                new_state = light.toggle_force()
                print(f"  [l] Общий свет → "
                      f"{'ПРИНУДИТЕЛЬНО ВКЛ' if new_state else 'принуждение снято'}")

        # ── Авто-режим: отслеживание смены занятости ──
        if showcase or light:
            state    = engine.get_state()
            occupied = state.get('people_now', 0) > 0
            if occupied != prev_occupied:
                prev_occupied = occupied
                if showcase:
                    showcase.set_occupied(occupied)
                if light:
                    light.set_occupied(occupied)

        # ── Периодический статус (каждые 10 с) ──
        now = time.time()
        if now - status_timer >= 10.0:
            _print_status(engine.get_state(), showcase, light)
            status_timer = now

        # ── Engine упал? ──
        if not engine.is_alive():
            print("  [Engine] Поток детекции завершился неожиданно")
            running = False

    # ════════════════════════════════════════════════════
    #  Завершение
    # ════════════════════════════════════════════════════
    print("\nЗавершение...")

    if showcase:
        showcase.shutdown()   # Отправляет OFF на ESP перед остановкой потоков
    if light:
        light.shutdown()      # Отправляет OFF на ESP перед остановкой потоков
    kbd.stop()

    if preview_on:
        _close_preview()
    else:
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)

    engine.stop()
    engine.join(timeout=5)
    cap.release()

    try:
        s      = db.get_today_summary()
        unique = engine.visitor_tracker.total_unique_visitors
        print(f"\n  Итог сессии : {unique} уник. посетителей")
        print(f"  Итог сегодня: {s['total_visits']} визитов | "
              f"{s['total_minutes']} мин | max {s['max_people']} чел")
        print(f"  БД: {DB_FILE}")
    except Exception:
        pass

    db.close()
    print("  Готово.\n")


if __name__ == "__main__":
    main()
