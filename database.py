import sqlite3
import logging
from contextlib import contextmanager

DB_PATH = "med_bot.db"

# Логгер для ошибок БД — пишет в файл
db_logger = logging.getLogger("db_errors")
db_logger.setLevel(logging.ERROR)
_fh = logging.FileHandler("db_errors.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s — %(message)s"))
db_logger.addHandler(_fh)


class DatabaseError(Exception):
    """Ошибка при работе с базой данных."""
    pass


@contextmanager
def get_connection():
    """Контекстный менеджер для подключения к БД."""
    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.Error as e:
        db_logger.error("Не удалось подключиться к БД: %s", e)
        raise DatabaseError("База данных недоступна") from e

    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        db_logger.error("Ошибка БД: %s", e)
        raise DatabaseError("Ошибка при работе с базой данных") from e
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Создаёт таблицы если их нет."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                timezone TEXT DEFAULT 'UTC',
                reminder_mode TEXT DEFAULT 'once',
                time_morning TEXT DEFAULT '09:00',
                time_lunch TEXT DEFAULT '12:00',
                time_evening TEXT DEFAULT '18:00',
                time_night TEXT DEFAULT '22:00',
                daily_plan_enabled INTEGER DEFAULT 1,
                daily_plan_time TEXT DEFAULT '08:00',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                dosage TEXT NOT NULL,
                meal_relation TEXT NOT NULL CHECK(meal_relation IN ('before', 'after', 'with', 'any')),
                times_per_day INTEGER NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS intake_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medication_id INTEGER NOT NULL,
                scheduled_time TEXT NOT NULL,
                taken_at TIMESTAMP,
                status TEXT DEFAULT 'pending' CHECK(status IN ('taken', 'skipped', 'pending')),
                FOREIGN KEY (medication_id) REFERENCES medications(id)
            );

            CREATE TABLE IF NOT EXISTS schedule_rules (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                medication_id INTEGER NOT NULL,
                reminder_time TEXT NOT NULL,
                frequency     TEXT NOT NULL DEFAULT 'daily',
                interval_days INTEGER,
                weekdays      TEXT,
                month_day     INTEGER,
                anchor_date   TEXT,
                FOREIGN KEY (medication_id) REFERENCES medications(id)
            );
        """)


def migrate():
    """Добавляет новые колонки если их нет (миграция)."""
    with get_connection() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
        if "timezone" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'UTC'")
        if "reminder_mode" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN reminder_mode TEXT DEFAULT 'once'")
        for col, default in [
            ("time_morning", "09:00"), ("time_lunch", "12:00"),
            ("time_evening", "18:00"), ("time_night", "22:00"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT '{default}'")

        if "daily_plan_enabled" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN daily_plan_enabled INTEGER DEFAULT 1")
        if "daily_plan_time" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN daily_plan_time TEXT DEFAULT '08:00'")

        sr_cols = [r[1] for r in conn.execute("PRAGMA table_info(schedule_rules)")]
        if "dosage" not in sr_cols:
            conn.execute("ALTER TABLE schedule_rules ADD COLUMN dosage TEXT DEFAULT NULL")

        # Дропаем устаревшую таблицу schedules (данные давно в schedule_rules)
        conn.execute("DROP TABLE IF EXISTS schedules")


def get_or_create_user(telegram_id: int, username: str = None) -> int:
    """Возвращает id пользователя, создаёт если не существует."""
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if user:
            return user["id"]
        conn.execute(
            "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
            (telegram_id, username)
        )
        return conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()["id"]


def get_reminder_mode(telegram_id: int) -> str:
    """Возвращает режим напоминаний: once | repeat."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT reminder_mode FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return row["reminder_mode"] if row else "once"


def set_reminder_mode(telegram_id: int, mode: str):
    """Устанавливает режим напоминаний."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET reminder_mode = ? WHERE telegram_id = ?",
            (mode, telegram_id)
        )


def set_user_timezone(telegram_id: int, timezone: str):
    """Сохраняет часовой пояс пользователя."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET timezone = ? WHERE telegram_id = ?",
            (timezone, telegram_id)
        )


def get_user_timezone(telegram_id: int) -> str:
    """Возвращает часовой пояс пользователя."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT timezone FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return row["timezone"] if row else "UTC"


def get_user_time_presets(telegram_id: int) -> dict:
    """Возвращает пресеты времени пользователя {morning, lunch, evening, night}."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT time_morning, time_lunch, time_evening, time_night FROM users WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()
        if row:
            return {
                "morning": row["time_morning"] or "09:00",
                "lunch":   row["time_lunch"]   or "12:00",
                "evening": row["time_evening"] or "18:00",
                "night":   row["time_night"]   or "22:00",
            }
        return {"morning": "09:00", "lunch": "12:00", "evening": "18:00", "night": "22:00"}


def set_user_time_preset(telegram_id: int, slot: str, time: str):
    """Обновляет один пресет времени пользователя."""
    col_map = {"morning": "time_morning", "lunch": "time_lunch",
               "evening": "time_evening", "night": "time_night"}
    col = col_map.get(slot)
    if not col:
        raise ValueError(f"Unknown slot: {slot}")
    with get_connection() as conn:
        conn.execute(f"UPDATE users SET {col} = ? WHERE telegram_id = ?", (time, telegram_id))


def count_active_medications(user_id: int) -> int:
    """Возвращает количество активных лекарств пользователя."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM medications WHERE user_id = ? AND active = 1",
            (user_id,)
        ).fetchone()
        return row[0]


def add_medication(user_id: int, name: str, dosage: str,
                   meal_relation: str, times_per_day: int) -> int:
    """Добавляет лекарство и возвращает его id."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO medications (user_id, name, dosage, meal_relation, times_per_day)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, name, dosage, meal_relation, times_per_day)
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def add_schedule(medication_id: int, reminder_time: str):
    """Добавляет ежедневное напоминание (обратная совместимость)."""
    add_schedule_rule(medication_id, reminder_time, "daily")


def add_schedule_rule(medication_id: int, reminder_time: str, frequency: str,
                      interval_days: int = None, weekdays: str = None,
                      month_day: int = None, anchor_date: str = None, dosage: str = None):
    """Добавляет правило напоминания в schedule_rules."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO schedule_rules
               (medication_id, reminder_time, frequency, interval_days, weekdays, month_day, anchor_date, dosage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (medication_id, reminder_time, frequency, interval_days, weekdays, month_day, anchor_date, dosage)
        )


def get_user_medications(user_id: int) -> list:
    """Возвращает активные лекарства пользователя."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM medications WHERE user_id = ? AND active = 1 ORDER BY id",
            (user_id,)
        ).fetchall()


def get_all_schedules() -> list:
    """Возвращает все правила расписания для планировщика."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT sr.reminder_time, sr.frequency, sr.interval_days,
                      sr.weekdays, sr.month_day, sr.anchor_date,
                      m.name, m.dosage AS med_dosage, m.meal_relation,
                      u.telegram_id, u.timezone, u.reminder_mode, sr.medication_id,
                      sr.dosage AS rule_dosage
               FROM schedule_rules sr
               JOIN medications m ON m.id = sr.medication_id
               JOIN users u ON u.id = m.user_id
               WHERE m.active = 1"""
        ).fetchall()


def deactivate_medication(medication_id: int, user_id: int):
    """Деактивирует лекарство и удаляет его расписание."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE medications SET active = 0 WHERE id = ? AND user_id = ?",
            (medication_id, user_id)
        )
        conn.execute(
            "DELETE FROM schedule_rules WHERE medication_id = ?",
            (medication_id,)
        )


def get_today_stats(user_id: int, start_utc: str, end_utc: str) -> list:
    """Возвращает статистику приёмов за сегодня (диапазон в UTC)."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT m.name, m.dosage, i.scheduled_time, i.status, i.taken_at
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               WHERE m.user_id = ?
               AND i.taken_at >= ? AND i.taken_at < ?
               ORDER BY i.taken_at""",
            (user_id, start_utc, end_utc)
        ).fetchall()


def get_history_detailed(user_id: int, since_utc: str) -> list:
    """Возвращает детальную историю начиная с since_utc (UTC строка)."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT m.name, m.dosage, m.id as med_id,
                      i.scheduled_time,
                      i.status,
                      i.taken_at
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               WHERE m.user_id = ?
               AND i.taken_at >= ?
               ORDER BY i.taken_at DESC, m.name, i.scheduled_time""",
            (user_id, since_utc)
        ).fetchall()


def get_history_by_days(user_id: int, days: int = 7) -> list:
    """Возвращает статистику по дням для каждого лекарства."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT m.name, m.dosage,
                      date(i.taken_at) as day,
                      SUM(CASE WHEN i.status = 'taken' THEN 1 ELSE 0 END) as taken,
                      SUM(CASE WHEN i.status = 'skipped' THEN 1 ELSE 0 END) as skipped,
                      COUNT(*) as total
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               WHERE m.user_id = ?
               AND i.taken_at >= date('now', ? || ' days')
               GROUP BY m.id, m.name, date(i.taken_at)
               ORDER BY m.name, day DESC""",
            (user_id, f"-{days}")
        ).fetchall()


def get_history(user_id: int, days: int = 7) -> list:
    """Возвращает статистику приёмов за последние N дней."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT m.name,
                      COUNT(*) as total,
                      SUM(CASE WHEN i.status = 'taken' THEN 1 ELSE 0 END) as taken,
                      SUM(CASE WHEN i.status = 'skipped' THEN 1 ELSE 0 END) as skipped
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               WHERE m.user_id = ?
               AND i.taken_at >= date('now', ? || ' days')
               GROUP BY m.id, m.name
               ORDER BY m.name""",
            (user_id, f"-{days}")
        ).fetchall()


def get_medication_by_id(medication_id: int, user_id: int):
    """Возвращает лекарство по id."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM medications WHERE id = ? AND user_id = ?",
            (medication_id, user_id)
        ).fetchone()


def get_schedules_by_medication(medication_id: int) -> list:
    """Возвращает правила расписания для лекарства."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT reminder_time, frequency, interval_days, weekdays, month_day, anchor_date, dosage
               FROM schedule_rules WHERE medication_id = ?""",
            (medication_id,)
        ).fetchall()


def update_medication(medication_id: int, user_id: int, name: str, dosage: str,
                      meal_relation: str, times_per_day: int, new_rules: list):
    """Обновляет лекарство и его расписание. new_rules — список dict с полями rule."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE medications SET name=?, dosage=?, meal_relation=?, times_per_day=?
               WHERE id=? AND user_id=?""",
            (name, dosage, meal_relation, times_per_day, medication_id, user_id)
        )
        conn.execute("DELETE FROM schedule_rules WHERE medication_id=?", (medication_id,))
        for rule in new_rules:
            conn.execute(
                """INSERT INTO schedule_rules
                   (medication_id, reminder_time, frequency, interval_days, weekdays, month_day, anchor_date, dosage)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (medication_id, rule["reminder_time"], rule.get("frequency", "daily"),
                 rule.get("interval_days"), rule.get("weekdays"),
                 rule.get("month_day"), rule.get("anchor_date"), rule.get("dosage"))
            )


def get_daily_plan_settings(telegram_id: int) -> dict:
    """Возвращает настройки плана дня: {enabled, time}."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT daily_plan_enabled, daily_plan_time FROM users WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()
        if row:
            return {"enabled": bool(row["daily_plan_enabled"]), "time": row["daily_plan_time"] or "08:00"}
        return {"enabled": True, "time": "08:00"}


def set_daily_plan_enabled(telegram_id: int, enabled: bool):
    """Включает или выключает план дня."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET daily_plan_enabled = ? WHERE telegram_id = ?",
            (1 if enabled else 0, telegram_id)
        )


def set_daily_plan_time(telegram_id: int, time_str: str):
    """Устанавливает время отправки плана дня."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET daily_plan_time = ? WHERE telegram_id = ?",
            (time_str, telegram_id)
        )


def get_schedules_for_user(telegram_id: int) -> list:
    """Возвращает все активные правила расписания для одного пользователя."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT u.telegram_id, u.timezone,
                      m.id AS medication_id, m.name, m.dosage AS med_dosage, m.meal_relation,
                      sr.reminder_time, sr.frequency, sr.interval_days,
                      sr.weekdays, sr.month_day, sr.anchor_date, sr.dosage AS rule_dosage
               FROM users u
               JOIN medications m ON m.user_id = u.id AND m.active = 1
               JOIN schedule_rules sr ON sr.medication_id = m.id
               WHERE u.telegram_id = ?
               ORDER BY m.id, sr.reminder_time""",
            (telegram_id,)
        ).fetchall()


def get_users_with_daily_plan() -> list:
    """Возвращает строки schedule_rules для пользователей с включённым планом дня."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT u.telegram_id, u.timezone, u.daily_plan_time,
                      m.id AS medication_id, m.name, m.dosage AS med_dosage, m.meal_relation,
                      sr.reminder_time, sr.frequency, sr.interval_days,
                      sr.weekdays, sr.month_day, sr.anchor_date, sr.dosage AS rule_dosage
               FROM users u
               JOIN medications m ON m.user_id = u.id AND m.active = 1
               JOIN schedule_rules sr ON sr.medication_id = m.id
               WHERE u.daily_plan_enabled = 1
               ORDER BY u.telegram_id, m.id, sr.reminder_time"""
        ).fetchall()


def delete_user_data(telegram_id: int) -> list:
    """Удаляет все данные пользователя. Возвращает список ID удалённых лекарств."""
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not user:
            return []
        user_id = user["id"]
        med_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM medications WHERE user_id = ?", (user_id,)
        ).fetchall()]
        if med_ids:
            placeholders = ",".join("?" * len(med_ids))
            conn.execute(f"DELETE FROM intake_log WHERE medication_id IN ({placeholders})", med_ids)
            conn.execute(f"DELETE FROM schedule_rules WHERE medication_id IN ({placeholders})", med_ids)
            conn.execute("DELETE FROM medications WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
        return med_ids


def get_admin_stats() -> dict:
    """Возвращает статистику для админ-панели."""
    with get_connection() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_meds = conn.execute(
            "SELECT COUNT(*) FROM medications WHERE active = 1"
        ).fetchone()[0]
        active_today = conn.execute(
            """SELECT COUNT(DISTINCT m.user_id) FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               WHERE date(i.taken_at) = date('now')"""
        ).fetchone()[0]
        return {"total_users": total_users, "total_meds": total_meds, "active_today": active_today}


def get_today_intake_statuses(telegram_id: int) -> dict:
    """Возвращает {(medication_id, scheduled_time): status} для сегодняшних записей."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT i.medication_id, i.scheduled_time, i.status
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               JOIN users u ON u.id = m.user_id
               WHERE u.telegram_id = ? AND date(i.taken_at) = date('now')""",
            (telegram_id,)
        ).fetchall()
    return {(r["medication_id"], r["scheduled_time"]): r["status"] for r in rows}


def log_intake(medication_id: int, scheduled_time: str, status: str):
    """Записывает факт приёма или пропуска лекарства. Обновляет запись если уже есть за сегодня."""
    with get_connection() as conn:
        existing = conn.execute(
            """SELECT id FROM intake_log
               WHERE medication_id = ? AND scheduled_time = ? AND date(taken_at) = date('now')""",
            (medication_id, scheduled_time)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE intake_log SET status = ?, taken_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, existing["id"])
            )
        else:
            conn.execute(
                """INSERT INTO intake_log (medication_id, scheduled_time, status, taken_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (medication_id, scheduled_time, status)
            )
