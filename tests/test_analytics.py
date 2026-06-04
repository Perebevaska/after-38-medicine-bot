"""F11-C (Фаза C-1) — чистые тесты analytics.py (без БД)."""
from datetime import date, timedelta

import pytz

import analytics


def _rule(mid, time="09:00", freq="daily"):
    return {"medication_id": mid, "reminder_time": time, "frequency": freq,
            "weekdays": None, "month_day": None, "anchor_date": None, "interval_days": None}


def _taken(*days):
    """status_by_day со всеми (1,'09:00') taken на указанных датах."""
    return {d: {(1, "09:00"): "taken"} for d in days}


# ── best_streak ─────────────────────────────────────────────────────────────

def test_best_streak_picks_longest_past_run():
    rows = [_rule(1)]
    today = date(2026, 1, 10)
    created = {1: date(2026, 1, 1)}
    # 1-3 taken, 4 skipped (разрыв), 5-10 taken → лучшая серия = 6
    st = _taken(date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
                date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7),
                date(2026, 1, 8), date(2026, 1, 9), date(2026, 1, 10))
    st[date(2026, 1, 4)] = {(1, "09:00"): "skipped"}
    assert analytics.best_streak(rows, st, today, created) == 6


def test_best_streak_zero_when_no_perfect_day():
    rows = [_rule(1)]
    today = date(2026, 1, 3)
    created = {1: date(2026, 1, 1)}
    st = {date(2026, 1, 1): {(1, "09:00"): "skipped"}}
    assert analytics.best_streak(rows, st, today, created) == 0


# ── daily_adherence / window_pct ────────────────────────────────────────────

def test_daily_and_window_pct():
    rows = [_rule(1)]
    today = date(2026, 1, 3)
    start = date(2026, 1, 1)
    taken_by_day = {date(2026, 1, 1): 1, date(2026, 1, 2): 1}  # 2 из 3 дней
    daily = analytics.daily_adherence(rows, taken_by_day, {}, start, today)
    assert len(daily) == 3
    assert daily[0] == {"day": "2026-01-01", "due": 1, "taken": 1, "pct": 100}
    assert daily[2]["pct"] == 0
    assert analytics.window_pct(daily, 3) == 67
    assert analytics.window_pct(daily, 7) == 67  # окно длиннее истории — то же


def test_daily_null_pct_when_no_due():
    # interval-правило без anchor → не срабатывает → due=0 → pct=None
    rows = [{"medication_id": 1, "reminder_time": "09:00", "frequency": "interval",
             "weekdays": None, "month_day": None, "anchor_date": None, "interval_days": None}]
    daily = analytics.daily_adherence(rows, {}, {}, date(2026, 1, 1), date(2026, 1, 1))
    assert daily[0]["pct"] is None


# ── punctuality ─────────────────────────────────────────────────────────────

def test_punctuality_metrics_and_worst_hour():
    tz = pytz.utc
    intakes = [
        {"scheduled_time": "09:00", "status": "taken", "taken_at": "2026-01-01 09:10:00"},  # +10
        {"scheduled_time": "09:00", "status": "taken", "taken_at": "2026-01-02 09:50:00"},  # +50
        {"scheduled_time": "21:00", "status": "skipped", "taken_at": "2026-01-01 23:00:00"},
        {"scheduled_time": "21:00", "status": "skipped", "taken_at": "2026-01-02 23:00:00"},
        {"scheduled_time": "21:00", "status": "skipped", "taken_at": "2026-01-03 23:00:00"},
    ]
    r = analytics.punctuality(intakes, tz, min_sample=2)
    assert r["sample"] == 2
    assert r["ontime_pct"] == 50          # +10 вовремя, +50 поздно
    assert r["late_pct"] == 50
    assert r["avg_delay_min"] == 30       # (10+50)/2
    assert r["worst_hour"] == 21
    assert r["worst_hour_skip_pct"] == 100


def test_punctuality_hides_metrics_below_min_sample():
    tz = pytz.utc
    intakes = [{"scheduled_time": "09:00", "status": "taken", "taken_at": "2026-01-01 09:10:00"}]
    r = analytics.punctuality(intakes, tz, min_sample=10)
    assert r["sample"] == 1
    assert r["ontime_pct"] is None and r["avg_delay_min"] is None


def test_weekly_adherence_buckets():
    rows = [_rule(1)]
    today = date(2026, 1, 14)
    start = date(2026, 1, 1)                    # 14 дней → 2 недельных бакета
    taken = {start + timedelta(days=i): 1 for i in range(7)}  # 1-я неделя 100%
    daily = analytics.daily_adherence(rows, taken, {}, start, today)
    wk = analytics.weekly_adherence(daily)
    assert len(wk) == 2
    assert wk[-1]["end"] == "2026-01-14"        # последний бакет оканчивается сегодня
    assert wk[0]["pct"] == 100 and wk[1]["pct"] == 0


# ── therapy_load ────────────────────────────────────────────────────────────

def test_therapy_load():
    rows = [_rule(1), _rule(2, time="20:00")]
    units = {1: 1, 2: 0.5}
    r = analytics.therapy_load(rows, units, date(2026, 1, 1))
    assert r["meds"] == 2
    assert r["intakes_per_day"] == 2.0          # 2 приёма/день
    assert r["units_per_week"] == 10.5          # (1 + 0.5) * 7
