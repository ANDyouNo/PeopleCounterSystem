# People Counter — Схема базы данных

SQLite база данных (`people_counter.db`) для фиксации присутствия людей.
Предназначена для последующего подключения веб-фронтенда (React, Tailwind и т.п.).

## Таблицы

### 1. `presence_log` — Интервалы присутствия

Каждая запись = один непрерывный интервал, когда в кадре были люди.
Интервал открывается при первом появлении человека и закрывается когда все люди покинули кадр (с учётом debounce-защиты от дребезга).

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INTEGER PK | Автоинкремент |
| `start_time` | TEXT NOT NULL | Начало присутствия, ISO 8601 (`YYYY-MM-DDTHH:MM:SS`) |
| `end_time` | TEXT | Конец присутствия. `NULL` = люди ещё в кадре |
| `max_people` | INTEGER NOT NULL | Максимум людей одновременно за этот интервал |
| `avg_people` | REAL NOT NULL | Среднее количество людей за интервал |
| `created_at` | TEXT NOT NULL | Время создания записи (автозаполнение) |

**Индексы:**
- `idx_presence_start` на `start_time` — быстрая фильтрация по дате
- `idx_presence_end` на `end_time` — поиск открытых сессий

**Типичные запросы для фронтенда:**

```sql
-- Все визиты за сегодня
SELECT * FROM presence_log
WHERE start_time >= date('now', 'localtime')
ORDER BY start_time DESC;

-- Сводка за сегодня: количество визитов, общее время, максимум людей
SELECT
    COUNT(*) as total_visits,
    COALESCE(SUM(
        (julianday(COALESCE(end_time, datetime('now','localtime')))
         - julianday(start_time)) * 24 * 60
    ), 0) as total_minutes,
    COALESCE(MAX(max_people), 0) as max_people,
    COALESCE(AVG(avg_people), 0) as avg_people
FROM presence_log
WHERE start_time >= date('now', 'localtime');

-- Визиты за конкретную дату
SELECT * FROM presence_log
WHERE start_time >= '2025-01-15' AND start_time < '2025-01-16'
ORDER BY start_time;

-- Визиты за последние 7 дней, сгруппированные по дням
SELECT
    date(start_time) as day,
    COUNT(*) as visits,
    SUM(
        (julianday(COALESCE(end_time, datetime('now','localtime')))
         - julianday(start_time)) * 24 * 60
    ) as total_minutes,
    MAX(max_people) as peak_people
FROM presence_log
WHERE start_time >= date('now', '-7 days', 'localtime')
GROUP BY date(start_time)
ORDER BY day;

-- Есть ли кто-то сейчас в зале?
SELECT id, start_time, max_people
FROM presence_log
WHERE end_time IS NULL
ORDER BY id DESC LIMIT 1;

-- Среднее время визита (в минутах) за последний месяц
SELECT AVG(
    (julianday(end_time) - julianday(start_time)) * 24 * 60
) as avg_visit_minutes
FROM presence_log
WHERE end_time IS NOT NULL
  AND start_time >= date('now', '-30 days', 'localtime');

-- Часовая разбивка визитов за сегодня (для графика)
SELECT
    strftime('%H', start_time) as hour,
    COUNT(*) as visits,
    MAX(max_people) as peak
FROM presence_log
WHERE start_time >= date('now', 'localtime')
GROUP BY strftime('%H', start_time)
ORDER BY hour;
```

### 2. `detections_raw` — Сырые данные детекции

Записывается каждые N кадров детекции (настраивается в `config.py` → `DB_LOG_EVERY_N_DETECTIONS`).
Полезно для детального анализа и построения графиков загруженности.

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INTEGER PK | Автоинкремент |
| `timestamp` | TEXT NOT NULL | Время детекции, ISO 8601 |
| `people_count` | INTEGER NOT NULL | Количество людей в кадре |
| `tracker_ids` | TEXT | JSON-массив ID трекера, например `"[1,3,5]"` |
| `inference_ms` | REAL | Время инференса модели в миллисекундах |

**Индексы:**
- `idx_detections_ts` на `timestamp`

**Типичные запросы:**

```sql
-- Последние 100 детекций
SELECT * FROM detections_raw
ORDER BY id DESC LIMIT 100;

-- Средняя загруженность по часам за сегодня (для графика)
SELECT
    strftime('%H', timestamp) as hour,
    AVG(people_count) as avg_people,
    MAX(people_count) as max_people
FROM detections_raw
WHERE timestamp >= date('now', 'localtime')
GROUP BY strftime('%H', timestamp)
ORDER BY hour;

-- Среднее время инференса (для мониторинга производительности)
SELECT AVG(inference_ms) as avg_ms, MAX(inference_ms) as max_ms
FROM detections_raw
WHERE timestamp >= datetime('now', '-1 hour', 'localtime');
```

## Настройки подключения

- **Файл:** `people_counter.db` (в корне проекта, настраивается в `config.py` → `DB_FILE`)
- **Режим журнала:** WAL (Write-Ahead Logging) — быстрее для параллельных чтений
- **Потокобезопасность:** `check_same_thread=False` — можно читать из другого потока

## REST API — Рекомендуемые эндпоинты для фронтенда

При создании веб-интерфейса рекомендуется реализовать следующие эндпоинты:

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/status` | Текущий статус: есть ли люди, сколько, длительность |
| GET | `/api/today` | Сводка за сегодня (вызывает `get_today_summary()`) |
| GET | `/api/history?date=YYYY-MM-DD` | Визиты за конкретную дату |
| GET | `/api/history?from=...&to=...` | Визиты за период |
| GET | `/api/stats/hourly?date=YYYY-MM-DD` | Почасовая статистика (для графика) |
| GET | `/api/stats/daily?days=7` | Ежедневная статистика за N дней |
| GET | `/api/detections?limit=100` | Последние сырые детекции |
| GET | `/api/performance` | Средние времена инференса |

## Примечания

- Все времена хранятся в локальном часовом поясе сервера (ISO 8601 без таймзоны)
- `end_time = NULL` означает, что интервал присутствия ещё не закрыт (люди в кадре)
- `tracker_ids` — JSON-строка, парсить через `json.loads()` в Python или `JSON.parse()` в JS
- Debounce-защита (`DEBOUNCE_FRAMES` в config.py) предотвращает ложное закрытие/открытие интервалов при кратковременной потере детекции
- WAL-режим позволяет читать БД из фронтенда не блокируя запись из основного процесса
