"""F2 — серия идеальных дней (streak): чистая логика compute_streak + группировка по субъектам."""
from datetime import date, timedelta

import pytz

from streak import compute_streak, streaks_by_subject

TODAY = date(2026, 6, 10)   # среда


def _rule(mid, time="09:00", freq="daily", dep=None, name=None,
          created="2025-01-01 00:00:00", **kw):
    base = {"medication_id": mid, "reminder_time": time, "frequency": freq,
            "weekdays": None, "month_day": None, "anchor_date": None, "interval_days": None,
            "dependent_id": dep, "dependent_name": name, "created_at": created}
    base.update(kw)
    return base


def _taken(mid, time="09:00"):
    return {(mid, time): "taken"}


# ── compute_streak (чистая) ─────────────────────────────────────────────────

def test_three_perfect_days():
    rows = [_rule(1)]
    sbd = {TODAY: _taken(1), TODAY - timedelta(days=1): _taken(1), TODAY - timedelta(days=2): _taken(1)}
    assert compute_streak(rows, sbd, TODAY) == 3


def test_today_pending_does_not_break():
    """Сегодня без отметок (pending) — серия прошлых дней сохраняется, но сегодня не считается."""
    rows = [_rule(1)]
    sbd = {TODAY - timedelta(days=1): _taken(1), TODAY - timedelta(days=2): _taken(1)}
    assert compute_streak(rows, sbd, TODAY) == 2


def test_today_skip_breaks_to_zero():
    rows = [_rule(1)]
    sbd = {TODAY: {(1, "09:00"): "skipped"}}
    assert compute_streak(rows, sbd, TODAY) == 0


def test_past_skip_breaks():
    rows = [_rule(1)]
    sbd = {TODAY: _taken(1), TODAY - timedelta(days=1): {(1, "09:00"): "skipped"}}
    assert compute_streak(rows, sbd, TODAY) == 1


def test_partial_day_breaks():
    """День, где один приём принят, а второй пропущен — не идеальный."""
    rows = [_rule(1, "09:00"), _rule(1, "21:00")]
    sbd = {TODAY: {(1, "09:00"): "taken", (1, "21:00"): "taken"},
           TODAY - timedelta(days=1): {(1, "09:00"): "taken"}}  # 21:00 пропущен (нет записи)
    assert compute_streak(rows, sbd, TODAY) == 1


def test_weekly_empty_days_dont_break():
    """Раз в неделю (пн): дни без приёмов не рвут серию."""
    mon = date(2026, 6, 8)   # понедельник
    rows = [_rule(1, freq="weekdays", weekdays="1")]
    sbd = {mon: _taken(1), mon - timedelta(days=7): _taken(1)}
    assert compute_streak(rows, sbd, mon) == 2


def test_created_clamp_other_med_not_required_before_creation():
    """Лекарство, созданное сегодня, не штрафует серию за прошлые дни."""
    rows = [_rule(1, created="2025-01-01 00:00:00"),       # старое
            _rule(2, created="2026-06-10 00:00:00")]        # создано сегодня
    sbd = {
        TODAY: {(1, "09:00"): "taken", (2, "09:00"): "taken"},
        TODAY - timedelta(days=1): _taken(1),
        TODAY - timedelta(days=2): _taken(1),
    }
    created = {1: date(2025, 1, 1), 2: TODAY}
    assert compute_streak(rows, sbd, TODAY, created) == 3


def test_no_planned_no_streak():
    rows = [_rule(1, freq="monthly", month_day=20)]   # 20-го нет в окне
    assert compute_streak(rows, {}, TODAY) == 0


# ── streaks_by_subject (группировка владелец/подопечные) ─────────────────────

def _intake(mid, status, day, time="09:00"):
    return {"medication_id": mid, "scheduled_time": time, "status": status,
            "taken_at": f"{day.isoformat()} 12:00:00"}


def test_subjects_owner_and_dependent_separate():
    tz = pytz.utc
    rows = [_rule(1, dep=None),
            _rule(2, dep=5, name="Маша")]
    intakes = [
        _intake(1, "taken", TODAY),
        _intake(1, "taken", TODAY - timedelta(days=1)),
        _intake(2, "taken", TODAY),
        _intake(2, "skipped", TODAY - timedelta(days=1)),
    ]
    res = streaks_by_subject(rows, intakes, tz, TODAY)
    assert res[0]["dependent_id"] is None and res[0]["name"] is None
    assert res[0]["streak"] == 2                       # владелец: сегодня + вчера
    masha = next(r for r in res if r["dependent_id"] == 5)
    assert masha["name"] == "Маша" and masha["streak"] == 1   # вчера пропуск рвёт


def test_subjects_owner_only():
    tz = pytz.utc
    rows = [_rule(1, dep=None)]
    intakes = [_intake(1, "taken", TODAY)]
    res = streaks_by_subject(rows, intakes, tz, TODAY)
    assert len(res) == 1 and res[0]["streak"] == 1
