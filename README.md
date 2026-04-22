# People Counter System v4.0

Система подсчёта посетителей в реальном времени на основе компьютерного зрения.  
YOLOv8 детекция + ByteTrack трекинг + управление освещением через ESP8266 + веб-интерфейс.

---

## Возможности

- Детекция и подсчёт людей с веб-камеры (YOLOv8n / YOLOv8s)
- Трекинг посетителей через ByteTrack — каждый человек считается один раз
- MJPEG-превью камеры в браузере с оверлеем детекций
- WebSocket: состояние системы обновляется в реальном времени без перезагрузки
- Статистика в SQLite: посещения по часам, дням, месяцам
- Зоны исключения — рисуются прямо в браузере (холст поверх снимка камеры)
- Управление витринами через ESP8266 + PCA9685: 8 каналов PWM, плавное включение
- Управление общим освещением через второй ESP8266 + реле, с задержкой после витрин
- Принудительный (ручной) режим для каждой витрины и общего света
- Настройки хранятся в SQLite, часть применяется на лету без перезапуска
- Темы: светлая / тёмная / системная

---

## Стек

| Слой | Технология |
|---|---|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Детекция | YOLOv8 (Ultralytics), ONNX опционально |
| Трекинг | Supervision + ByteTrack |
| База данных | SQLite (через стандартный `sqlite3`) |
| Frontend | React 18 + TypeScript + Vite |
| Стили | Tailwind CSS + Radix UI |
| Графики | Recharts |
| ESP-прошивки | Arduino (ESP8266) |

---

## Требования

**Python:** 3.10 или новее  
**Node.js:** 18 или новее (для сборки фронтенда)  
**Камера:** любая USB-камера или встроенная

Для работы с ESP8266 — дополнительно:
- ESP8266 (NodeMCU / Wemos D1 Mini) × 2
- PCA9685 16-канальный PWM-контроллер (для витрин)
- Одноканальное реле 5 V (для общего света)

---

## Быстрый старт

### macOS / Linux

```bash
chmod +x start.sh
./start.sh          # prod-режим: собирает фронтенд и поднимает сервер
./start.sh dev      # dev-режим: Vite dev server (HMR) + FastAPI с --reload
```

### Windows

```bat
start.bat           # prod-режим
start.bat dev       # dev-режим
```

Скрипты при первом запуске автоматически:
1. Создают виртуальное окружение `.venv` и устанавливают Python-зависимости
2. Запускают `npm install` в папке `frontend/`
3. В prod-режиме собирают фронтенд (`npm run build`)

После запуска откройте в браузере:

| Режим | URL |
|---|---|
| prod | http://localhost:8000 |
| dev (фронтенд) | http://localhost:5173 |
| dev (API docs) | http://localhost:8000/docs |

При первом запуске модель YOLOv8n скачается автоматически (~6 MB).

---

## Структура проекта

```
PeopleCounterSystem/
├── backend/
│   ├── main.py                  # FastAPI приложение, lifespan-инициализация
│   ├── state.py                 # AppState — центральное хранилище состояния
│   ├── config_defaults.py       # Дефолтные значения всех настроек
│   ├── api/routes/
│   │   ├── stream.py            # GET /stream/video (MJPEG), WS /ws
│   │   ├── control.py           # POST /api/control/showcases/*, /light/*
│   │   ├── settings.py          # GET/PUT /api/settings
│   │   ├── stats.py             # GET /api/stats/{summary,daily,hourly,monthly}
│   │   └── zones.py             # GET/PUT /api/zones, GET /api/zones/snapshot
│   ├── core/
│   │   ├── detection_engine.py  # Фоновый поток детекции (YOLOv8 + ByteTrack)
│   │   ├── roi_manager.py       # Зоны исключения (загрузка, маска, фильтрация)
│   │   ├── showcase_controller.py  # UDP-управление витринами (ESP8266 + PCA9685)
│   │   ├── light_controller.py     # UDP-управление общим светом (ESP8266 + реле)
│   │   └── camera_utils.py      # Утилиты для работы с камерой
│   └── db/
│       └── database.py          # SQLite: схема, запись, статистика
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── DashboardPage.tsx   # Превью камеры, счётчики, статус ESP
│   │   │   ├── ControlPage.tsx     # Ручное управление витринами и светом
│   │   │   ├── AnalyticsPage.tsx   # Графики: день/час/месяц + кастомный календарь
│   │   │   ├── ZonesPage.tsx       # Редактор зон исключения (canvas)
│   │   │   └── SettingsPage.tsx    # Настройки системы
│   │   ├── api/client.ts           # Типы и fetch-обёртки
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts     # Auto-reconnect WebSocket хук
│   │   │   └── useTheme.ts         # Тема: light / dark / system
│   │   └── components/ui/          # Button, Card, Switch, Tabs, Toast…
│   ├── vite.config.ts              # Dev-прокси /api, /ws, /stream → :8000
│   └── package.json
├── esp8266/
│   ├── showcase_controller/
│   │   └── showcase_controller.ino  # Витрины: PCA9685, 8 каналов, fade-анимация
│   └── light_controller/
│       └── light_controller.ino     # Общий свет: реле, UDP-команды
├── data/                        # Создаётся автоматически
│   ├── people_counter.db        # SQLite база (посещения, детекции, настройки)
│   └── exclusion_zones.json     # Зоны исключения (сохраняются из веб-UI)
├── requirements.txt
├── start.sh
└── start.bat
```

---

## Настройки

Все настройки хранятся в SQLite и редактируются через вкладку **Settings** в веб-интерфейсе. Часть применяется на лету, часть требует перезапуска.

| Ключ | По умолчанию | Применяется | Описание |
|---|---|---|---|
| `camera_index` | 0 | перезапуск | Индекс камеры |
| `frame_width` | 640 | перезапуск | Ширина кадра |
| `frame_height` | 480 | перезапуск | Высота кадра |
| `model_size` | n | перезапуск | YOLOv8 размер: n / s / m |
| `inference_backend` | auto | перезапуск | auto / onnx / pytorch |
| `inference_size` | 320 | на лету | Размер входа модели |
| `confidence_threshold` | 0.4 | на лету | Порог уверенности |
| `iou_threshold` | 0.45 | на лету | Порог IoU |
| `skip_frames` | 1 | на лету | Детекция каждые N кадров |
| `max_fps` | 30 | на лету | Ограничение FPS |
| `debounce_frames` | 4 | перезапуск | Кадров до "человек ушёл" |
| `showcase_delay_on` | 3 | на лету | Задержка включения витрин (сек) |
| `showcase_delay_off` | 5 | на лету | Задержка выключения витрин (сек) |
| `showcase_count` | 8 | на лету | Количество витрин |
| `showcase_esp_enabled` | true | перезапуск | Включить контроллер витрин |
| `light_delay_after_showcases` | 5 | на лету | Задержка общего света после витрин (сек) |
| `light_delay_off` | 10 | на лету | Задержка выключения общего света (сек) |
| `light_esp_enabled` | true | перезапуск | Включить контроллер света |

---

## ESP8266 — прошивки

### Showcase Controller (`esp8266/showcase_controller/`)

Управляет 8 каналами LED-подсветки витрин через PCA9685 (PWM, 1000 Гц).

**Подключение PCA9685:**

| PCA9685 | ESP8266 |
|---|---|
| SDA | D2 (GPIO4) |
| SCL | D1 (GPIO5) |
| VCC | 3.3 V |
| GND | GND |

**UDP-команды** (порт 4211):

| Команда | Действие |
|---|---|
| `ON` | Включить все витрины последовательно (fade-in) |
| `OFF` | Выключить все (одновременный fade-out) |
| `FON:1,3,5` | Принудительно включить витрины 1, 3, 5 |
| `FOFF:1,3,5` | Снять принудительный режим с 1, 3, 5 |
| `MAP:1=3,2=0` | Переназначить каналы PCA9685 |

Контроллер анонсирует себя UDP-broadcast `PCOUNTER_SHOW` каждые 5 секунд (порт 4211).

### Light Controller (`esp8266/light_controller/`)

Управляет реле общего освещения.

**Подключение:** реле → D5 (GPIO14), активный уровень HIGH (настраивается).

**UDP-команды** (порт 4212):

| Команда | Действие |
|---|---|
| `ON` | Включить реле |
| `OFF` | Выключить реле |
| `FON` | Принудительно включить |
| `FOFF` | Снять принудительный режим |

Контроллер анонсирует себя `PCOUNTER_LIGHT` каждые 5 секунд (порт 4213).

**Важно:** добавьте в прошивку ваши Wi-Fi credentials:
```cpp
const char* ssid     = "YOUR_SSID";
const char* password = "YOUR_PASSWORD";
```

---

## API

Документация доступна интерактивно на http://localhost:8000/docs

| Метод | Путь | Описание |
|---|---|---|
| GET | `/stream/video` | MJPEG-поток камеры |
| WS | `/ws` | WebSocket состояния (push) |
| GET | `/api/settings` | Все настройки с метаданными |
| PUT | `/api/settings` | Обновить настройки |
| GET | `/api/control/state` | Полное состояние системы |
| POST | `/api/control/showcases/force_on` | Принудительно включить витрины |
| POST | `/api/control/showcases/force_off` | Снять принудительный режим |
| POST | `/api/control/showcases/{id}/toggle` | Переключить витрину |
| POST | `/api/control/light/force_on` | Принудительно включить свет |
| POST | `/api/control/light/force_off` | Снять принудительный режим света |
| POST | `/api/control/light/toggle` | Переключить свет |
| GET | `/api/stats/summary` | Сводка за сегодня |
| GET | `/api/stats/daily?days=30` | Статистика по дням |
| GET | `/api/stats/hourly?date=YYYY-MM-DD` | Статистика по часам |
| GET | `/api/stats/monthly?months=12` | Статистика по месяцам |
| GET | `/api/zones` | Зоны исключения |
| PUT | `/api/zones` | Сохранить зоны |
| GET | `/api/zones/snapshot` | Снимок камеры (JPEG) |

---

## Производительность

| Железо | Рекомендуемые настройки |
|---|---|
| Intel i3 (старый) | `inference_size=320`, `skip_frames=3`, ONNX |
| Intel i5/i7 | `inference_size=320`, `skip_frames=2` |
| Apple M1/M2 | `inference_size=640`, `skip_frames=1` |
| Raspberry Pi 4 | `inference_size=256`, `skip_frames=4`, ONNX |

**Ускорение через ONNX:**
```bash
# Один раз — экспортируем модель
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"
# Затем в настройках: inference_backend = onnx
```

---

## Troubleshooting

**Камера не найдена при старте**  
→ Проверьте индекс камеры в настройках (`camera_index`). Попробуйте 0, 1, 2.

**Чёрный экран в превью**  
→ Нормально при старте — система показывает заглушку "Camera starting…" пока инициализируется движок. Если экран чёрный дольше 10–15 секунд, перезапустите бэкенд.

**Высокое время инференса (>200 ms)**  
→ Уменьшите `inference_size` до 256, увеличьте `skip_frames`, экспортируйте модель в ONNX.

**Ложные срабатывания (человек то появляется, то пропадает)**  
→ Увеличьте `debounce_frames` до 6–8. Нарисуйте зоны исключения на проблемных областях (вкладка Zones).

**ESP8266 не обнаруживается**  
→ Убедитесь, что ESP и сервер в одной локальной сети. Wi-Fi sleep отключён прошивкой (`WIFI_NONE_SLEEP`). Проверьте `showcase_esp_enabled` / `light_esp_enabled` в настройках.

**`npm install` ошибка после переноса с другой ОС**  
→ Удалите `frontend/node_modules/` и `frontend/package-lock.json`, запустите скрипт снова — он всё пересоздаст автоматически.
