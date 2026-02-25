"""
People Counter System v3.3 — MVP
Подсчёт людей через камеру. Управление с клавиатуры (терминал).

Все настройки — в config.py (камера, зоны, модель, БД).

Запуск:  python main.py

Клавиши (без Enter):
  t   — открыть / закрыть окно превью
  q   — завершить
  Esc — завершить
"""

import os
import signal
import sys
import time
import threading
from queue import Queue, Empty
from typing import Optional

import cv2

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
    ESP_ENABLED,
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
            tty.setcbreak(fd)           # посимвольно, без эха

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
        """Неблокирующее получение клавиши. None если очередь пуста."""
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

def _open_preview():
    """Показать превью-окно (пустое — кадр придёт в следующей итерации)."""
    # Создаём окно заранее, чтобы оно появилось сразу
    cv2.namedWindow(PREVIEW_WIN, cv2.WINDOW_NORMAL)
    print("  [t] Превью открыто")


def _close_preview():
    """
    Надёжное закрытие окна превью на macOS / Windows / Linux.
    cv2.destroyWindow + несколько итераций waitKey для обработки событий.
    """
    try:
        cv2.destroyWindow(PREVIEW_WIN)
    except Exception:
        pass
    # Без этих вызовов на macOS окно зависает («мертвое» окно без содержимого)
    for _ in range(10):
        cv2.waitKey(1)
    print("  [t] Превью закрыто")


def _preview_is_open() -> bool:
    """Возвращает True, если окно ещё видимо (пользователь не закрыл крестиком)."""
    try:
        return cv2.getWindowProperty(PREVIEW_WIN, cv2.WND_PROP_VISIBLE) >= 1
    except Exception:
        return False


# ═══════════════════════════════════════════════════════
#  Вывод в терминал
# ═══════════════════════════════════════════════════════

def _print_banner():
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║       People Counter  v3.3  —  MVP              ║")
    print("║  YOLOv8 + ByteTrack + SQLite                    ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

def _print_help():
    print("  Клавиши:  t = превью     q / Esc = выход")
    print()

def _print_status(state: dict):
    people = state.get('people_now', 0)
    fps    = state.get('fps', 0.0)
    inf_ms = state.get('inference_ms', 0.0)
    unique = state.get('total_unique', 0)
    today  = state.get('today_summary', {})
    visits = today.get('total_visits', 0)

    mark = "●" if people > 0 else "○"
    label = f"ЕСТЬ ЛЮДИ ({people} чел)" if people > 0 else "пусто"
    print(f"  {mark} {label}  |  сессия: {unique} уник.  |  "
          f"сегодня: {visits} визитов  |  FPS {fps:.0f}  inf {inf_ms:.0f}ms")


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

    roi_mgr     = ROIManager(config_path=EXCLUSION_ZONES_FILE)
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

    # ── ESP8266 (опционально) ───────────────────────────
    esp = None
    if ESP_ENABLED:
        from esp_controller import EspController
        esp = EspController()
        esp.start()

    kbd = KeyboardReader()
    kbd.start()

    print(f"\n  Детекция запущена.")
    _print_help()

    # ── Состояние ──
    preview_on    = False
    running       = True
    status_timer  = time.time()
    prev_occupied = False          # для отслеживания смены занятости зала

    # Ctrl+C
    def _sigint(sig, frm):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _sigint)

    # ════════════════════════════════════════════════════
    #  Главный цикл
    # ════════════════════════════════════════════════════
    while running:

        # ── Считать клавишу (терминал) ──
        key = kbd.get()

        # Если превью открыто — также слушаем клавиши из cv2-окна
        if preview_on and key is None:
            cv_key = cv2.waitKey(30) & 0xFF
            if cv_key not in (255, 0xFF, 0):
                key = chr(cv_key).lower() if cv_key < 128 else None
        else:
            # Без превью — просто небольшая пауза
            time.sleep(0.03)

        # ── Обработка клавиш ──
        if key in ('q', '\x1b'):        # q или Esc
            running = False

        elif key == 't':
            if preview_on:
                _close_preview()
                preview_on = False
            else:
                _open_preview()
                preview_on = True

        # ── Обновление превью ──
        if preview_on:
            frame = engine.get_latest_frame()
            if frame is not None:
                cv2.imshow(PREVIEW_WIN, frame)

            # Пользователь закрыл окно крестиком?
            if not _preview_is_open():
                # destroyWindow уже сработал через крестик,
                # просто сбрасываем флаг и чистим очередь событий
                for _ in range(5):
                    cv2.waitKey(1)
                preview_on = False
                print("  [Превью] Закрыто пользователем")

        # ── ESP: отслеживание смены занятости ──
        if esp:
            state    = engine.get_state()
            occupied = state.get('people_now', 0) > 0
            if occupied != prev_occupied:
                esp.set_occupied(occupied)
                prev_occupied = occupied

        # ── Периодический статус в терминал (каждые 10 сек) ──
        now = time.time()
        if now - status_timer >= 10.0:
            _print_status(engine.get_state())
            status_timer = now

        # ── Engine упал? ──
        if not engine.is_alive():
            print("  [Engine] Поток детекции завершился неожиданно")
            running = False

    # ════════════════════════════════════════════════════
    #  Завершение
    # ════════════════════════════════════════════════════
    print("\nЗавершение...")

    if esp:
        esp.stop()
    kbd.stop()

    if preview_on:
        _close_preview()
    else:
        # На случай если есть «призрачные» окна
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
