"""F2 — серия идеальных дней (streak). Логика поверх schedule_utils.

«Идеальный день» — все положенные на день приёмы отмечены `taken` (ни одного
skipped/pending/пропущенного). Серия = число подряд идущих идеальных дней,
заканчивающихся сегодня. Сегодня серию не рвёт, пока его приёмы ещё в ожидании
(нет ни одного skipped); в серию текущий день засчитывается только когда всё за
день принято.

Серия считается ОТДЕЛЬНО для владельца и каждого подопечного (caregiver):
строки группируются по `dependent_id` до вызова `compute_streak`.

`compute_streak` — чистая (без БД/tz). `streaks_by_subject`/`streak_window`
конвертируют UTC-таймстампы в локальную дату пользователя (pytz).
"""
from datetime import date, datetime, timedelta

import pytz

from schedule_utils import due_intakes_on


def compute_streak(rows, status_by_day, today: date, created_dates: dict = None,
                   horizon: int = 400) -> int:
    """Длина серии идеальных дней, заканчивающихся `today`.

    rows — правила расписания (как в schedule_utils); status_by_day —
    {date: {(medication_id, reminder_time): status}} фактических записей
    intake_log; created_dates (опц.) — {mid: date создания}: дни до создания
    лекарства не считаются положенными (не рвут серию). Возвращает int ≥ 0.
    """
    earliest = min(created_dates.values()) if created_dates else None
    streak = 0
    day = today
    for _ in range(horizon):
        if earliest is not None and day < earliest:
            break
        planned = []
        for mid, t in due_intakes_on(rows, day):
            if created_dates is not None:
                cd = created_dates.get(mid)
                if cd is not None and day < cd:
                    continue
            planned.append((mid, t))
        if planned:
            day_st = status_by_day.get(day, {})
            if all(day_st.get(k) == "taken" for k in planned):
                streak += 1
            elif day == today and not any(day_st.get(k) == "skipped" for k in planned):
                pass  # сегодня ещё в процессе — не рвём серию и не засчитываем
            else:
                break
        day -= timedelta(days=1)
    return streak


def _local_date(ts: str, user_tz) -> date:
    """UTC-таймстамп 'YYYY-MM-DD HH:MM:SS' → локальная дата пользователя."""
    return (datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=pytz.utc).astimezone(user_tz).date())


def streak_window(user_tz, days: int = 400):
    """Окно выборки записей для серий: (today_local, start_utc, end_utc)."""
    today = datetime.now(user_tz).date()
    start_day = today - timedelta(days=days)
    start_local = user_tz.localize(datetime(start_day.year, start_day.month, start_day.day))
    end_local = user_tz.localize(datetime(today.year, today.month, today.day)) + timedelta(days=1)
    start_utc = start_local.astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_utc = end_local.astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")
    return today, start_utc, end_utc


def streaks_by_subject(streak_rows, intake_rows, user_tz, today: date) -> list:
    """Серии по субъектам (владелец + подопечные).

    streak_rows — строки правил (medication_id, dependent_id, dependent_name,
    created_at + поля расписания) активных непаузных лекарств; intake_rows —
    записи intake_log (medication_id, scheduled_time, status, taken_at) за окно.
    Возвращает [{dependent_id, name, streak}]: владелец (dependent_id=None,
    name=None) первым, затем подопечные по dependent_id. Субъекты без правил
    отсутствуют.
    """
    med_subject: dict = {}
    subjects: list = []          # порядок появления: (dep_id, dep_name)
    seen: set = set()
    rows_by_subject: dict = {}
    created_by_subject: dict = {}
    for r in streak_rows:
        dep_id = r["dependent_id"]
        mid = r["medication_id"]
        med_subject[mid] = dep_id
        if dep_id not in seen:
            seen.add(dep_id)
            subjects.append((dep_id, r["dependent_name"]))
            rows_by_subject[dep_id] = []
            created_by_subject[dep_id] = {}
        rows_by_subject[dep_id].append(r)
        if mid not in created_by_subject[dep_id]:
            try:
                created_by_subject[dep_id][mid] = _local_date(r["created_at"], user_tz)
            except (ValueError, TypeError):
                created_by_subject[dep_id][mid] = None

    status_by_subject = {dep_id: {} for dep_id, _ in subjects}
    for ir in intake_rows:
        dep_id = med_subject.get(ir["medication_id"])
        if dep_id not in status_by_subject:
            continue
        day = _local_date(ir["taken_at"], user_tz)
        key = (ir["medication_id"], ir["scheduled_time"])
        status_by_subject[dep_id].setdefault(day, {})[key] = ir["status"]

    result = []
    for dep_id, dep_name in subjects:
        cd = {m: d for m, d in created_by_subject[dep_id].items() if d is not None} or None
        streak = compute_streak(rows_by_subject[dep_id], status_by_subject[dep_id], today, cd)
        result.append({"dependent_id": dep_id, "name": dep_name, "streak": streak})
    result.sort(key=lambda x: (x["dependent_id"] is not None, x["dependent_id"] or 0))
    return result
