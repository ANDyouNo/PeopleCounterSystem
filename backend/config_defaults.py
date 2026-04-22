"""
Настройки по умолчанию.
Хранятся в БД (таблица settings), здесь только значения для первого запуска.

Структура каждой настройки:
  value           — значение по умолчанию (строка, парсится по type)
  type            — int | float | bool | string
  description     — человекочитаемое описание (отображается в UI)
  category        — группа в UI: camera | detection | showcase | light
  restart_required — True если изменение требует перезапуска
"""

DEFAULT_SETTINGS: dict = {
    # ── Камера ──────────────────────────────────────────────────
    "camera_index": {
        "value": "0",
        "type": "int",
        "description": "Индекс камеры (0, 1, 2 ...)",
        "category": "camera",
        "restart_required": True,
    },
    "frame_width": {
        "value": "640",
        "type": "int",
        "description": "Ширина кадра (пикселей)",
        "category": "camera",
        "restart_required": True,
    },
    "frame_height": {
        "value": "480",
        "type": "int",
        "description": "Высота кадра (пикселей)",
        "category": "camera",
        "restart_required": True,
    },

    # ── Детекция ────────────────────────────────────────────────
    "model_size": {
        "value": "n",
        "type": "string",
        "description": "Размер модели YOLOv8: n / s / m / l / x",
        "category": "detection",
        "restart_required": True,
    },
    "inference_backend": {
        "value": "auto",
        "type": "string",
        "description": "Бэкенд инференса: auto | onnx | pytorch",
        "category": "detection",
        "restart_required": True,
    },
    "confidence_threshold": {
        "value": "0.4",
        "type": "float",
        "description": "Порог уверенности детекции (0.0–1.0)",
        "category": "detection",
        "restart_required": False,
    },
    "iou_threshold": {
        "value": "0.45",
        "type": "float",
        "description": "Порог IOU для NMS (0.0–1.0)",
        "category": "detection",
        "restart_required": False,
    },
    "inference_size": {
        "value": "320",
        "type": "int",
        "description": "Размер входного изображения YOLO (пикселей)",
        "category": "detection",
        "restart_required": False,
    },
    "skip_frames": {
        "value": "1",
        "type": "int",
        "description": "Запускать YOLO каждые N кадров (1 = каждый кадр)",
        "category": "detection",
        "restart_required": False,
    },
    "debounce_frames": {
        "value": "4",
        "type": "int",
        "description": "Человек считается ушедшим после N пропущенных кадров",
        "category": "detection",
        "restart_required": False,
    },
    "max_fps": {
        "value": "30",
        "type": "int",
        "description": "Максимальная частота обработки кадров (0 = без ограничений)",
        "category": "detection",
        "restart_required": False,
    },

    # ── Витрины (Showcase ESP) ───────────────────────────────────
    "showcase_esp_enabled": {
        "value": "true",
        "type": "bool",
        "description": "Включить управление витринами через ESP8266",
        "category": "showcase",
        "restart_required": True,
    },
    "showcase_count": {
        "value": "8",
        "type": "int",
        "description": "Количество витрин",
        "category": "showcase",
        "restart_required": False,
    },
    "showcase_delay_on": {
        "value": "3",
        "type": "int",
        "description": "Задержка включения витрин (с) — защита от ложных срабатываний",
        "category": "showcase",
        "restart_required": False,
    },
    "showcase_delay_off": {
        "value": "10",
        "type": "int",
        "description": "Задержка выключения витрин (с) после ухода людей",
        "category": "showcase",
        "restart_required": False,
    },

    # ── Общий свет (Light ESP) ───────────────────────────────────
    "light_esp_enabled": {
        "value": "true",
        "type": "bool",
        "description": "Включить управление общим светом через ESP8266",
        "category": "light",
        "restart_required": True,
    },
    "light_delay_after_showcases": {
        "value": "5",
        "type": "int",
        "description": "Задержка включения общего света после витрин (с)",
        "category": "light",
        "restart_required": False,
    },
    "light_delay_off": {
        "value": "0",
        "type": "int",
        "description": "Задержка выключения общего света (с)",
        "category": "light",
        "restart_required": False,
    },
}


def cast_value(raw: str, typ: str):
    """Привести строку к нужному типу."""
    if typ == "int":
        return int(raw)
    if typ == "float":
        return float(raw)
    if typ == "bool":
        return raw.lower() in ("true", "1", "yes")
    return raw  # string


def get_default_values() -> dict:
    """Вернуть словарь {key: typed_value} для дефолтных настроек."""
    return {
        k: cast_value(v["value"], v["type"])
        for k, v in DEFAULT_SETTINGS.items()
    }
