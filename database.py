"""
SQLite база данных для фиксации присутствия людей.

Таблицы:
  - presence_log: каждая запись = один интервал присутствия (вошёл → ушёл)
  - detections_raw: сырые данные — количество людей в каждом кадре детекции

Подробная документация: DB_SCHEMA.md
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_FILE = "people_counter.db"


class Database:
    """Обёртка над SQLite для логирования присутствия людей."""

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")  # Быстрее для конкурентных чтений
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS presence_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time  TEXT    NOT NULL,  -- ISO 8601: YYYY-MM-DDTHH:MM:SS
                end_time    TEXT,              -- NULL если человек ещё в зале
                max_people  INTEGER NOT NULL DEFAULT 1,
                avg_people  REAL    NOT NULL DEFAULT 1.0,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS detections_raw (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,  -- ISO 8601
                people_count INTEGER NOT NULL,
                tracker_ids TEXT,              -- JSON список ID трекера, например "[1,3,5]"
                inference_ms REAL              -- Время инференса в мс
            );

            CREATE INDEX IF NOT EXISTS idx_presence_start
                ON presence_log(start_time);

            CREATE INDEX IF NOT EXISTS idx_presence_end
                ON presence_log(end_time);

            CREATE INDEX IF NOT EXISTS idx_detections_ts
                ON detections_raw(timestamp);
        """)
        self.conn.commit()

    # ─── Presence Log (интервалы присутствия) ───

    def start_presence(self, people_count: int = 1) -> int:
        """
        Фиксирует начало присутствия.
        Возвращает id записи.
        """
        now = datetime.now().isoformat(timespec='seconds')
        cur = self.conn.execute(
            "INSERT INTO presence_log (start_time, max_people, avg_people) VALUES (?, ?, ?)",
            (now, people_count, float(people_count))
        )
        self.conn.commit()
        return cur.lastrowid

    def end_presence(self, row_id: int):
        """Фиксирует конец присутствия."""
        now = datetime.now().isoformat(timespec='seconds')
        self.conn.execute(
            "UPDATE presence_log SET end_time = ? WHERE id = ?",
            (now, row_id)
        )
        self.conn.commit()

    def update_presence_stats(self, row_id: int, max_people: int, avg_people: float):
        """Обновляет статистику для текущего интервала."""
        self.conn.execute(
            "UPDATE presence_log SET max_people = ?, avg_people = ? WHERE id = ?",
            (max_people, avg_people, row_id)
        )
        self.conn.commit()

    def get_open_presence(self) -> Optional[int]:
        """Возвращает id незакрытой сессии (end_time IS NULL), если есть."""
        row = self.conn.execute(
            "SELECT id FROM presence_log WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    # ─── Detections Raw (каждый кадр) ───

    def log_detection(self, people_count: int, tracker_ids: str = None,
                      inference_ms: float = None):
        """Записывает сырую детекцию (вызывается каждые N кадров)."""
        now = datetime.now().isoformat(timespec='seconds')
        self.conn.execute(
            "INSERT INTO detections_raw (timestamp, people_count, tracker_ids, inference_ms) "
            "VALUES (?, ?, ?, ?)",
            (now, people_count, tracker_ids, inference_ms)
        )
        # Коммит пачкой для производительности (каждые ~10 записей)
        # Вызывается из main loop, commit делается явно через flush()

    def flush(self):
        """Принудительный commit (вызывать периодически)."""
        self.conn.commit()

    # ─── Запросы для фронтенда ───

    def get_today_summary(self) -> dict:
        """
        Сводка за сегодня.
        Возвращает: {total_visits, total_minutes, max_people, avg_people}
        """
        today = datetime.now().strftime('%Y-%m-%d')
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total_visits,
                COALESCE(SUM(
                    (julianday(COALESCE(end_time, datetime('now','localtime')))
                     - julianday(start_time)) * 24 * 60
                ), 0) as total_minutes,
                COALESCE(MAX(max_people), 0) as max_people,
                COALESCE(AVG(avg_people), 0) as avg_people
            FROM presence_log
            WHERE start_time >= ?
        """, (today,)).fetchone()
        return {
            'total_visits': row[0],
            'total_minutes': round(row[1], 1),
            'max_people': row[2],
            'avg_people': round(row[3], 1),
        }

    # ─── Дополнительные запросы для веб-API ───

    def get_presence_history(self, hours: int = 24) -> list:
        """
        Список интервалов присутствия за последние N часов.
        Возвращает: [{id, start_time, end_time, max_people, avg_people, duration_min}, ...]
        """
        rows = self.conn.execute("""
            SELECT id, start_time, end_time, max_people, avg_people,
                   ROUND((julianday(COALESCE(end_time, datetime('now','localtime')))
                    - julianday(start_time)) * 24 * 60, 1) as duration_min
            FROM presence_log
            WHERE start_time >= datetime('now', ? || ' hours', 'localtime')
            ORDER BY start_time DESC
        """, (str(-hours),)).fetchall()
        return [
            {
                'id': r[0],
                'start_time': r[1],
                'end_time': r[2],
                'max_people': r[3],
                'avg_people': round(r[4], 1) if r[4] else 0,
                'duration_min': r[5] if r[5] else 0,
            }
            for r in rows
        ]

    def get_hourly_stats(self, date: str = None) -> list:
        """
        Почасовая статистика за конкретную дату (YYYY-MM-DD).
        Если date=None, берёт сегодня.
        Возвращает: [{hour, visits, total_minutes, peak_people}, ...]
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        next_date = date  # Для фильтрации берём start_time >= date
        rows = self.conn.execute("""
            SELECT
                CAST(strftime('%H', start_time) AS INTEGER) as hour,
                COUNT(*) as visits,
                ROUND(SUM(
                    (julianday(COALESCE(end_time, datetime('now','localtime')))
                     - julianday(start_time)) * 24 * 60
                ), 1) as total_minutes,
                MAX(max_people) as peak_people
            FROM presence_log
            WHERE start_time >= ? AND start_time < date(?, '+1 day')
            GROUP BY strftime('%H', start_time)
            ORDER BY hour
        """, (date, date)).fetchall()
        return [
            {
                'hour': r[0],
                'visits': r[1],
                'total_minutes': r[2] if r[2] else 0,
                'peak_people': r[3] if r[3] else 0,
            }
            for r in rows
        ]

    def get_current_status(self) -> dict:
        """
        Текущий статус: есть ли открытая сессия (люди в зале).
        Возвращает: {is_occupied, session_id, start_time, max_people}
        """
        row = self.conn.execute("""
            SELECT id, start_time, max_people
            FROM presence_log
            WHERE end_time IS NULL
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        if row:
            return {
                'is_occupied': True,
                'session_id': row[0],
                'start_time': row[1],
                'max_people': row[2],
            }
        return {
            'is_occupied': False,
            'session_id': None,
            'start_time': None,
            'max_people': 0,
        }

    def get_daily_stats(self, days: int = 7) -> list:
        """
        Ежедневная статистика за последние N дней.
        Возвращает: [{date, visits, total_minutes, max_people, avg_people}, ...]
        """
        rows = self.conn.execute("""
            SELECT
                date(start_time) as day,
                COUNT(*) as visits,
                ROUND(SUM(
                    (julianday(COALESCE(end_time, datetime('now','localtime')))
                     - julianday(start_time)) * 24 * 60
                ), 1) as total_minutes,
                MAX(max_people) as max_people,
                ROUND(AVG(avg_people), 1) as avg_people
            FROM presence_log
            WHERE start_time >= date('now', ? || ' days', 'localtime')
            GROUP BY date(start_time)
            ORDER BY day DESC
        """, (str(-days),)).fetchall()
        return [
            {
                'date': r[0],
                'visits': r[1],
                'total_minutes': r[2] if r[2] else 0,
                'max_people': r[3] if r[3] else 0,
                'avg_people': r[4] if r[4] else 0,
            }
            for r in rows
        ]

    def close(self):
        self.conn.commit()
        self.conn.close()
