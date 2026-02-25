"""
Утилиты для перечисления и выбора камер.
Кроссплатформенно: Windows, macOS, Linux.
"""

import cv2
import sys


def enumerate_cameras(max_index: int = 10) -> list:
    """
    Перечисляет доступные камеры, пробуя индексы 0..max_index-1.
    Возвращает список словарей: [{'index': int, 'width': int, 'height': int, 'name': str}]
    """
    cameras = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            # Попытка прочитать кадр для подтверждения работоспособности
            ret, _ = cap.read()
            if ret:
                cameras.append({
                    'index': i,
                    'width': w,
                    'height': h,
                    'name': f'Camera {i}',
                })
            cap.release()
    return cameras


def select_camera(auto_index: int = None) -> int:
    """
    Интерактивный выбор камеры в терминале.

    Если auto_index задан (не None), сразу возвращает его без интерактива.
    Иначе перечисляет камеры и просит пользователя выбрать.
    """
    if auto_index is not None:
        return auto_index

    print("\n" + "=" * 55)
    print("  ПОИСК КАМЕР...")
    print("=" * 55)

    cameras = enumerate_cameras()

    if not cameras:
        print("\n  Камеры не найдены!")
        print("  Проверьте подключение камеры и попробуйте снова.")
        sys.exit(1)

    print(f"\n  Найдено камер: {len(cameras)}\n")
    for cam in cameras:
        print(f"  [{cam['index']}]  {cam['name']}  —  {cam['width']}x{cam['height']}")

    print()
    print("=" * 55)

    while True:
        try:
            raw = input(f"  Выберите камеру [0-{cameras[-1]['index']}]: ").strip()
            idx = int(raw)
            # Проверяем что выбранный индекс есть в списке
            if any(c['index'] == idx for c in cameras):
                selected = next(c for c in cameras if c['index'] == idx)
                print(f"  ✓ Выбрана: {selected['name']} ({selected['width']}x{selected['height']})")
                return idx
            else:
                valid = ", ".join(str(c['index']) for c in cameras)
                print(f"  Нет камеры с индексом {idx}. Доступные: {valid}")
        except ValueError:
            print("  Введите число.")
        except (EOFError, KeyboardInterrupt):
            print("\n  Отмена.")
            sys.exit(0)
