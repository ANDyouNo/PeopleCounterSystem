"""
SQLite база данных.

Таблицы:
  presence_log    — интервалы присутствия людей (start → end)
  detections_raw  — сырые данные детекции (каждый N-й кадр)
  settings        — конфигурация системы (key-value)
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from backend.config_defaults import DEFAULT_SETTINGS, cast_value

DB_PATH = Path(__file__).parent.parent.parent / "data" / "people_counter.db"


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._init_default_settings()

    # ─── Schema ─────────────────────────────────────────────────

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS presence_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time  TEXT NOT NULL,
                end_time    TEXT,
                max_people  INTEGER NOT NULL DEFAULT 1,
                avg_people  REAL    NOT NULL DEFAULT 1.0,
                created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS detections_raw (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                people_count INTEGER NOT NULL,
                tracker_ids  TEXT,
                inference_ms REAL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key              TEXT PRIMARY KEY,
                value            TEXT NOT NULL,
                type             TEXT NOT NULL DEFAULT 'string',
                description      TEXT NOT NULL DEFAULT '',
                category         TEXT NOT NULL DEFAULT 'general',
                restart_required INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_presence_start ON presence_log(start_time);
            CREATE INDEX IF NOT EXISTS idx_presence_end   ON presence_log(end_time);
            CREATE INDEX IF NOT EXISTS idx_detections_ts  ON detections_raw(timestamp);
        """)
        self.conn.commit()

    def _init_default_settings(self):
        """Вставить дефолтные настройки если ключ ещё не существует."""
        for key, meta in DEFAULT_SETTINGS.items():
            self.conn.execute("""
                INSERT OR IGNORE INTO settings (key, value, type, description, category, restart_required)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                key,
                meta["value"],
                meta["type"],
                meta["description"],
                meta["category"],
                1 if meta.get("restart_required") else 0,
            ))
        self.conn.commit()

    # ─── Settings ───────────────────────────────────────────────

    def get_all_settings(self) -> dict:
        """Вернуть все настройки: { key: { value(typed), type, description, category, restart_required } }"""
        rows = self.conn.execute("SELECT * FROM settings ORDER BY category, key").fetchall()
        result = {}
        for r in rows:
            result[r["key"]] = {
                "value": cast_value(r["value"], r["type"]),
                "type": r["type"],
                "description": r["description"],
                "category": r["category"],
                "restart_required": bool(r["restart_required"]),
            }
        return result

    def get_settings_values(self) -> dict:
        """Вернуть только значения: { key: typed_value }"""
        rows = self.conn.execute("SELECT key, value, type FROM settings").fetchall()
        return {r["key"]: cast_value(r["value"], r["type"]) for r in rows}

    def set_setting(self, key: str, value: Any) -> bool:
        """Обновить одну настройку. Возвращает False если ключ не существует."""
        row = self.conn.execute(
            "SELECT type FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return False
        self.conn.execute(
            "UPDATE settings SET value = ? WHERE key = ?", (str(value), key))
        self.conn.commit()
        return True

    def set_settings(self, updates: dict) -> list[str]:
        """Обновить несколько настроек. Возвращает список обновлённых ключей."""
        updated = []
        for key, value in updates.items():
            if self.set_setting(key, value):
                updated.append(key)
        return updated

    # ─── Presence Log ────────────────────────────────────────────

    def start_presence(self, people_count: int = 1) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO presence_log (start_time, max_people, avg_people) VALUES (?, ?, ?)",
            (now, people_count, float(people_count)),
        )
        self.conn.commit()
        return cur.lastrowid

    def end_presence(self, row_id: int):
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE presence_log SET end_time = ? WHERE id = ?", (now, row_id))
        self.conn.commit()

    def update_presence_stats(self, row_id: int, max_people: int, avg_people: float):
        self.conn.execute(
            "UPDATE presence_log SET max_people = ?, avg_people = ? WHERE id = ?",
            (max_people, avg_people, row_id),
        )
        self.conn.commit()

    def get_open_presence(self) -> Optional[int]:
        row = self.conn.execute(
            "SELECT id FROM presence_log WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None

    # ─── Detections Raw ─────────────────────────────────────────

    def log_detection(self, people_count: int,
                      tracker_ids: Optional[str] = None,
                      inference_ms: Optional[float] = None):
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO detections_raw (timestamp, people_count, tracker_ids, inference_ms) "
            "VALUES (?, ?, ?, ?)",
            (now, people_count, tracker_ids, inference_ms),
        )

    def flush(self):
        self.conn.commit()

    # ─── Stats ───────────────────────────────────────────────────

    def get_today_summary(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
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
            "total_visits": row["total_visits"],
            "total_minutes": round(row["total_minutes"], 1),
            "max_people": row["max_people"],
            "avg_people": round(row["avg_people"], 1),
        }

    def get_daily_stats(self, days: int = 30) -> list:
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
            ORDER BY day ASC
        """, (str(-days),)).fetchall()
        return [dict(r) for r in rows]

    def get_hourly_stats(self, date: Optional[str] = None) -> list:
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
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
        return [dict(r) for r in rows]

    def get_monthly_stats(self, months: int = 12) -> list:
        rows = self.conn.execute("""
            SELECT
                strftime('%Y-%m', start_time) as month,
                COUNT(*) as visits,
                ROUND(SUM(
                    (julianday(COALESCE(end_time, datetime('now','localtime')))
                     - julianday(start_time)) * 24 * 60
                ), 1) as total_minutes,
                MAX(max_people) as max_people
            FROM presence_log
            WHERE start_time >= date('now', ? || ' months', 'localtime')
            GROUP BY strftime('%Y-%m', start_time)
            ORDER BY month ASC
        """, (str(-months),)).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.commit()
        self.conn.close()
