"""
Менеджер зон исключения (ROI).
Позволяет рисовать прямоугольники на кадре для исключения областей
(например, окон), в которых людей считать не нужно.

Зоны сохраняются в JSON и автоматически загружаются при следующем запуске.
Фильтрация: пост-инференс — отбрасываем детекции, центр которых попадает в зону.
"""

import json
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional


class ExclusionZone:
    """Прямоугольная зона исключения."""

    def __init__(self, name: str, pt1: Tuple[int, int], pt2: Tuple[int, int],
                 enabled: bool = True):
        self.name = name
        # Нормализуем координаты (top-left, bottom-right)
        self.x1 = min(pt1[0], pt2[0])
        self.y1 = min(pt1[1], pt2[1])
        self.x2 = max(pt1[0], pt2[0])
        self.y2 = max(pt1[1], pt2[1])
        self.enabled = enabled

    def contains(self, x: int, y: int) -> bool:
        """Проверяет, находится ли точка внутри зоны."""
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'pt1': [self.x1, self.y1],
            'pt2': [self.x2, self.y2],
            'enabled': self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'ExclusionZone':
        return cls(
            name=d['name'],
            pt1=tuple(d['pt1']),
            pt2=tuple(d['pt2']),
            enabled=d.get('enabled', True),
        )


class ROIManager:
    """Управление зонами исключения: загрузка, сохранение, фильтрация, визуализация."""

    DEFAULT_FILE = "exclusion_zones.json"

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path or self.DEFAULT_FILE)
        self.zones: List[ExclusionZone] = []
        self._mask: Optional[np.ndarray] = None

    # ─── Загрузка / Сохранение ───

    def load(self) -> bool:
        """Загружает зоны из JSON. Возвращает True если файл найден."""
        if not self.config_path.exists():
            return False
        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)
            self.zones = [ExclusionZone.from_dict(z) for z in data.get('zones', [])]
            print(f"  Загружено зон исключения: {len(self.zones)} из {self.config_path}")
            return True
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Ошибка чтения {self.config_path}: {e}")
            return False

    def save(self):
        """Сохраняет зоны в JSON."""
        data = {'zones': [z.to_dict() for z in self.zones]}
        with open(self.config_path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  Сохранено зон: {len(self.zones)} → {self.config_path}")

    # ─── Маска и фильтрация ───

    def build_mask(self, frame_h: int, frame_w: int):
        """Строит бинарную маску: 255=активная зона, 0=исключена."""
        self._mask = np.ones((frame_h, frame_w), dtype=np.uint8) * 255
        for zone in self.zones:
            if zone.enabled:
                self._mask[zone.y1:zone.y2, zone.x1:zone.x2] = 0

    def filter_detections(self, detections) -> object:
        """
        Убирает детекции, центр которых попадает в зону исключения.
        Работает с supervision.Detections.
        """
        if not self.zones or self._mask is None:
            return detections

        if detections.xyxy is None or len(detections.xyxy) == 0:
            return detections

        keep = []
        for i, box in enumerate(detections.xyxy):
            cx = int((box[0] + box[2]) / 2)
            cy = int((box[1] + box[3]) / 2)
            # Проверяем по маске
            if 0 <= cy < self._mask.shape[0] and 0 <= cx < self._mask.shape[1]:
                if self._mask[cy, cx] > 0:  # Активная зона
                    keep.append(i)
            else:
                keep.append(i)  # За пределами кадра — оставляем

        if keep:
            return detections[keep]
        else:
            # Возвращаем пустые детекции
            import supervision as sv
            return sv.Detections.empty()

    # ─── Визуализация ───

    def draw_zones(self, frame: np.ndarray) -> np.ndarray:
        """Рисует зоны исключения на кадре (полупрозрачные)."""
        if not self.zones:
            return frame

        overlay = frame.copy()
        for zone in self.zones:
            if not zone.enabled:
                continue
            # Серая полупрозрачная заливка
            cv2.rectangle(overlay, (zone.x1, zone.y1), (zone.x2, zone.y2),
                          (80, 80, 80), -1)

        frame = cv2.addWeighted(overlay, 0.4, frame, 0.6, 0)

        # Рамки и подписи поверх
        for zone in self.zones:
            if not zone.enabled:
                continue
            cv2.rectangle(frame, (zone.x1, zone.y1), (zone.x2, zone.y2),
                          (0, 0, 200), 2)
            cv2.putText(frame, zone.name,
                        (zone.x1 + 5, zone.y1 + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        return frame

    # ─── Интерактивная настройка ───

    def interactive_setup(self, frame: np.ndarray) -> bool:
        """
        Открывает окно для рисования зон исключения.
        Click+drag = нарисовать прямоугольник.
        'r' = удалить последний, 'c' = очистить всё,
        Enter = сохранить, Esc = отмена.

        Возвращает True если зоны сохранены.
        """
        base_frame = frame.copy()
        rects: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
        drawing = False
        start_pt = (0, 0)
        current_pt = (0, 0)

        win_name = "Setup Exclusion Zones"

        def _redraw():
            display = base_frame.copy()
            for i, (p1, p2) in enumerate(rects):
                cv2.rectangle(display, p1, p2, (0, 255, 0), 2)
                cv2.putText(display, f"Zone {i + 1}", (p1[0] + 5, p1[1] + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            # Инструкции
            h = display.shape[0]
            cv2.putText(display, "Drag to draw | r=undo | c=clear | Enter=save | Esc=cancel",
                        (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
            cv2.putText(display, f"Zones: {len(rects)}",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            return display

        def on_mouse(event, x, y, flags, param):
            nonlocal drawing, start_pt, current_pt

            if event == cv2.EVENT_LBUTTONDOWN:
                drawing = True
                start_pt = (x, y)
                current_pt = (x, y)

            elif event == cv2.EVENT_MOUSEMOVE and drawing:
                current_pt = (x, y)
                display = _redraw()
                cv2.rectangle(display, start_pt, current_pt, (255, 0, 0), 2)
                cv2.imshow(win_name, display)

            elif event == cv2.EVENT_LBUTTONUP and drawing:
                drawing = False
                # Минимальный размер 20x20 пикселей
                dx = abs(x - start_pt[0])
                dy = abs(y - start_pt[1])
                if dx > 20 and dy > 20:
                    rects.append((start_pt, (x, y)))
                    print(f"  Зона {len(rects)}: ({start_pt}) → ({x}, {y})")
                cv2.imshow(win_name, _redraw())

        cv2.imshow(win_name, _redraw())
        cv2.setMouseCallback(win_name, on_mouse)

        print("\n" + "=" * 55)
        print("  НАСТРОЙКА ЗОН ИСКЛЮЧЕНИЯ")
        print("=" * 55)
        print("  Нарисуйте прямоугольники вокруг областей, которые")
        print("  нужно исключить (окна, зеркала и т.п.)")
        print()
        print("  Drag       — нарисовать зону")
        print("  r          — удалить последнюю зону")
        print("  c          — очистить все")
        print("  Enter      — сохранить и продолжить")
        print("  Esc        — отмена (без сохранения)")
        print("=" * 55 + "\n")

        while True:
            key = cv2.waitKey(30) & 0xFF

            if key == 27:  # Esc
                print("  Отмена. Зоны не сохранены.")
                cv2.destroyWindow(win_name)
                for _ in range(10):   # macOS: нужно сбросить очередь событий
                    cv2.waitKey(1)
                return False

            elif key == 13:  # Enter
                cv2.destroyWindow(win_name)
                for _ in range(10):   # macOS: нужно сбросить очередь событий
                    cv2.waitKey(1)
                self.zones = [
                    ExclusionZone(name=f"Zone_{i + 1}", pt1=p1, pt2=p2)
                    for i, (p1, p2) in enumerate(rects)
                ]
                if self.zones:
                    self.save()
                else:
                    print("  Нет зон для сохранения.")
                return True

            elif key == ord('r'):
                if rects:
                    removed = rects.pop()
                    print(f"  Удалена зона. Осталось: {len(rects)}")
                cv2.imshow(win_name, _redraw())

            elif key == ord('c'):
                rects.clear()
                print("  Все зоны очищены.")
                cv2.imshow(win_name, _redraw())

        return False
