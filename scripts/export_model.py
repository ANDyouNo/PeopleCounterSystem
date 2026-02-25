"""
Экспорт YOLOv8n в ONNX формат для ускорения инференса на CPU.

Запустите один раз:
    python export_model.py

После этого main.py автоматически подхватит .onnx модель (при INFERENCE_BACKEND="auto").
На Intel i3/i5/i7 ONNX Runtime даёт прирост ~20-30% по сравнению с PyTorch.
"""

from ultralytics import YOLO
from config import MODEL_SIZE, INFERENCE_SIZE


def main():
    model_name = f"yolov8{MODEL_SIZE}.pt"
    print(f"Загрузка модели {model_name}...")

    model = YOLO(model_name)

    print(f"Экспорт в ONNX (imgsz={INFERENCE_SIZE})...")
    output_path = model.export(
        format="onnx",
        imgsz=INFERENCE_SIZE,
        opset=12,       # Максимальная совместимость со старыми CPU
        simplify=True,  # Оптимизация графа
        dynamic=False,  # Фиксированный размер = быстрее на CPU
    )

    print(f"\nГотово! Экспортирована модель: {output_path}")
    print(f"Теперь main.py будет автоматически использовать ONNX бэкенд.")
    print(f"\nДля использования убедитесь что установлен onnxruntime:")
    print(f"  pip install onnxruntime")


if __name__ == "__main__":
    main()
