"""DB-тесты учёта запаса (F5) на временной БД (monkeypatch database.DB_PATH)."""
import importlib

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    import database as d
    monkeypatch.setattr(d, "DB_PATH", str(tmp_path / "test.db"))
    d.init_db()
    d.migrate()
    return d


def _med(d):
    uid = d.get_or_create_user(555001, "stock")
    mid = d.add_medication(uid, "Аспирин", "100мг", "after", 1)
    return d, uid, mid


def test_defaults(db):
    d, uid, mid = _med(db)
    m = d.get_medication_by_id(mid, uid)
    assert m["stock_qty"] is None          # трекинг выключен по умолчанию
    assert m["units_per_dose"] == 1
    assert m["low_stock_days"] == 5


def test_set_and_add_stock(db):
    d, uid, mid = _med(db)
    d.set_medication_stock(mid, uid, 30)
    assert d.get_medication_by_id(mid, uid)["stock_qty"] == 30
    d.add_medication_stock(mid, uid, 20)
    assert d.get_medication_by_id(mid, uid)["stock_qty"] == 50


def test_add_stock_from_disabled(db):
    d, uid, mid = _med(db)
    d.add_medication_stock(mid, uid, 10)   # был NULL → 0 + 10
    assert d.get_medication_by_id(mid, uid)["stock_qty"] == 10


def test_units_and_threshold(db):
    d, uid, mid = _med(db)
    d.set_units_per_dose(mid, uid, 2)
    d.set_low_stock_days(mid, uid, 7)
    m = d.get_medication_by_id(mid, uid)
    assert m["units_per_dose"] == 2 and m["low_stock_days"] == 7


def test_apply_intake_stock_off_returns_none(db):
    d, uid, mid = _med(db)
    assert d.apply_intake_stock(mid, "taken", None) is None   # трекинг выключен


def test_apply_intake_decrement_and_refund(db):
    d, uid, mid = _med(db)
    d.set_medication_stock(mid, uid, 10)
    d.set_units_per_dose(mid, uid, 2)

    r = d.apply_intake_stock(mid, "taken", None)
    assert r["changed"] and r["stock_qty"] == 8

    # повторный taken — без изменений (идемпотентно)
    r = d.apply_intake_stock(mid, "taken", "taken")
    assert not r["changed"] and r["stock_qty"] == 8

    # taken → skipped — возврат
    r = d.apply_intake_stock(mid, "skipped", "taken")
    assert r["changed"] and r["stock_qty"] == 10


def test_apply_intake_clamps_at_zero(db):
    d, uid, mid = _med(db)
    d.set_medication_stock(mid, uid, 1)
    d.set_units_per_dose(mid, uid, 2)
    r = d.apply_intake_stock(mid, "taken", None)
    assert r["stock_qty"] == 0   # не уходит в минус


def test_disable_tracking(db):
    d, uid, mid = _med(db)
    d.set_medication_stock(mid, uid, 5)
    d.disable_stock_tracking(mid, uid)
    assert d.get_medication_by_id(mid, uid)["stock_qty"] is None


def test_log_intake_returns_old_status(db):
    d, uid, mid = _med(db)
    lo, hi = "2000-01-01 00:00:00", "2100-01-01 00:00:00"
    assert d.log_intake(mid, "09:00", "taken", lo, hi) is None      # новая запись
    assert d.log_intake(mid, "09:00", "skipped", lo, hi) == "taken"  # прежний статус
    assert d.log_intake(mid, "09:00", "taken", lo, hi) == "skipped"
