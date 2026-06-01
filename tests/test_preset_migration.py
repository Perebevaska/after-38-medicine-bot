"""Баг #6: смена пресета времени переносит существующие правила на новое время."""
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    import database as d
    monkeypatch.setattr(d, "DB_PATH", str(tmp_path / "test.db"))
    d.init_db()
    d.migrate()
    return d


def _rule_times(d, med_id):
    with d.get_connection() as conn:
        return sorted(r["reminder_time"] for r in conn.execute(
            "SELECT reminder_time FROM schedule_rules WHERE medication_id = ?", (med_id,)
        ))


def test_changing_preset_migrates_matching_rules(db):
    d = db
    uid = d.get_or_create_user(8001, "u")
    mid = d.add_medication(uid, "Аспирин", "100мг", "after", 2)
    d.add_schedule_rule(mid, "09:00", "daily")   # «утро» по умолчанию
    d.add_schedule_rule(mid, "21:00", "daily")   # «ночь»

    n = d.set_user_time_preset(8001, "morning", "12:44")

    assert n == 1                                  # перенесено одно правило
    assert _rule_times(d, mid) == ["12:44", "21:00"]
    assert d.get_user_time_presets(8001)["morning"] == "12:44"


def test_same_value_no_migration(db):
    d = db
    uid = d.get_or_create_user(8002, "u")
    mid = d.add_medication(uid, "X", "1", "any", 1)
    d.add_schedule_rule(mid, "09:00", "daily")
    assert d.set_user_time_preset(8002, "morning", "09:00") == 0
    assert _rule_times(d, mid) == ["09:00"]


def test_only_active_meds_migrated(db):
    d = db
    uid = d.get_or_create_user(8003, "u")
    mid = d.add_medication(uid, "X", "1", "any", 1)
    d.add_schedule_rule(mid, "09:00", "daily")
    d.deactivate_medication(mid, uid)   # неактивно (и правила удаляются deactivate)
    # у неактивного лекарства правил уже нет → перенос 0
    assert d.set_user_time_preset(8003, "morning", "10:00") == 0


def test_unknown_user_noop(db):
    assert db.set_user_time_preset(999999, "morning", "10:00") == 0


def test_other_users_rules_untouched(db):
    d = db
    a = d.get_or_create_user(8101, "a")
    b = d.get_or_create_user(8102, "b")
    ma = d.add_medication(a, "A", "1", "any", 1); d.add_schedule_rule(ma, "09:00", "daily")
    mb = d.add_medication(b, "B", "1", "any", 1); d.add_schedule_rule(mb, "09:00", "daily")
    d.set_user_time_preset(8101, "morning", "07:30")
    assert _rule_times(d, ma) == ["07:30"]
    assert _rule_times(d, mb) == ["09:00"]   # чужие правила не тронуты
