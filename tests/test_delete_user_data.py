"""Проверка полного удаления данных пользователя (/settings → «Удалить мои данные»).

Гарантирует, что delete_user_data чистит ВСЕ таблицы (users, dependents,
medications, schedule_rules, intake_log), включая лекарства подопечных,
и НЕ задевает других пользователей.
"""
import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    import database as d
    monkeypatch.setattr(d, "DB_PATH", str(tmp_path / "test.db"))
    d.init_db()
    d.migrate()
    return d


def _counts(d, user_id, med_ids):
    """Сколько строк осталось по каждому участку данных пользователя."""
    ph = ",".join("?" * len(med_ids)) or "NULL"
    with d.get_connection() as conn:
        users = conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        deps = conn.execute("SELECT COUNT(*) FROM dependents WHERE user_id = ?", (user_id,)).fetchone()[0]
        meds = conn.execute("SELECT COUNT(*) FROM medications WHERE user_id = ?", (user_id,)).fetchone()[0]
        rules = conn.execute(f"SELECT COUNT(*) FROM schedule_rules WHERE medication_id IN ({ph})", med_ids).fetchone()[0] if med_ids else 0
        logs = conn.execute(f"SELECT COUNT(*) FROM intake_log WHERE medication_id IN ({ph})", med_ids).fetchone()[0] if med_ids else 0
    return {"users": users, "dependents": deps, "medications": meds, "schedule_rules": rules, "intake_log": logs}


def _seed(d, telegram_id):
    """Создаёт пользователя с подопечным, своими и его лекарствами, расписанием и историей."""
    uid = d.get_or_create_user(telegram_id, "u")
    dep_id = d.add_dependent(telegram_id, "Маша")
    m_own = d.add_medication(uid, "Аспирин", "100мг", "after", 1)
    m_dep = d.add_medication(uid, "Сироп", "5мл", "before", 1, dependent_id=dep_id)
    for mid in (m_own, m_dep):
        d.add_schedule_rule(mid, "09:00", "daily")
        d.log_intake(mid, "09:00", "taken", "2000-01-01 00:00:00", "2100-01-01 00:00:00")
    return uid, [m_own, m_dep]


def test_delete_removes_everything(db):
    uid, med_ids = _seed(db, 1001)
    # до удаления — данные есть
    before = _counts(db, uid, med_ids)
    assert before == {"users": 1, "dependents": 1, "medications": 2,
                      "schedule_rules": 2, "intake_log": 2}

    returned = db.delete_user_data(1001)
    assert sorted(returned) == sorted(med_ids)

    after = _counts(db, uid, med_ids)
    assert after == {"users": 0, "dependents": 0, "medications": 0,
                     "schedule_rules": 0, "intake_log": 0}


def test_delete_does_not_touch_other_user(db):
    uid_a, meds_a = _seed(db, 1001)
    uid_b, meds_b = _seed(db, 1002)

    db.delete_user_data(1001)

    # пользователь B полностью на месте
    assert _counts(db, uid_b, meds_b) == {"users": 1, "dependents": 1, "medications": 2,
                                          "schedule_rules": 2, "intake_log": 2}


def test_delete_unknown_user_noop(db):
    assert db.delete_user_data(999999) == []
