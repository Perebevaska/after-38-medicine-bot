"""Тесты чистого модуля schedule_utils — «положенные приёмы» за день/период.

Фундамент для adherence (F3), streak (F2), прогноза запаса (F5).
"""
from datetime import date

from schedule_utils import (
    _rule_fires_today, due_intakes_on, iter_due_by_day,
    count_due_by_medication, count_due_total, days_of_stock_left,
    due_by_med_day,
)

MON = date(2026, 6, 1)   # понедельник, isoweekday()==1


def _rule(mid, time, freq="daily", **kw):
    base = {"medication_id": mid, "reminder_time": time, "frequency": freq,
            "weekdays": None, "month_day": None, "anchor_date": None, "interval_days": None}
    base.update(kw)
    return base


# ── due_intakes_on ──────────────────────────────────────────────────────────

def test_due_daily():
    rows = [_rule(1, "09:00"), _rule(1, "21:00")]
    assert due_intakes_on(rows, MON) == [(1, "09:00"), (1, "21:00")]


def test_due_weekdays_filters():
    rows = [_rule(1, "09:00", "weekdays", weekdays="1,3"),   # пн — да
            _rule(2, "10:00", "weekdays", weekdays="2,4")]   # пн — нет
    assert due_intakes_on(rows, MON) == [(1, "09:00")]


def test_due_monthly():
    rows = [_rule(1, "09:00", "monthly", month_day=1),
            _rule(2, "09:00", "monthly", month_day=15)]
    assert due_intakes_on(rows, MON) == [(1, "09:00")]


def test_due_interval():
    rows = [_rule(1, "09:00", "interval", interval_days=2, anchor_date="2026-06-01")]
    assert due_intakes_on(rows, date(2026, 6, 1)) == [(1, "09:00")]
    assert due_intakes_on(rows, date(2026, 6, 2)) == []
    assert due_intakes_on(rows, date(2026, 6, 3)) == [(1, "09:00")]


# ── iter_due_by_day ─────────────────────────────────────────────────────────

def test_iter_inclusive_range():
    rows = [_rule(1, "09:00")]
    days = [d for d, _ in iter_due_by_day(rows, MON, date(2026, 6, 3))]
    assert days == [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)]


def test_iter_single_day():
    rows = [_rule(1, "09:00")]
    out = list(iter_due_by_day(rows, MON, MON))
    assert out == [(MON, [(1, "09:00")])]


# ── count helpers ───────────────────────────────────────────────────────────

def test_count_total_daily_week():
    rows = [_rule(1, "09:00"), _rule(1, "21:00")]   # 2 приёма/день
    # 7 дней (1–7 июня) × 2 = 14
    assert count_due_total(rows, MON, date(2026, 6, 7)) == 14


def test_count_by_medication():
    rows = [
        _rule(1, "09:00"),                                   # daily
        _rule(2, "10:00", "weekdays", weekdays="1"),         # только пн
    ]
    # период пн–вс (1–7 июня): med1 = 7, med2 = 1 (один понедельник)
    counts = count_due_by_medication(rows, MON, date(2026, 6, 7))
    assert counts == {1: 7, 2: 1}


def test_count_total_empty_when_nothing_fires():
    rows = [_rule(1, "09:00", "monthly", month_day=20)]
    # 1–7 июня — 20-го нет
    assert count_due_total(rows, MON, date(2026, 6, 7)) == 0


# ── created_dates кламп (знаменатель adherence F3) ───────────────────────────

def test_count_by_medication_clamps_to_created_date():
    rows = [_rule(1, "09:00"), _rule(2, "09:00")]
    # med1 создан 1 июня (весь период), med2 — 5 июня (учитываются 5,6,7 = 3 дня)
    created = {1: MON, 2: date(2026, 6, 5)}
    counts = count_due_by_medication(rows, MON, date(2026, 6, 7), created)
    assert counts == {1: 7, 2: 3}


def test_count_by_medication_unknown_created_counted_fully():
    rows = [_rule(1, "09:00"), _rule(2, "09:00")]
    # med2 нет в created_dates → учитывается за весь период
    counts = count_due_by_medication(rows, MON, date(2026, 6, 7), {1: date(2026, 6, 6)})
    assert counts == {1: 2, 2: 7}


def test_count_by_medication_created_after_period_excluded():
    rows = [_rule(1, "09:00")]
    counts = count_due_by_medication(rows, MON, date(2026, 6, 7), {1: date(2026, 6, 30)})
    assert counts == {}


# ── due_by_med_day (календарь отчёта врача F1) ───────────────────────────────

def test_due_by_med_day_keys_and_counts():
    rows = [_rule(1, "09:00"), _rule(1, "21:00"),          # med1 — 2 приёма/день
            _rule(2, "10:00", "weekdays", weekdays="1")]   # med2 — только пн
    out = due_by_med_day(rows, MON, date(2026, 6, 2))
    assert out[(1, MON)] == 2
    assert out[(1, date(2026, 6, 2))] == 2
    assert out[(2, MON)] == 1
    assert (2, date(2026, 6, 2)) not in out               # вторник — med2 не положен


def test_due_by_med_day_respects_created():
    rows = [_rule(1, "09:00")]
    out = due_by_med_day(rows, MON, date(2026, 6, 3), {1: date(2026, 6, 3)})
    assert out == {(1, date(2026, 6, 3)): 1}              # дни до created не попадают


# ── совместимость реэкспорта ────────────────────────────────────────────────

def test_rule_fires_today_still_importable_from_scheduler():
    from scheduler import _rule_fires_today as sched_fires
    assert sched_fires is _rule_fires_today
    assert sched_fires(_rule(1, "09:00"), MON) is True


# ── days_of_stock_left (F5) ─────────────────────────────────────────────────

def test_stock_daily_one_per_dose():
    rules = [_rule(1, "09:00")]            # 1 приём/день
    assert days_of_stock_left(rules, 3, 1, MON) == 3


def test_stock_daily_two_doses():
    rules = [_rule(1, "09:00"), _rule(1, "21:00")]   # 2 приёма/день
    # 5 таблеток по 1 → день1(2), день2(2), день3 нужно 2, осталось 1 → стоп = 2 дня
    assert days_of_stock_left(rules, 5, 1, MON) == 2


def test_stock_units_per_dose():
    rules = [_rule(1, "09:00")]            # 1 приём/день, по 2 таблетки
    assert days_of_stock_left(rules, 4, 2, MON) == 2


def test_stock_zero_cannot_cover_today():
    rules = [_rule(1, "09:00")]
    assert days_of_stock_left(rules, 0, 1, MON) == 0


def test_stock_tracking_off_returns_none():
    rules = [_rule(1, "09:00")]
    assert days_of_stock_left(rules, None, 1, MON) is None


def test_stock_invalid_units_returns_none():
    rules = [_rule(1, "09:00")]
    assert days_of_stock_left(rules, 10, 0, MON) is None


def test_stock_horizon_cap():
    rules = [_rule(1, "09:00", "monthly", month_day=1)]   # раз в месяц
    # огромный запас — но прогноз ограничен horizon
    assert days_of_stock_left(rules, 1000, 1, MON, horizon=30) == 30


def test_stock_weekly_spans_calendar_days():
    rules = [_rule(1, "09:00", "weekdays", weekdays="1")]  # только пн
    # 1 таблетка: today(пн) приём покрыт; следующий пн (через 7 дн) не покрыть.
    # покрыты дни: пн..вс (7 дней), на 8-й (след. пн) расход 1 > 0 → стоп
    assert days_of_stock_left(rules, 1, 1, MON) == 7
