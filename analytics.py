"""F11-C (Фаза C-1) — чистая аналитика вкладки «Прогресс». Без БД/Telegram.

Содержит:
- best_streak       — лучшая серия идеальных дней за историю (не только до сегодня);
- daily_adherence   — соблюдение по дням (для графика) с клампом по дате создания;
- window_pct        — % соблюдения за последние N дней из daily;
- punctuality       — пунктуальность ОТМЕТОК (taken_at = момент нажатия, не приёма);
- therapy_load      — нагрузка по терапии (лекарств / приёмов в день / единиц в неделю).

Важно про данные: `taken_at` — момент нажатия кнопки в Mini App, не реальный
момент приёма. Метрики пунктуальности подаются как «пунктуальность отметок».
"""
from datetime import date, datetime, timedelta

import pytz

from schedule_utils import due_intakes_on, iter_due_by_day


def _planned_on(rows, day, created_dates):
    """Положенные приёмы на день с клампом по дате создания лекарства."""
    out = []
    for mid, t in due_intakes_on(rows, day):
        cd = created_dates.get(mid) if created_dates else None
        if cd is not None and day < cd:
            continue
        out.append((mid, t))
    return out


def best_streak(rows, status_by_day, today: date, created_dates: dict = None,
                horizon: int = 400) -> int:
    """Максимальная серия идеальных дней за историю (а не только серия до today).

    rows — правила; status_by_day — {date: {(mid, reminder_time): status}};
    created_dates — {mid: date создания}. День без положенных приёмов не рвёт и
    не продлевает серию. Незавершённый «сегодня» (нет skipped) не рвёт серию.
    """
    earliest = min((d for d in created_dates.values() if d), default=None) if created_dates else None
    day = earliest or (today - timedelta(days=horizon))
    best = run = 0
    while day <= today:
        planned = _planned_on(rows, day, created_dates)
        if planned:
            day_st = status_by_day.get(day, {})
            if all(day_st.get(k) == "taken" for k in planned):
                run += 1
                best = max(best, run)
            elif day == today and not any(day_st.get(k) == "skipped" for k in planned):
                pass  # сегодня ещё в процессе — серию не рвём
            else:
                run = 0
        day += timedelta(days=1)
    return best


def daily_adherence(rows, taken_by_day: dict, created_dates: dict,
                    start_day: date, today: date) -> list:
    """[{day, due, taken, pct}] за [start_day, today]. taken_by_day — {date: count taken}.

    pct = None для дней без положенных приёмов (due=0) — на графике пустой столбик.
    taken клампится к due (нельзя принять больше положенного за день).
    """
    out = []
    for day, _ in iter_due_by_day(rows, start_day, today):
        planned = _planned_on(rows, day, created_dates)
        due = len(planned)
        tk = taken_by_day.get(day, 0)
        pct = min(100, round(tk / due * 100)) if due else None
        out.append({
            "day": day.isoformat(),
            "due": due,
            "taken": min(tk, due) if due else tk,
            "pct": pct,
        })
    return out


def window_pct(daily: list, n: int):
    """% соблюдения за последние n дней из daily (учитываются только дни с due>0)."""
    last = daily[-n:] if n else daily
    due = sum(d["due"] for d in last)
    tk = sum(d["taken"] for d in last)
    return min(100, round(tk / due * 100)) if due else None


def weekly_adherence(daily: list, weeks: int = 13) -> list:
    """Свернуть daily в недельные бакеты (последние `weeks`); последний — текущая неделя.

    daily — по возрастанию даты. Каждый бакет: {start, end, due, taken, pct}.
    Группируем с конца по 7 дней, чтобы последний бакет всегда оканчивался сегодня.
    pct = None для недели без положенных приёмов.
    """
    buckets = []
    i = len(daily)
    while i > 0:
        chunk = daily[max(0, i - 7):i]
        due = sum(d["due"] for d in chunk)
        tk = sum(d["taken"] for d in chunk)
        buckets.append({
            "start": chunk[0]["day"],
            "end": chunk[-1]["day"],
            "due": due,
            "taken": tk,
            "pct": min(100, round(tk / due * 100)) if due else None,
        })
        i -= 7
    buckets.reverse()
    return buckets[-weeks:]


def _delay_minutes(scheduled_time: str, taken_at: str, user_tz):
    """Отклонение отметки от планового времени в минутах (−=раньше, +=позже).

    Коррекция перехода через полночь: берём ближайшее по модулю отклонение.
    None если не распарсить.
    """
    try:
        sh, sm = int(scheduled_time[:2]), int(scheduled_time[3:5])
        loc = (datetime.strptime(taken_at, "%Y-%m-%d %H:%M:%S")
               .replace(tzinfo=pytz.utc).astimezone(user_tz))
    except (ValueError, TypeError, AttributeError):
        return None
    delay = (loc.hour * 60 + loc.minute) - (sh * 60 + sm)
    if delay > 720:
        delay -= 1440
    elif delay < -720:
        delay += 1440
    return delay


def punctuality(intakes: list, user_tz, min_sample: int = 10) -> dict:
    """Пунктуальность ОТМЕТОК: отклонение нажатия от планового времени.

    intakes — [{scheduled_time, status, taken_at}]. Возвращает
    {sample, ontime_pct, late_pct, avg_delay_min, worst_hour, worst_hour_skip_pct}.
    ontime = отметка ≤30 мин после плана (включая раньше); late = >30 мин.
    ontime/late/avg_delay = None пока sample < min_sample (мало данных — не врём).
    worst_hour — плановый час с макс долей skipped (≥3 приёма в часе, есть skip).
    """
    delays = []
    by_hour: dict = {}   # hour -> [total, skipped]
    for i in intakes:
        st = i.get("scheduled_time")
        try:
            hour = int(st[:2])
        except (ValueError, TypeError):
            continue
        tot, sk = by_hour.get(hour, (0, 0))
        by_hour[hour] = (tot + 1, sk + (1 if i["status"] == "skipped" else 0))
        if i["status"] == "taken" and i.get("taken_at"):
            d = _delay_minutes(st, i["taken_at"], user_tz)
            if d is not None:
                delays.append(d)
    sample = len(delays)
    worst_hour = worst_pct = None
    cand = {h: sk / tot for h, (tot, sk) in by_hour.items() if tot >= 3 and sk > 0}
    if cand:
        worst_hour = max(cand, key=lambda h: (cand[h], h))
        worst_pct = round(cand[worst_hour] * 100)
    if sample < min_sample:
        return {"sample": sample, "ontime_pct": None,
                "late_pct": None, "avg_delay_min": None,
                "worst_hour": worst_hour, "worst_hour_skip_pct": worst_pct}
    # «Вовремя» = отметка в пределах 30 мин после плана (раньше тоже ок).
    late = sum(1 for d in delays if d > 30)
    ontime = sample - late
    return {
        "sample": sample,
        "ontime_pct": round(100 * ontime / sample),
        "late_pct": round(100 * late / sample),
        "avg_delay_min": round(sum(delays) / sample),
        "worst_hour": worst_hour,
        "worst_hour_skip_pct": worst_pct,
    }


def therapy_load(rows, units_by_med: dict, today: date, horizon: int = 7) -> dict:
    """Нагрузка по терапии за ближайшие `horizon` дней расписания.

    rows — правила активных лекарств; units_by_med — {mid: units_per_dose}.
    Возвращает {meds, intakes_per_day, units_per_week}.
    meds — все активные лекарства с правилами (а не только сработавшие в окне).
    """
    intakes = 0
    units = 0.0
    for day, day_intakes in iter_due_by_day(rows, today, today + timedelta(days=horizon - 1)):
        for mid, _t in day_intakes:
            intakes += 1
            units += units_by_med.get(mid, 1) or 1
    all_mids = {r["medication_id"] for r in rows}
    return {
        "meds": len(all_mids),
        "intakes_per_day": round(intakes / horizon, 1),
        "units_per_week": round(units / horizon * 7, 1),
    }
