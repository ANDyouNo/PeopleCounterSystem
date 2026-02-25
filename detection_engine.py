"""
Фоновый поток детекции людей.

Выполняет: захват кадров → YOLOv8 инференс → ByteTrack → VisitorTracker → Database.
Публикует последний аннотированный кадр (numpy) для показа в превью.
"""

import json
import os
import time
import threading
from queue import Queue
from typing import Optional

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

from roi_manager import ROIManager
from database import Database
from config import (
    CONFIDENCE_THRESHOLD, IOU_THRESHOLD,
    INFERENCE_SIZE, SKIP_FRAMES,
    DEBOUNCE_FRAMES,
    DB_LOG_EVERY_N_DETECTIONS, DB_FLUSH_INTERVAL,
    SHOW_FPS, SHOW_LABELS, SHOW_EXCLUSION_ZONES,
    TEXT_COLOR, TEXT_BG_COLOR,
    MAX_FPS,
)

# Минимальное время одной итерации цикла (сек). 0 = без ограничений.
_MIN_FRAME_TIME = (1.0 / MAX_FPS) if MAX_FPS and MAX_FPS > 0 else 0.0


# ─── Потоковый захват кадров ───

class FrameGrabber(threading.Thread):
    """Читает кадры с камеры в отдельном потоке."""

    def __init__(self, cap: cv2.VideoCapture, queue_size: int = 2):
        super().__init__(daemon=True)
        self.cap = cap
        self.queue = Queue(maxsize=queue_size)
        self.running = True

    def run(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            if self.queue.full():
                try:
                    self.queue.get_nowait()
                except Exception:
                    pass
            self.queue.put(frame)

    def read(self):
        return self.queue.get(timeout=5.0)

    def stop(self):
        self.running = False


# ─── Трекер посетителей с debounce ───

class VisitorTracker:
    """
    Управляет уникальными посетителями на основе tracker_id от ByteTrack.
    Debounce: ID пропавший менее чем на DEBOUNCE_FRAMES кадров — тот же посетитель.
    """

    def __init__(self, debounce_frames: int = 4):
        self.debounce_frames = debounce_frames
        self.known_ids: dict = {}
        self.missing_counter: dict = {}
        self.active_ids: set = set()
        self.total_unique_visitors = 0
        self.current_people = 0

    def update(self, tracker_ids: list) -> dict:
        current_set = set(tracker_ids)
        new_visitors = []
        lost_visitors = []

        for tid in current_set:
            if tid not in self.known_ids:
                self.known_ids[tid] = True
                self.total_unique_visitors += 1
                new_visitors.append(tid)
            self.missing_counter.pop(tid, None)
            self.active_ids.add(tid)

        currently_missing = self.active_ids - current_set
        for tid in list(currently_missing):
            self.missing_counter[tid] = self.missing_counter.get(tid, 0) + 1
            if self.missing_counter[tid] >= self.debounce_frames:
                self.active_ids.discard(tid)
                self.missing_counter.pop(tid, None)
                self.known_ids[tid] = False
                lost_visitors.append(tid)

        self.current_people = len(current_set)

        return {
            'current_people': self.current_people,
            'new_visitors': new_visitors,
            'lost_visitors': lost_visitors,
            'total_unique': self.total_unique_visitors,
        }


# ─── Загрузка модели ───

def load_model(model_size: str, backend: str) -> YOLO:
    pt_path = f"yolov8{model_size}.pt"
    onnx_path = f"yolov8{model_size}.onnx"

    if backend == "onnx" or (backend == "auto" and os.path.exists(onnx_path)):
        if os.path.exists(onnx_path):
            print(f"  Загрузка ONNX: {onnx_path}")
            return YOLO(onnx_path)
        else:
            print(f"  ONNX не найден, используем PyTorch. Для ускорения: python export_model.py")

    print(f"  Загрузка PyTorch: {pt_path}")
    return YOLO(pt_path)


# ─── Оверлей ───

def draw_overlay(frame: np.ndarray, people_now: int, total_unique: int,
                 fps: float, inference_ms: float, db_today: dict) -> np.ndarray:
    h, w = frame.shape[:2]

    overlay = frame.copy()
    bar_h = 95
    bg_color = (0, 35, 0) if people_now > 0 else TEXT_BG_COLOR
    cv2.rectangle(overlay, (0, 0), (w, bar_h), bg_color, -1)
    frame = cv2.addWeighted(overlay, 0.65, frame, 0.35, 0)

    if people_now > 0:
        status_text = f"PEOPLE: {people_now}"
        status_color = (0, 230, 80)
        cv2.circle(frame, (w - 28, 22), 10, (0, 230, 0), -1)
    else:
        status_text = "EMPTY"
        status_color = (120, 120, 120)
        cv2.circle(frame, (w - 28, 22), 10, (70, 70, 70), -1)

    cv2.putText(frame, status_text, (12, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, status_color, 2)
    cv2.putText(frame, f"Unique/session: {total_unique}",
                (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.52, TEXT_COLOR, 1)

    today_txt = (f"Today: {db_today['total_visits']} visits | "
                 f"{db_today['total_minutes']} min | "
                 f"max {db_today['max_people']} people")
    cv2.putText(frame, today_txt, (12, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.43, (160, 160, 160), 1)

    if SHOW_FPS:
        cv2.putText(frame, f"FPS:{fps:.0f} Inf:{inference_ms:.0f}ms",
                    (w - 130, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (140, 140, 140), 1)

    return frame


# ─── DetectionEngine ───

class DetectionEngine(threading.Thread):
    """
    Фоновый поток: захват → детекция → трекинг → БД.
    Хранит последний аннотированный кадр для показа в превью (главный поток).
    """

    def __init__(self, cap: cv2.VideoCapture, model: YOLO,
                 roi_mgr: ROIManager, db: Database):
        super().__init__(daemon=True)
        self.cap = cap
        self.model = model
        self.roi_mgr = roi_mgr
        self.db = db

        self.grabber = FrameGrabber(cap, queue_size=2)

        self.byte_track = sv.ByteTrack(
            lost_track_buffer=DEBOUNCE_FRAMES * 2,
            track_activation_threshold=0.25,
            minimum_matching_threshold=0.8,
            frame_rate=30,
        )
        self.visitor_tracker = VisitorTracker(debounce_frames=DEBOUNCE_FRAMES)
        self.box_annotator = sv.BoxAnnotator(thickness=2)
        self.label_annotator = sv.LabelAnnotator(
            text_scale=0.5, text_thickness=1, text_padding=5)

        # Последний аннотированный кадр для превью (главный поток вызывает get_latest_frame)
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None

        # Thread-safe состояние
        self._state_lock = threading.Lock()
        self._state = {
            'people_now': 0,
            'total_unique': 0,
            'fps': 0.0,
            'inference_ms': 0.0,
            'today_summary': {'total_visits': 0, 'total_minutes': 0,
                              'max_people': 0, 'avg_people': 0},
        }

        self.running = True

    # ── Публичный интерфейс ──

    def get_state(self) -> dict:
        with self._state_lock:
            return dict(self._state)

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Получить копию последнего аннотированного кадра (безопасно из главного потока)."""
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def stop(self):
        self.running = False

    # ── Приватные методы ──

    def _update_state(self, **kwargs):
        with self._state_lock:
            self._state.update(kwargs)

    def _publish_frame(self, frame: np.ndarray):
        """Сохранить аннотированный кадр (вызывается из потока детекции)."""
        with self._frame_lock:
            self._latest_frame = frame  # уже копия из annotated

    # ── Основной цикл ──

    def run(self):
        self.grabber.start()

        # Закрыть незакрытые сессии
        open_id = self.db.get_open_presence()
        if open_id:
            self.db.end_presence(open_id)
            print(f"  Закрыта незавершённая сессия #{open_id}")

        today_summary = self.db.get_today_summary()
        self._update_state(today_summary=today_summary)

        frame_count = 0
        detection_count = 0
        fps = 0.0
        fps_timer = time.time()
        fps_frame_count = 0
        inference_ms = 0.0
        last_detections = None
        last_flush = time.time()
        presence_id = None
        people_sum = 0
        people_samples = 0
        max_people = 0

        try:
            while self.running:
                _t_frame_start = time.perf_counter()

                try:
                    frame = self.grabber.read()
                except Exception:
                    if not self.running:
                        break
                    continue

                frame_count += 1

                # ── Детекция ──
                run_detection = (frame_count % SKIP_FRAMES == 0) or (last_detections is None)

                if run_detection:
                    t0 = time.perf_counter()
                    results = self.model(
                        frame,
                        conf=CONFIDENCE_THRESHOLD,
                        iou=IOU_THRESHOLD,
                        imgsz=INFERENCE_SIZE,
                        classes=[0],
                        verbose=False,
                    )[0]
                    inference_ms = (time.perf_counter() - t0) * 1000

                    detections = sv.Detections.from_ultralytics(results)
                    detections = self.roi_mgr.filter_detections(detections)
                    last_detections = detections
                    detection_count += 1
                else:
                    detections = last_detections

                # ── Трекинг ──
                detections = self.byte_track.update_with_detections(detections)

                # ── Visitor tracking с debounce ──
                tracker_ids = (list(detections.tracker_id)
                               if detections.tracker_id is not None else [])
                vt_result = self.visitor_tracker.update(tracker_ids)

                people_now = vt_result['current_people']
                total_unique = vt_result['total_unique']

                # ── Логи посетителей ──
                for tid in vt_result['new_visitors']:
                    print(f"  → Вошёл #{tid} (всего в зале: {people_now})")
                for tid in vt_result['lost_visitors']:
                    print(f"  ← Вышел #{tid} (всего в зале: {people_now})")

                # ── БД: интервалы присутствия ──
                if people_now > 0 and presence_id is None:
                    presence_id = self.db.start_presence(people_now)
                    max_people = people_now
                    people_sum = people_now
                    people_samples = 1
                elif people_now > 0 and presence_id is not None:
                    people_sum += people_now
                    people_samples += 1
                    max_people = max(max_people, people_now)
                elif people_now == 0 and presence_id is not None:
                    if len(self.visitor_tracker.active_ids) == 0:
                        avg = people_sum / max(people_samples, 1)
                        self.db.update_presence_stats(presence_id, max_people, avg)
                        self.db.end_presence(presence_id)
                        presence_id = None
                        today_summary = self.db.get_today_summary()
                        self._update_state(today_summary=today_summary)

                # ── Сырые детекции в БД ──
                if run_detection and detection_count % DB_LOG_EVERY_N_DETECTIONS == 0:
                    ids_json = (json.dumps([int(x) for x in tracker_ids])
                                if tracker_ids else None)
                    self.db.log_detection(people_now, ids_json, inference_ms)

                # ── Flush ──
                now_t = time.time()
                if now_t - last_flush >= DB_FLUSH_INTERVAL:
                    self.db.flush()
                    today_summary = self.db.get_today_summary()
                    self._update_state(today_summary=today_summary)
                    last_flush = now_t

                # ── FPS ──
                fps_frame_count += 1
                elapsed = time.time() - fps_timer
                if elapsed >= 1.0:
                    fps = fps_frame_count / elapsed
                    fps_frame_count = 0
                    fps_timer = time.time()

                self._update_state(
                    people_now=people_now,
                    total_unique=total_unique,
                    fps=fps,
                    inference_ms=inference_ms,
                )

                # ── Аннотированный кадр для превью ──
                annotated = frame.copy()

                if SHOW_EXCLUSION_ZONES:
                    annotated = self.roi_mgr.draw_zones(annotated)

                annotated = self.box_annotator.annotate(
                    scene=annotated, detections=detections)

                if SHOW_LABELS and detections.tracker_id is not None:
                    labels = [f"#{tid}" for tid in detections.tracker_id]
                    annotated = self.label_annotator.annotate(
                        scene=annotated, detections=detections, labels=labels)

                annotated = draw_overlay(
                    annotated, people_now, total_unique,
                    fps, inference_ms, today_summary)

                self._publish_frame(annotated)

                # ── FPS cap ──
                if _MIN_FRAME_TIME > 0:
                    _elapsed = time.perf_counter() - _t_frame_start
                    _sleep   = _MIN_FRAME_TIME - _elapsed
                    if _sleep > 0:
                        time.sleep(_sleep)

        except Exception as e:
            print(f"\n[DetectionEngine] Ошибка: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if presence_id is not None:
                avg = people_sum / max(people_samples, 1)
                self.db.update_presence_stats(presence_id, max_people, avg)
                self.db.end_presence(presence_id)
            self.grabber.stop()
            print(f"\n  Детекция остановлена. "
                  f"Уникальных за сессию: {self.visitor_tracker.total_unique_visitors}")
