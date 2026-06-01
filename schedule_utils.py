"""Чистая логика расписания: какие приёмы «положены» в конкретный день/период.

Без БД и Telegram — работает со строками `schedule_rules`+`medications`
(sqlite3.Row или dict с ключами frequency/weekdays/month_day/anchor_date/
interval_days/medication_id/reminder_time). Базис для напоминаний (scheduler)
и аналитики: adherence (F3), streak (F2), прогноз запаса таблеток (F5).

Примечание про «положенность» в прошлом: `_rule_fires_today` применяет правило
к любой дате, не зная, когда лекарство было создано. Потребители аналитики
обязаны сами ограничивать период началом действия лекарства/правила.
"""
from datetime import date, timedelta


def _rule_fires_today(row, today_local: date) -> bool:
    """Проверяет, должно ли правило сработать в указанный день (локальная дата пользователя)."""
    freq = row["frequency"]
    if freq == "daily":
        return True
    if freq == "weekdays":
        days = [int(d) for d in (row["weekdays"] or "").split(",") if d]
        return today_local.isoweekday() in days
    if freq == "monthly":
        return today_local.day == row["month_day"]
    if freq == "interval":
        anchor_str = row["anchor_date"]
        if not anchor_str:
            return False
        anchor = date.fromisoformat(anchor_str)
        return (today_local - anchor).days % row["interval_days"] == 0
    return False


def due_intakes_on(rows, day: date) -> list:
    """Положенные приёмы на дату `day`: список (medication_id, reminder_time)."""
    return [
        (row["medication_id"], row["reminder_time"])
        for row in rows
        if _rule_fires_today(row, day)
    ]


def iter_due_by_day(rows, start_day: date, end_day: date):
    """Генератор (day, [(medication_id, reminder_time), ...]) по дням [start_day, end_day] включительно."""
    day = start_day
    while day <= end_day:
        yield day, due_intakes_on(rows, day)
        day += timedelta(days=1)


def count_due_by_medication(rows, start_day: date, end_day: date,
                            created_dates: dict = None) -> dict:
    """{medication_id: число положенных приёмов за период [start_day, end_day]}.

    created_dates (опц.) — {medication_id: date начала действия}: дни раньше этой
    даты не учитываются (знаменатель adherence не штрафует за время до создания
    лекарства). Лекарства без записи в created_dates учитываются за весь период.
    """
    counts: dict = {}
    for day, intakes in iter_due_by_day(rows, start_day, end_day):
        for mid, _time in intakes:
            if created_dates is not None:
                cd = created_dates.get(mid)
                if cd is not None and day < cd:
                    continue
            counts[mid] = counts.get(mid, 0) + 1
    return counts


def due_by_med_day(rows, start_day: date, end_day: date, created_dates: dict = None) -> dict:
    """{(medication_id, day): число положенных приёмов} по дням (для календаря отчёта врача, F1).

    created_dates (опц.) — кламп по дате создания лекарства (как в count_due_by_medication).
    """
    out: dict = {}
    for day, intakes in iter_due_by_day(rows, start_day, end_day):
        for mid, _time in intakes:
            if created_dates is not None:
                cd = created_dates.get(mid)
                if cd is not None and day < cd:
                    continue
            out[(mid, day)] = out.get((mid, day), 0) + 1
    return out


def count_due_total(rows, start_day: date, end_day: date) -> int:
    """Всего положенных приёмов за период [start_day, end_day] (знаменатель adherence)."""
    return sum(len(intakes) for _day, intakes in iter_due_by_day(rows, start_day, end_day))


def days_of_stock_left(rules, stock_qty, units_per_dose, today: date, horizon: int = 365):
    """Сколько календарных дней (начиная с today) хватит запаса при текущем расписании (F5).

    rules — правила ОДНОГО лекарства; stock_qty — остаток в единицах;
    units_per_dose — расход за один приём. Возвращает число дней, целиком покрытых
    запасом (день без приёмов тоже «покрыт»); прерывается на первом дне, чей расход
    не покрыть. horizon — потолок прогноза (дней). None если трекинг выключен
    (stock_qty is None) или некорректный units_per_dose.
    """
    if stock_qty is None or units_per_dose is None or units_per_dose <= 0:
        return None
    remaining = stock_qty
    days = 0
    day = today
    for _ in range(horizon):
        due = sum(1 for r in rules if _rule_fires_today(r, day))
        need = due * units_per_dose
        if need > 0:
            if remaining >= need:
                remaining -= need
            else:
                break
        days += 1
        day += timedelta(days=1)
    return days
