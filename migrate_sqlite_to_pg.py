#!/usr/bin/env python3
"""migrate_sqlite_to_pg.py — миграция данных med_bot.db → PostgreSQL.

Запуск:
    python3 migrate_sqlite_to_pg.py [--sqlite med_bot.db] [--dsn postgresql://...]

Идемпотентен: повторный запуск пропускает уже существующие строки (ON CONFLICT DO NOTHING).
После вставки сбрасывает sequences на MAX(id) каждой таблицы.
"""

import argparse
import sqlite3
import sys

import psycopg
from dotenv import load_dotenv
import os

load_dotenv()

TABLES = ["users", "dependents", "medications", "schedule_rules", "intake_log"]

# Ожидаемые колонки каждой таблицы с дефолтами для тех, которые могут отсутствовать
# в старых SQLite БД (добавлены через migrate()).
COLUMNS = {
    "users": [
        ("id",                  None),
        ("telegram_id",         None),
        ("username",            None),
        ("timezone",            "UTC"),
        ("reminder_mode",       "once"),
        ("time_morning",        "09:00"),
        ("time_lunch",          "12:00"),
        ("time_evening",        "18:00"),
        ("time_night",          "22:00"),
        ("daily_plan_enabled",  1),
        ("daily_plan_time",     "08:00"),
        ("caregiver_enabled",   0),
        ("created_at",          None),
    ],
    "dependents": [
        ("id",      None),
        ("user_id", None),
        ("name",    None),
    ],
    "medications": [
        ("id",             None),
        ("user_id",        None),
        ("name",           None),
        ("dosage",         None),
        ("meal_relation",  None),
        ("times_per_day",  None),
        ("active",         1),
        ("dependent_id",   None),
        ("stock_qty",      None),
        ("units_per_dose", 1.0),
        ("low_stock_days", 5),
        ("paused",         0),
        ("created_at",     None),
    ],
    "schedule_rules": [
        ("id",            None),
        ("medication_id", None),
        ("reminder_time", None),
        ("frequency",     "daily"),
        ("interval_days", None),
        ("weekdays",      None),
        ("month_day",     None),
        ("anchor_date",   None),
        ("dosage",        None),
    ],
    "intake_log": [
        ("id",             None),
        ("medication_id",  None),
        ("scheduled_time", None),
        ("taken_at",       None),
        ("status",         "pending"),
    ],
}

INSERT_SQL = {
    "users": """
        INSERT INTO users (id, telegram_id, username, timezone, reminder_mode,
            time_morning, time_lunch, time_evening, time_night,
            daily_plan_enabled, daily_plan_time, caregiver_enabled, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """,
    "dependents": """
        INSERT INTO dependents (id, user_id, name)
        VALUES (%s,%s,%s)
        ON CONFLICT DO NOTHING
    """,
    "medications": """
        INSERT INTO medications (id, user_id, name, dosage, meal_relation, times_per_day,
            active, dependent_id, stock_qty, units_per_dose, low_stock_days, paused, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """,
    "schedule_rules": """
        INSERT INTO schedule_rules (id, medication_id, reminder_time, frequency,
            interval_days, weekdays, month_day, anchor_date, dosage)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """,
    "intake_log": """
        INSERT INTO intake_log (id, medication_id, scheduled_time, taken_at, status)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """,
}


def sqlite_columns(conn_sqlite, table: str) -> set:
    cur = conn_sqlite.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def read_table(conn_sqlite, table: str) -> list[tuple]:
    """Читает строки из SQLite, подставляя дефолты для отсутствующих колонок."""
    existing = sqlite_columns(conn_sqlite, table)
    col_defs = COLUMNS[table]

    select_parts = []
    for col, default in col_defs:
        if col in existing:
            select_parts.append(col)
        else:
            val = "NULL" if default is None else repr(default)
            select_parts.append(f"{val} AS {col}")

    sql = f"SELECT {', '.join(select_parts)} FROM {table}"
    cur = conn_sqlite.execute(sql)
    return cur.fetchall()


def reset_sequences(conn_pg):
    """Сдвигает IDENTITY-последовательности на MAX(id) каждой таблицы."""
    for table in TABLES:
        conn_pg.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 0))"
        )


def migrate(sqlite_path: str, dsn: str, clean: bool = False):
    print(f"SQLite:    {sqlite_path}")
    print(f"Postgres:  {dsn.split('@')[-1]}")  # не логируем пароль
    print()

    conn_sqlite = sqlite3.connect(sqlite_path)
    conn_sqlite.row_factory = sqlite3.Row

    # Подсчёт строк в источнике
    src_counts = {}
    for table in TABLES:
        try:
            n = conn_sqlite.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        src_counts[table] = n
        print(f"  SQLite {table:<20} {n:>6} строк")

    print()

    with psycopg.connect(dsn, autocommit=False) as conn_pg:
        if clean:
            print("Очищаю целевую БД (--clean)...")
            conn_pg.execute(
                "TRUNCATE TABLE intake_log, schedule_rules, medications, dependents, users "
                "RESTART IDENTITY CASCADE"
            )
            conn_pg.commit()
            print()

        inserted = {}
        skipped = {}

        for table in TABLES:
            if src_counts[table] == 0:
                inserted[table] = 0
                skipped[table] = 0
                continue

            rows = read_table(conn_sqlite, table)
            sql = INSERT_SQL[table]

            ins = 0
            for row in rows:
                cur = conn_pg.execute(sql, tuple(row))
                ins += cur.rowcount  # 0 = конфликт (пропущено), 1 = вставлено
            inserted[table] = ins
            skipped[table] = src_counts[table] - ins

        reset_sequences(conn_pg)
        conn_pg.commit()

    conn_sqlite.close()

    # Итог
    print("Результат:")
    print(f"  {'Таблица':<20} {'Источник':>8} {'Вставлено':>10} {'Пропущено':>10}")
    print("  " + "-" * 52)
    ok = True
    for table in TABLES:
        src = src_counts[table]
        ins = inserted[table]
        skip = skipped[table]
        status = "" if ins + skip == src else "  ⚠ РАСХОЖДЕНИЕ"
        print(f"  {table:<20} {src:>8} {ins:>10} {skip:>10}{status}")
        if ins + skip != src:
            ok = False

    print()
    if ok:
        print("✅ Миграция завершена успешно.")
    else:
        print("❌ Обнаружены расхождения — проверьте данные вручную.")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Миграция SQLite → PostgreSQL")
    parser.add_argument("--sqlite", default="med_bot.db", help="Путь к SQLite-файлу")
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL"),
                        help="DSN PostgreSQL (по умолчанию — DATABASE_URL из .env)")
    parser.add_argument("--clean", action="store_true",
                        help="Очистить целевую БД перед миграцией (TRUNCATE)")
    args = parser.parse_args()

    if not args.dsn:
        print("Ошибка: DATABASE_URL не задан и --dsn не указан.", file=sys.stderr)
        sys.exit(1)

    migrate(args.sqlite, args.dsn, clean=args.clean)
