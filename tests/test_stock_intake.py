"""Интеграционные тесты F5: списание запаса и предупреждение при приёме.

Гоняем scheduler.handle_intake_callback на временной БД с фейковым Telegram.
"""
import asyncio

import pytest


def run(coro):
    return asyncio.run(coro)


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()
        self.edited = []

    async def answer(self, *a, **kw):
        pass

    async def edit_message_text(self, text, **kw):
        self.edited.append(text)


class FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.username = "u"
        self.first_name = "U"


class FakeUpdate:
    def __init__(self, query, uid):
        self.callback_query = query
        self.effective_user = FakeUser(uid)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import database as d
    monkeypatch.setattr(d, "DB_PATH", str(tmp_path / "test.db"))
    d.init_db()
    d.migrate()
    import scheduler
    uid = d.get_or_create_user(7001, "u")
    mid = d.add_medication(uid, "Аспирин", "100мг", "after", 1)
    d.add_schedule_rule(mid, "09:00", "daily")
    return d, scheduler, mid


def _take(scheduler, mid):
    q = FakeQuery(f"taken:{mid}:09:00")
    run(scheduler.handle_intake_callback(FakeUpdate(q, 7001), None))
    return q


def test_intake_decrements_stock(env):
    d, scheduler, mid = env
    d.set_medication_stock(mid, 1, 10)        # user_id=1 (первый созданный)
    q = _take(scheduler, mid)
    assert d.get_medication_by_id(mid, 1)["stock_qty"] == 9
    assert q.edited and "записан" in q.edited[-1]


def test_warning_on_threshold_crossing(env):
    d, scheduler, mid = env
    d.set_medication_stock(mid, 1, 6)         # daily 1/день, порог 5 → после приёма 5 дн.
    d.set_low_stock_days(mid, 1, 5)
    q = _take(scheduler, mid)
    assert d.get_medication_by_id(mid, 1)["stock_qty"] == 5
    assert any("скоро закончится" in r for r in q.message.replies)


def test_no_warning_above_threshold(env):
    d, scheduler, mid = env
    d.set_medication_stock(mid, 1, 20)        # 20 дн. > порог 5 → без предупреждения
    q = _take(scheduler, mid)
    assert q.message.replies == []


def test_no_warning_when_tracking_off(env):
    d, scheduler, mid = env
    # запас не задан (NULL) — трекинг выключен
    q = _take(scheduler, mid)
    assert q.message.replies == []
    assert d.get_medication_by_id(mid, 1)["stock_qty"] is None


def test_double_take_decrements_once(env):
    d, scheduler, mid = env
    d.set_medication_stock(mid, 1, 10)
    _take(scheduler, mid)
    _take(scheduler, mid)                      # повторное «принял» — без двойного списания
    assert d.get_medication_by_id(mid, 1)["stock_qty"] == 9
