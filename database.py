import sqlite3
import logging
from contextlib import contextmanager

DB_PATH = "med_bot.db"

# Логгер для ошибок БД — пишет в файл
db_logger = logging.getLogger("db_errors")
db_logger.setLevel(logging.ERROR)
db_logger.propagate = False  # не дублировать ошибки БД в root-логгер (консоль)
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
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
    except sqlite3.Error as e:
        db_logger.error("Не удалось подключиться к БД: %s", e)
        raise DatabaseError("База данных недоступна") from e

    conn.row_factory = sqlite3.Row
    # WAL — параллельные чтение/запись (планировщик + пользователь);
    # busy_timeout — ждать снятия блокировки вместо мгновенного "database is locked";
    # foreign_keys — включить проверку внешних ключей (per-connection).
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
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
                caregiver_enabled INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS dependents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                dosage TEXT NOT NULL,
                meal_relation TEXT NOT NULL CHECK(meal_relation IN ('before', 'after', 'with', 'any')),
                times_per_day INTEGER NOT NULL,
                active INTEGER DEFAULT 1,
                dependent_id INTEGER DEFAULT NULL,
                stock_qty REAL DEFAULT NULL,
                units_per_dose REAL DEFAULT 1,
                low_stock_days INTEGER DEFAULT 5,
                paused INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (dependent_id) REFERENCES dependents(id)
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

            CREATE INDEX IF NOT EXISTS idx_medications_user_active
                ON medications(user_id, active);
            CREATE INDEX IF NOT EXISTS idx_medications_dependent
                ON medications(dependent_id);
            CREATE INDEX IF NOT EXISTS idx_schedule_rules_medication
                ON schedule_rules(medication_id);
            CREATE INDEX IF NOT EXISTS idx_intake_log_medication
                ON intake_log(medication_id, scheduled_time);
            CREATE INDEX IF NOT EXISTS idx_intake_log_taken_at
                ON intake_log(taken_at);
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

        if "caregiver_enabled" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN caregiver_enabled INTEGER DEFAULT 0")

        # dependents создаётся в init_db() (вызывается до migrate), поэтому здесь
        # достаточно добавить ссылочную колонку для старых БД.
        med_cols = [r[1] for r in conn.execute("PRAGMA table_info(medications)")]
        if "dependent_id" not in med_cols:
            conn.execute("ALTER TABLE medications ADD COLUMN dependent_id INTEGER DEFAULT NULL REFERENCES dependents(id)")
        # F5 — учёт запаса таблеток
        if "stock_qty" not in med_cols:
            conn.execute("ALTER TABLE medications ADD COLUMN stock_qty REAL DEFAULT NULL")
        if "units_per_dose" not in med_cols:
            conn.execute("ALTER TABLE medications ADD COLUMN units_per_dose REAL DEFAULT 1")
        if "low_stock_days" not in med_cols:
            conn.execute("ALTER TABLE medications ADD COLUMN low_stock_days INTEGER DEFAULT 5")
        # F4 — пауза лекарства (временное отключение без удаления)
        if "paused" not in med_cols:
            conn.execute("ALTER TABLE medications ADD COLUMN paused INTEGER DEFAULT 0")

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


def set_user_time_preset(telegram_id: int, slot: str, time: str) -> int:
    """Обновляет пресет времени и переносит существующие правила с прежнего времени на новое.

    Слоты хранятся в schedule_rules как конкретное время (снимок пресета на момент
    создания). Чтобы смена пресета «прокидывалась» в напоминания/список/план, все
    активные правила пользователя с reminder_time == старое значение пресета
    обновляются на новое. Возвращает число обновлённых правил.
    """
    col_map = {"morning": "time_morning", "lunch": "time_lunch",
               "evening": "time_evening", "night": "time_night"}
    col = col_map.get(slot)
    if not col:
        raise ValueError(f"Unknown slot: {slot}")
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT id, {col} AS old FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if row is None:
            return 0
        old_time, user_id = row["old"], row["id"]
        conn.execute(f"UPDATE users SET {col} = ? WHERE telegram_id = ?", (time, telegram_id))
        if not old_time or old_time == time:
            return 0
        cur = conn.execute(
            """UPDATE schedule_rules SET reminder_time = ?
               WHERE reminder_time = ?
                 AND medication_id IN (
                     SELECT id FROM medications WHERE user_id = ? AND active = 1
                 )""",
            (time, old_time, user_id)
        )
        return cur.rowcount


def count_active_medications(user_id: int, dependent_id: int = None) -> int:
    """Возвращает количество активных лекарств для user_id (dependent_id=None — для себя)."""
    with get_connection() as conn:
        if dependent_id is None:
            row = conn.execute(
                "SELECT COUNT(*) FROM medications WHERE user_id = ? AND active = 1 AND dependent_id IS NULL",
                (user_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM medications WHERE user_id = ? AND active = 1 AND dependent_id = ?",
                (user_id, dependent_id)
            ).fetchone()
        return row[0]


def get_caregiver_mode(telegram_id: int) -> bool:
    """Возвращает True если caregiver-режим включён."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT caregiver_enabled FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return bool(row["caregiver_enabled"]) if row else False


def set_caregiver_mode(telegram_id: int, enabled: bool):
    """Включает или выключает caregiver-режим."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET caregiver_enabled = ? WHERE telegram_id = ?",
            (1 if enabled else 0, telegram_id)
        )


def get_dependents(telegram_id: int) -> list:
    """Возвращает список подопечных пользователя [{id, name}, ...]."""
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not user:
            return []
        return [dict(r) for r in conn.execute(
            "SELECT id, name FROM dependents WHERE user_id = ? ORDER BY id",
            (user["id"],)
        ).fetchall()]


def count_dependents(telegram_id: int) -> int:
    """Возвращает количество подопечных пользователя."""
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not user:
            return 0
        return conn.execute(
            "SELECT COUNT(*) FROM dependents WHERE user_id = ?", (user["id"],)
        ).fetchone()[0]


def add_dependent(telegram_id: int, name: str) -> int:
    """Добавляет подопечного. Возвращает id новой записи."""
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not user:
            raise DatabaseError("Пользователь не найден")
        conn.execute(
            "INSERT INTO dependents (user_id, name) VALUES (?, ?)", (user["id"], name)
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def delete_dependent(telegram_id: int, dependent_id: int) -> list:
    """Удаляет подопечного и деактивирует его лекарства. Возвращает список ID лекарств."""
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not user:
            return []
        user_id = user["id"]
        dep = conn.execute(
            "SELECT id FROM dependents WHERE id = ? AND user_id = ?", (dependent_id, user_id)
        ).fetchone()
        if not dep:
            return []
        med_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM medications WHERE user_id = ? AND dependent_id = ?",
            (user_id, dependent_id)
        ).fetchall()]
        if med_ids:
            placeholders = ",".join("?" * len(med_ids))
            conn.execute(f"DELETE FROM intake_log WHERE medication_id IN ({placeholders})", med_ids)
            conn.execute(f"DELETE FROM schedule_rules WHERE medication_id IN ({placeholders})", med_ids)
            # dependent_id = NULL обязательно: иначе DELETE подопечного нарушит FK
            conn.execute(
                "UPDATE medications SET active = 0, dependent_id = NULL WHERE dependent_id = ? AND user_id = ?",
                (dependent_id, user_id)
            )
        conn.execute("DELETE FROM dependents WHERE id = ?", (dependent_id,))
        return med_ids


def add_medication(user_id: int, name: str, dosage: str,
                   meal_relation: str, times_per_day: int,
                   dependent_id: int = None) -> int:
    """Добавляет лекарство и возвращает его id."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO medications (user_id, name, dosage, meal_relation, times_per_day, dependent_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, name, dosage, meal_relation, times_per_day, dependent_id)
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
    """Возвращает активные лекарства пользователя с именем подопечного."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT m.*, d.name AS dependent_name
               FROM medications m
               LEFT JOIN dependents d ON d.id = m.dependent_id
               WHERE m.user_id = ? AND m.active = 1
               ORDER BY m.id""",
            (user_id,)
        ).fetchall()


def get_active_schedule_rows() -> list:
    """Все правила расписания активных лекарств + поля пользователя — один проход.

    Покрывает и напоминания (reminder_mode), и план дня (daily_plan_enabled /
    daily_plan_time). Фильтрация по плану дня выполняется в Python, без второго запроса.
    """
    with get_connection() as conn:
        return conn.execute(
            """SELECT u.telegram_id, u.timezone, u.reminder_mode,
                      u.daily_plan_enabled, u.daily_plan_time,
                      m.id AS medication_id, m.name, m.dosage AS med_dosage, m.meal_relation,
                      sr.reminder_time, sr.frequency, sr.interval_days,
                      sr.weekdays, sr.month_day, sr.anchor_date, sr.dosage AS rule_dosage,
                      d.name AS dependent_name
               FROM schedule_rules sr
               JOIN medications m ON m.id = sr.medication_id
               JOIN users u ON u.id = m.user_id
               LEFT JOIN dependents d ON d.id = m.dependent_id
               WHERE m.active = 1 AND m.paused = 0
               ORDER BY u.telegram_id, m.id, sr.reminder_time"""
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
                      i.scheduled_time, i.status, i.taken_at,
                      d.name AS dependent_name
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               LEFT JOIN dependents d ON d.id = m.dependent_id
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


def set_medication_paused(medication_id: int, user_id: int, paused: bool):
    """Ставит лекарство на паузу / снимает с паузы (F4). На паузе не шлёт напоминания и не входит в adherence."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE medications SET paused = ? WHERE id = ? AND user_id = ?",
            (1 if paused else 0, medication_id, user_id)
        )


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


def get_rules_grouped_for_user(user_id: int) -> dict:
    """Возвращает {medication_id: [rule, ...]} для всех активных лекарств пользователя одним запросом.

    Заменяет N+1 (get_schedules_by_medication в цикле) при рендере списка лекарств.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT sr.medication_id, sr.reminder_time, sr.frequency,
                      sr.interval_days, sr.weekdays, sr.month_day, sr.anchor_date, sr.dosage
               FROM schedule_rules sr
               JOIN medications m ON m.id = sr.medication_id
               WHERE m.user_id = ? AND m.active = 1
               ORDER BY sr.medication_id""",
            (user_id,)
        ).fetchall()
    grouped: dict = {}
    for r in rows:
        grouped.setdefault(r["medication_id"], []).append(r)
    return grouped


# ── Соблюдение режима / adherence (F3) ──────────────────────────────────────

def get_adherence_rules(user_id: int) -> list:
    """Правила активных лекарств пользователя + created_at/имя/подопечный (F3).

    Используется для знаменателя adherence: по этим правилам считаются «положенные»
    приёмы за период (schedule_utils.count_due_by_medication), с клампом по created_at.
    """
    with get_connection() as conn:
        return conn.execute(
            """SELECT m.id AS medication_id, m.name, m.dosage AS med_dosage,
                      m.created_at, d.name AS dependent_name,
                      sr.reminder_time, sr.frequency, sr.interval_days,
                      sr.weekdays, sr.month_day, sr.anchor_date
               FROM medications m
               JOIN schedule_rules sr ON sr.medication_id = m.id
               LEFT JOIN dependents d ON d.id = m.dependent_id
               WHERE m.user_id = ? AND m.active = 1 AND m.paused = 0
               ORDER BY m.id""",
            (user_id,)
        ).fetchall()


def get_taken_intakes(user_id: int, start_utc: str, end_utc: str) -> list:
    """(medication_id, taken_at) для status='taken' в окне — для календаря отчёта врача (F1).

    taken_at в UTC; потребитель конвертирует в локальную дату пользователя и бакетит по дням.
    """
    with get_connection() as conn:
        return conn.execute(
            """SELECT i.medication_id AS mid, i.taken_at
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               WHERE m.user_id = ? AND i.status = 'taken'
                 AND i.taken_at >= ? AND i.taken_at < ?""",
            (user_id, start_utc, end_utc)
        ).fetchall()


def get_taken_counts(user_id: int, start_utc: str, end_utc: str) -> dict:
    """{medication_id: число приёмов status='taken' за [start_utc, end_utc)} — числитель adherence (F3)."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT i.medication_id AS mid, COUNT(*) AS cnt
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               WHERE m.user_id = ? AND i.status = 'taken'
                 AND i.taken_at >= ? AND i.taken_at < ?
               GROUP BY i.medication_id""",
            (user_id, start_utc, end_utc)
        ).fetchall()
    return {r["mid"]: r["cnt"] for r in rows}


def get_streak_rows(user_id: int) -> list:
    """Правила активных непаузных лекарств + dependent_id/имя/created_at — для серий (F2).

    Группируются по подопечному (dependent_id) в streak.streaks_by_subject:
    серия считается отдельно для владельца и каждого подопечного.
    """
    with get_connection() as conn:
        return conn.execute(
            """SELECT m.id AS medication_id, m.dependent_id, m.created_at,
                      d.name AS dependent_name,
                      sr.reminder_time, sr.frequency, sr.interval_days,
                      sr.weekdays, sr.month_day, sr.anchor_date
               FROM medications m
               JOIN schedule_rules sr ON sr.medication_id = m.id
               LEFT JOIN dependents d ON d.id = m.dependent_id
               WHERE m.user_id = ? AND m.active = 1 AND m.paused = 0
               ORDER BY m.id""",
            (user_id,)
        ).fetchall()


def get_intake_statuses_window(user_id: int, start_utc: str, end_utc: str) -> list:
    """Записи intake_log (mid, scheduled_time, status, taken_at) пользователя за окно — для серий (F2)."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT i.medication_id, i.scheduled_time, i.status, i.taken_at
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               WHERE m.user_id = ? AND i.taken_at >= ? AND i.taken_at < ?""",
            (user_id, start_utc, end_utc)
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


def get_user_settings_row(telegram_id: int):
    """Возвращает строку настроек пользователя одним запросом (для экрана /settings)."""
    with get_connection() as conn:
        return conn.execute(
            """SELECT timezone, reminder_mode,
                      time_morning, time_lunch, time_evening, time_night,
                      daily_plan_enabled, daily_plan_time, caregiver_enabled
               FROM users WHERE telegram_id = ?""",
            (telegram_id,)
        ).fetchone()


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
                      sr.weekdays, sr.month_day, sr.anchor_date, sr.dosage AS rule_dosage,
                      d.name AS dependent_name
               FROM users u
               JOIN medications m ON m.user_id = u.id AND m.active = 1
               JOIN schedule_rules sr ON sr.medication_id = m.id
               LEFT JOIN dependents d ON d.id = m.dependent_id
               WHERE u.telegram_id = ? AND m.paused = 0
               ORDER BY m.id, sr.reminder_time""",
            (telegram_id,)
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
        conn.execute("DELETE FROM dependents WHERE user_id = ?", (user_id,))
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


def get_today_intake_statuses(telegram_id: int, start_utc: str, end_utc: str) -> dict:
    """Возвращает {(medication_id, scheduled_time): status} для записей в локальных сутках пользователя.

    Диапазон [start_utc, end_utc) задаётся в UTC и соответствует «сегодня» в TZ пользователя.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT i.medication_id, i.scheduled_time, i.status
               FROM intake_log i
               JOIN medications m ON m.id = i.medication_id
               JOIN users u ON u.id = m.user_id
               WHERE u.telegram_id = ? AND i.taken_at >= ? AND i.taken_at < ?""",
            (telegram_id, start_utc, end_utc)
        ).fetchall()
    return {(r["medication_id"], r["scheduled_time"]): r["status"] for r in rows}


def log_intake(medication_id: int, scheduled_time: str, status: str,
               start_utc: str, end_utc: str):
    """Записывает факт приёма или пропуска лекарства. Обновляет запись если уже есть за сегодня.

    «Сегодня» определяется диапазоном [start_utc, end_utc) в TZ пользователя.
    Возвращает прежний статус записи за сегодня (или None, если записи не было) —
    нужно для идемпотентного списания запаса (F5).
    """
    with get_connection() as conn:
        existing = conn.execute(
            """SELECT id, status FROM intake_log
               WHERE medication_id = ? AND scheduled_time = ?
               AND taken_at >= ? AND taken_at < ?""",
            (medication_id, scheduled_time, start_utc, end_utc)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE intake_log SET status = ?, taken_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, existing["id"])
            )
            return existing["status"]
        conn.execute(
            """INSERT INTO intake_log (medication_id, scheduled_time, status, taken_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
            (medication_id, scheduled_time, status)
        )
        return None


# ── Учёт запаса таблеток (F5) ───────────────────────────────────────────────

def set_medication_stock(medication_id: int, user_id: int, stock_qty: float):
    """Устанавливает остаток (включает трекинг). Для начального ввода и пополнения (absolute)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE medications SET stock_qty = ? WHERE id = ? AND user_id = ?",
            (stock_qty, medication_id, user_id)
        )


def add_medication_stock(medication_id: int, user_id: int, amount: float):
    """Прибавляет amount к остатку (пополнение упаковкой). Если трекинг был выключен — включает."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT stock_qty FROM medications WHERE id = ? AND user_id = ?",
            (medication_id, user_id)
        ).fetchone()
        base = (row["stock_qty"] if row and row["stock_qty"] is not None else 0)
        conn.execute(
            "UPDATE medications SET stock_qty = ? WHERE id = ? AND user_id = ?",
            (base + amount, medication_id, user_id)
        )


def set_units_per_dose(medication_id: int, user_id: int, units: float):
    """Устанавливает расход единиц за один приём."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE medications SET units_per_dose = ? WHERE id = ? AND user_id = ?",
            (units, medication_id, user_id)
        )


def set_low_stock_days(medication_id: int, user_id: int, days: int):
    """Устанавливает порог предупреждения (в днях)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE medications SET low_stock_days = ? WHERE id = ? AND user_id = ?",
            (days, medication_id, user_id)
        )


def disable_stock_tracking(medication_id: int, user_id: int):
    """Выключает учёт запаса (stock_qty = NULL)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE medications SET stock_qty = NULL WHERE id = ? AND user_id = ?",
            (medication_id, user_id)
        )


def apply_intake_stock(medication_id: int, new_status: str, old_status):
    """Корректирует остаток при отметке приёма. Возвращает dict состояния после или None.

    Идемпотентно: списывает units_per_dose только при переходе в `taken`,
    возвращает при уходе из `taken`. `changed=True` — если остаток изменился.
    None — если трекинг выключен (stock_qty IS NULL) или лекарство не найдено.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT stock_qty, units_per_dose, low_stock_days FROM medications WHERE id = ?",
            (medication_id,)
        ).fetchone()
        if row is None or row["stock_qty"] is None:
            return None
        units = row["units_per_dose"] or 1
        qty = row["stock_qty"]
        changed = False
        if new_status == "taken" and old_status != "taken":
            qty = max(0, qty - units)
            changed = True
        elif old_status == "taken" and new_status != "taken":
            qty = qty + units
            changed = True
        if changed:
            conn.execute("UPDATE medications SET stock_qty = ? WHERE id = ?", (qty, medication_id))
        return {"stock_qty": qty, "units_per_dose": units,
                "low_stock_days": row["low_stock_days"], "changed": changed}
