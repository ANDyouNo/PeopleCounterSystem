"""
Фоновый поток детекции людей (адаптирован для FastAPI / AppState).

Основные изменения по сравнению с оригиналом:
  - Читает параметры из AppState.get_setting() вместо config.py
  - Уведомляет AppState об изменении количества людей
  - Не зависит от cv2.imshow / клавиатурного ввода
"""

import json
import os
import time
import threading
from queue import Queue, Empty
from typing import Optional, TYPE_CHECKING

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

if TYPE_CHECKING:
    from backend.state import AppState
    from backend.core.roi_manager import ROIManager
    from backend.db.database import Database


# ─── Захват кадров ────────────────────────────────────────────

class FrameGrabber(threading.Thread):
    def __init__(self, cap: cv2.VideoCapture, queue_size: int = 2):
        super().__init__(daemon=True)
        self.cap = cap
        self.queue: Queue = Queue(maxsize=queue_size)
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

    def read(self) -> np.ndarray:
        return self.queue.get(timeout=5.0)

    def stop(self):
        self.running = False


# ─── Трекер посетителей ───────────────────────────────────────

class VisitorTracker:
    def __init__(self, debounce_frames: int = 4):
        self.debounce_frames = debounce_frames
        self.known_ids: dict = {}
        self.missing_counter: dict = {}
        self.active_ids: set = set()
        self.total_unique_visitors = 0
        self.current_people = 0

    def update(self, tracker_ids: list) -> dict:
        current_set = set(tracker_ids)
        new_visitors, lost_visitors = [], []

        for tid in current_set:
            if tid not in self.known_ids:
                self.known_ids[tid] = True
                self.total_unique_visitors += 1
                new_visitors.append(tid)
            self.missing_counter.pop(tid, None)
            self.active_ids.add(tid)

        for tid in list(self.active_ids - current_set):
            self.missing_counter[tid] = self.missing_counter.get(tid, 0) + 1
            if self.missing_counter[tid] >= self.debounce_frames:
                self.active_ids.discard(tid)
                self.missing_counter.pop(tid, None)
                self.known_ids[tid] = False
                lost_visitors.append(tid)

        self.current_people = len(current_set)
        return {
            "current_people": self.current_people,
            "new_visitors": new_visitors,
            "lost_visitors": lost_visitors,
            "total_unique": self.total_unique_visitors,
        }


# ─── Загрузка модели ─────────────────────────────────────────

def load_model(model_size: str, backend: str) -> YOLO:
    onnx_path = f"yolov8{model_size}.onnx"
    pt_path   = f"yolov8{model_size}.pt"
    if backend == "onnx" or (backend == "auto" and os.path.exists(onnx_path)):
        if os.path.exists(onnx_path):
            print(f"  Загрузка ONNX: {onnx_path}")
            return YOLO(onnx_path)
    print(f"  Загрузка PyTorch: {pt_path}")
    return YOLO(pt_path)


# ─── Оверлей на кадр (для MJPEG превью) ──────────────────────

def draw_overlay(frame: np.ndarray, people_now: int,
                 total_unique: int, fps: float,
                 inference_ms: float, today: dict) -> np.ndarray:
    h, w = frame.shape[:2]
    overlay = frame.copy()
    bg = (0, 35, 0) if people_now > 0 else (0, 0, 0)
    cv2.rectangle(overlay, (0, 0), (w, 95), bg, -1)
    frame = cv2.addWeighted(overlay, 0.65, frame, 0.35, 0)

    status = f"PEOPLE: {people_now}" if people_now > 0 else "EMPTY"
    color  = (0, 230, 80) if people_now > 0 else (120, 120, 120)
    dot    = (0, 230, 0) if people_now > 0 else (70, 70, 70)
    cv2.circle(frame, (w - 28, 22), 10, dot, -1)
    cv2.putText(frame, status, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
    cv2.putText(frame, f"Unique/session: {total_unique}",
                (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 200, 200), 1)
    cv2.putText(frame, f"Today: {today['total_visits']} visits | "
                f"{today['total_minutes']} min | max {today['max_people']}",
                (12, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (150, 150, 150), 1)
    cv2.putText(frame, f"FPS:{fps:.0f} Inf:{inference_ms:.0f}ms",
                (w - 130, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (130, 130, 130), 1)
    return frame


# ─── DetectionEngine ─────────────────────────────────────────

class DetectionEngine(threading.Thread):
    """
    Фоновый поток детекции. Читает настройки из AppState на лету.
    """

    DB_LOG_EVERY_N = 5
    DB_FLUSH_INTERVAL = 30

    def __init__(self, cap: cv2.VideoCapture, model: YOLO,
                 roi_mgr: "ROIManager", db: "Database",
                 app_state: "AppState"):
        super().__init__(daemon=True, name="detection-engine")
        self.cap = cap
        self.model = model
        self.roi_mgr = roi_mgr
        self.db = db
        self.app_state = app_state

        self.grabber = FrameGrabber(cap, queue_size=2)

        debounce = app_state.get_setting("debounce_frames", 4)
        self.byte_track = sv.ByteTrack(
            lost_track_buffer=debounce * 2,
            track_activation_threshold=0.25,
            minimum_matching_threshold=0.8,
            frame_rate=30,
        )
        self.visitor_tracker = VisitorTracker(debounce_frames=debounce)
        self.box_annotator   = sv.BoxAnnotator(thickness=2)
        self.label_annotator = sv.LabelAnnotator(
            text_scale=0.5, text_thickness=1, text_padding=5)

        self._frame_lock   = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self.running = True

    def get_latest_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def stop(self):
        self.running = False

    def run(self):
        self.grabber.start()

        # Закрыть незакрытые сессии из предыдущего запуска
        open_id = self.db.get_open_presence()
        if open_id:
            self.db.end_presence(open_id)

        today = self.db.get_today_summary()
        self.app_state.update_detection_state(
            today_visits=today["total_visits"],
            today_minutes=today["total_minutes"],
            max_people_today=today["max_people"],
        )

        frame_count = detection_count = 0
        fps = fps_frame_count = 0
        fps_timer = time.time()
        inference_ms = 0.0
        last_detections = None
        last_flush = time.time()
        presence_id = None
        people_sum = people_samples = max_people = 0

        try:
            while self.running:
                t_start = time.perf_counter()

                # Читаем актуальные настройки
                skip_frames    = self.app_state.get_setting("skip_frames", 1)
                conf           = self.app_state.get_setting("confidence_threshold", 0.4)
                iou            = self.app_state.get_setting("iou_threshold", 0.45)
                inf_size       = self.app_state.get_setting("inference_size", 320)
                max_fps        = self.app_state.get_setting("max_fps", 30)
                min_frame_time = (1.0 / max_fps) if max_fps > 0 else 0

                try:
                    frame = self.grabber.read()
                except Empty:
                    if not self.running:
                        break
                    continue

                frame_count += 1
                run_det = (frame_count % max(skip_frames, 1) == 0) or (last_detections is None)

                # ── Детекция ──
                if run_det:
                    t0 = time.perf_counter()
                    results = self.model(
                        frame, conf=conf, iou=iou, imgsz=inf_size,
                        classes=[0], verbose=False,
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
                ids = (list(detections.tracker_id)
                       if detections.tracker_id is not None else [])
                vt = self.visitor_tracker.update(ids)
                people_now = vt["current_people"]

                # ── Логи ──
                for tid in vt["new_visitors"]:
                    print(f"  → #{tid}  (в зале: {people_now})")
                for tid in vt["lost_visitors"]:
                    print(f"  ← #{tid}  (в зале: {people_now})")

                # ── БД: присутствие ──
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
                        today = self.db.get_today_summary()
                        self.app_state.update_detection_state(
                            today_visits=today["total_visits"],
                            today_minutes=today["total_minutes"],
                            max_people_today=today["max_people"],
                        )

                # ── БД: сырые детекции ──
                if run_det and detection_count % self.DB_LOG_EVERY_N == 0:
                    ids_json = json.dumps([int(x) for x in ids]) if ids else None
                    self.db.log_detection(people_now, ids_json, inference_ms)

                # ── Flush ──
                now_t = time.time()
                if now_t - last_flush >= self.DB_FLUSH_INTERVAL:
                    self.db.flush()
                    today = self.db.get_today_summary()
                    self.app_state.update_detection_state(
                        today_visits=today["total_visits"],
                        today_minutes=today["total_minutes"],
                        max_people_today=today["max_people"],
                    )
                    last_flush = now_t

                # ── FPS ──
                fps_frame_count += 1
                elapsed = time.time() - fps_timer
                if elapsed >= 1.0:
                    fps = fps_frame_count / elapsed
                    fps_frame_count = 0
                    fps_timer = time.time()

                # ── Обновляем AppState (одновременно уведомляет ESP) ──
                self.app_state.update_detection_state(
                    people_now=people_now,
                    total_unique=vt["total_unique"],
                    fps=fps,
                    inference_ms=inference_ms,
                )
                self.app_state.check_occupancy_change(people_now)

                # ── Аннотированный кадр ──
                annotated = frame.copy()
                annotated = self.roi_mgr.draw_zones(annotated)
                annotated = self.box_annotator.annotate(annotated, detections)
                if detections.tracker_id is not None:
                    labels = [f"#{t}" for t in detections.tracker_id]
                    annotated = self.label_annotator.annotate(annotated, detections, labels)
                annotated = draw_overlay(
                    annotated, people_now, vt["total_unique"],
                    fps, inference_ms, today)

                with self._frame_lock:
                    self._latest_frame = annotated

                # ── FPS cap ──
                if min_frame_time > 0:
                    elapsed = time.perf_counter() - t_start
                    sleep = min_frame_time - elapsed
                    if sleep > 0:
                        time.sleep(sleep)

        except Exception as e:
            import traceback
            print(f"[DetectionEngine] Ошибка: {e}")
            traceback.print_exc()
        finally:
            if presence_id is not None:
                avg = people_sum / max(people_samples, 1)
                self.db.update_presence_stats(presence_id, max_people, avg)
                self.db.end_presence(presence_id)
            self.grabber.stop()
            print("[DetectionEngine] Остановлен")
