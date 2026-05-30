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

            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medication_id INTEGER NOT NULL,
                reminder_time TEXT NOT NULL,
                FOREIGN KEY (medication_id) REFERENCES medications(id)
            );

            CREATE TABLE IF NOT EXISTS intake_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medication_id INTEGER NOT NULL,
                scheduled_time TEXT NOT NULL,
                taken_at TIMESTAMP,
                status TEXT DEFAULT 'pending' CHECK(status IN ('taken', 'skipped', 'pending')),
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
    """Добавляет время напоминания для лекарства (формат HH:MM)."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO schedules (medication_id, reminder_time) VALUES (?, ?)",
            (medication_id, reminder_time)
        )


def get_user_medications(user_id: int) -> list:
    """Возвращает активные лекарства пользователя."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT m.*, GROUP_CONCAT(s.reminder_time) as times
               FROM medications m
               LEFT JOIN schedules s ON s.medication_id = m.id
               WHERE m.user_id = ? AND m.active = 1
               GROUP BY m.id""",
            (user_id,)
        ).fetchall()


def get_all_schedules() -> list:
    """Возвращает все расписания для планировщика."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT s.reminder_time, m.name, m.dosage, m.meal_relation,
                      u.telegram_id, u.timezone, u.reminder_mode, s.medication_id
               FROM schedules s
               JOIN medications m ON m.id = s.medication_id
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
            "DELETE FROM schedules WHERE medication_id = ?",
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
               ORDER BY m.name, i.taken_at DESC, i.scheduled_time""",
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
    """Возвращает времена напоминаний для лекарства."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT reminder_time FROM schedules WHERE medication_id = ?",
            (medication_id,)
        ).fetchall()


def update_medication(medication_id: int, user_id: int, name: str, dosage: str,
                      meal_relation: str, times_per_day: int, new_times: list):
    """Обновляет лекарство и его расписание."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE medications SET name=?, dosage=?, meal_relation=?, times_per_day=?
               WHERE id=? AND user_id=?""",
            (name, dosage, meal_relation, times_per_day, medication_id, user_id)
        )
        conn.execute("DELETE FROM schedules WHERE medication_id=?", (medication_id,))
        for t in new_times:
            conn.execute(
                "INSERT INTO schedules (medication_id, reminder_time) VALUES (?, ?)",
                (medication_id, t)
            )


def log_intake(medication_id: int, scheduled_time: str, status: str):
    """Записывает факт приёма или пропуска лекарства."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO intake_log (medication_id, scheduled_time, status, taken_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
            (medication_id, scheduled_time, status)
        )
