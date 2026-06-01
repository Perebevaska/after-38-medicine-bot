"""Тесты чистого модуля schedule_utils — «положенные приёмы» за день/период.

Фундамент для adherence (F3), streak (F2), прогноза запаса (F5).
"""
from datetime import date

from schedule_utils import (
    _rule_fires_today, due_intakes_on, iter_due_by_day,
    count_due_by_medication, count_due_total,
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


# ── совместимость реэкспорта ────────────────────────────────────────────────

def test_rule_fires_today_still_importable_from_scheduler():
    from scheduler import _rule_fires_today as sched_fires
    assert sched_fires is _rule_fires_today
    assert sched_fires(_rule(1, "09:00"), MON) is True
