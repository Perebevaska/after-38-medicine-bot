"""F4 — пауза лекарства: DB-фильтры (планировщик/план/adherence) + toggle-хендлер."""
import asyncio

import pytest


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import database as d
    monkeypatch.setattr(d, "DB_PATH", str(tmp_path / "test.db"))
    d.init_db()
    d.migrate()
    return d


def _med(d, tid=4001):
    uid = d.get_or_create_user(tid, "u")
    mid = d.add_medication(uid, "Аспирин", "100мг", "after", 1)
    d.add_schedule_rule(mid, "09:00", "daily")
    return uid, mid


def test_default_not_paused(db):
    uid, mid = _med(db)
    assert db.get_medication_by_id(mid, uid)["paused"] == 0


def test_set_paused_toggles(db):
    uid, mid = _med(db)
    db.set_medication_paused(mid, uid, True)
    assert db.get_medication_by_id(mid, uid)["paused"] == 1
    db.set_medication_paused(mid, uid, False)
    assert db.get_medication_by_id(mid, uid)["paused"] == 0


def test_paused_excluded_from_scheduler(db):
    uid, mid = _med(db, 4002)
    assert any(r["medication_id"] == mid for r in db.get_active_schedule_rows())
    db.set_medication_paused(mid, uid, True)
    assert not any(r["medication_id"] == mid for r in db.get_active_schedule_rows())


def test_paused_excluded_from_user_schedules_and_adherence(db):
    uid, mid = _med(db, 4003)
    assert db.get_schedules_for_user(4003)            # есть правила
    assert db.get_adherence_rules(uid)
    db.set_medication_paused(mid, uid, True)
    assert db.get_schedules_for_user(4003) == []      # пропадает из «сегодня»/плана
    assert db.get_adherence_rules(uid) == []          # не входит в adherence


def test_paused_still_in_meds_list(db):
    """На паузе лекарство остаётся в списке управления (get_user_medications)."""
    uid, mid = _med(db, 4004)
    db.set_medication_paused(mid, uid, True)
    meds = db.get_user_medications(uid)
    assert [m["id"] for m in meds] == [mid]
    assert meds[0]["paused"] == 1


# ── toggle-хендлер ──────────────────────────────────────────────────────────

class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.edits = []

    async def answer(self, *a, **kw):
        pass

    async def edit_message_text(self, text, **kw):
        self.edits.append((text, kw.get("reply_markup")))


class FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.username = "u"


class FakeUpdate:
    def __init__(self, query, uid):
        self.callback_query = query
        self.effective_user = FakeUser(uid)


def _cbs(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_handler_pause_then_resume(db, monkeypatch):
    import handlers.meds as meds
    monkeypatch.setattr(meds, "get_tz_for_user", lambda _id: __import__("pytz").utc)
    uid, mid = _med(db, 4005)

    q = FakeQuery(f"med_pause:{mid}")
    run(meds.handle_pause_toggle(FakeUpdate(q, 4005), None))
    assert db.get_medication_by_id(mid, uid)["paused"] == 1
    text, markup = q.edits[-1]
    assert "на паузе" in text
    assert f"med_resume:{mid}" in _cbs(markup)        # кнопка стала «Возобновить»

    q2 = FakeQuery(f"med_resume:{mid}")
    run(meds.handle_pause_toggle(FakeUpdate(q2, 4005), None))
    assert db.get_medication_by_id(mid, uid)["paused"] == 0
    text2, markup2 = q2.edits[-1]
    assert "на паузе" not in text2
    assert f"med_pause:{mid}" in _cbs(markup2)
