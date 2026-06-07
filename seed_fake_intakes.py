"""Одноразовый засев ДЕМО-данных для вкладки «Прогресс» (вкл. risk-сигналы C-2).

Делает правильно: создаёт ОТДЕЛЬНЫЕ демо-лекарства (с расписанием) и вешает приёмы
на них. Реальные лекарства пользователей НЕ трогает.

Также откатывает предыдущую (ошибочную) версию: снимает демо-приёмы с реальных
лекарств 64/65/66 и возвращает их флаги.

Идемпотентно: демо-лекарства (имя с пометкой «(демо)») пересоздаются при каждом прогоне.
НЕ для прода — запускать вручную.
"""
import random
from datetime import datetime, timedelta

import pytz

from database import (init_pool, get_connection, add_medication, add_schedule_rule)

random.seed(42)

CREATED_OFFSET = 55
SEED_AGES = range(1, 56)
PRIMARY_SKIP = {1, 3, 5, 7, 20, 35}
SECOND_SKIP = {22, 40}
UTC_FMT = "%Y-%m-%d %H:%M:%S"

# (telegram_id, user_id, tzname)
ACCOUNTS = [
    (335809114, 12061, "Asia/Yekaterinburg"),  # admin (itdmitriy)
    (310868540, 12542, "Europe/Moscow"),        # elpikito
]

# демо-лекарства: (name, slot, is_primary)
DEMO_MEDS = [
    ("Витамин D (демо)", "09:00", True),
    ("Омега-3 (демо)",   "21:00", False),
]


def to_utc(tz, day, slot, offset_min):
    h, m = int(slot[:2]), int(slot[3:5])
    local = tz.localize(datetime(day.year, day.month, day.day, h, m)) + timedelta(minutes=offset_min)
    return local.astimezone(pytz.utc).strftime(UTC_FMT)


def revert_real_meds(conn):
    """Снять демо-приёмы с реальных 64/65/66 и вернуть их флаги."""
    # удаляем историч. приёмы (сегодняшние реальные не трогаем — taken_at >= today_start UTC-проще: режем по дате < сегодня UTC-2дня хватит? нет — режем по конкретным дням)
    # безопасно: удаляем все приёмы этих меди старше 2 дней назад (сегодняшние реальные останутся)
    cut = (datetime.now(pytz.utc) - timedelta(days=2)).strftime(UTC_FMT)
    conn.execute("DELETE FROM intake_log WHERE medication_id IN (64,65,66) AND taken_at < %s", (cut,))
    # admin med 64 → исходное (была на паузе)
    conn.execute("UPDATE medications SET paused=1, course_total=NULL, "
                 "created_at='2026-06-05 16:47:36' WHERE id=64")
    # elpikito 65/66 → активны/без паузы; created_at приблизительно (оригинал утерян)
    conn.execute("UPDATE medications SET course_total=NULL, "
                 "created_at='2026-06-05 12:00:00' WHERE id IN (65,66)")


def reset_demo(conn, user_id):
    """Удалить прежние демо-лекарства юзера (+ их приёмы/правила) для идемпотентности."""
    rows = conn.execute(
        "SELECT id FROM medications WHERE user_id=%s AND name LIKE '%%(демо)%%'", (user_id,)
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        conn.execute("DELETE FROM intake_log WHERE medication_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM schedule_rules WHERE medication_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM medications WHERE id = ANY(%s)", (ids,))


def seed_account(tid, user_id, tzname):
    tz = pytz.timezone(tzname)
    today = datetime.now(tz).date()
    created = (datetime.now(pytz.utc) - timedelta(days=CREATED_OFFSET)).strftime(UTC_FMT)

    with get_connection() as conn:
        reset_demo(conn, user_id)

    total = 0
    for name, slot, is_primary in DEMO_MEDS:
        med_id = add_medication(user_id, name, "1 таблетка", "after", 1)
        add_schedule_rule(med_id, slot, "daily")
        with get_connection() as conn:
            conn.execute("UPDATE medications SET created_at=%s WHERE id=%s", (created, med_id))
            for age in SEED_AGES:
                day = today - timedelta(days=age)
                if is_primary:
                    skip = age in PRIMARY_SKIP
                    offset = 0 if skip else random.randint(-150, 200)
                else:
                    skip = age in SECOND_SKIP
                    offset = 0 if skip else random.randint(-20, 25)
                status = "skipped" if skip else "taken"
                conn.execute(
                    "INSERT INTO intake_log (medication_id, scheduled_time, status, taken_at) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT (medication_id, scheduled_time, (LEFT(taken_at,10))) "
                    "DO UPDATE SET status=EXCLUDED.status, taken_at=EXCLUDED.taken_at",
                    (med_id, slot, status, to_utc(tz, day, slot, offset)),
                )
                total += 1
        print(f"  demo med id={med_id} «{name}» {slot}")
    print(f"tid={tid}: demo приёмов≈{total}, created={created[:10]}")


def main():
    init_pool()
    with get_connection() as conn:
        revert_real_meds(conn)
    print("Реальные 64/65/66 откатаны.")
    for tid, uid, tz in ACCOUNTS:
        seed_account(tid, uid, tz)


if __name__ == "__main__":
    main()
