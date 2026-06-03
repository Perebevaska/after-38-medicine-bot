"""F10-C: пуш помощникам при автопропуске приёма подопечного (строгий режим).

Проверяем _apply_strict_autoskip: при просрочке приёма опекун (F7) и
наблюдатель локального близкого (F8) получают уведомление через ARQ-очередь.
Время фиксируем моком scheduler.datetime, ARQ-пул — фейком.
"""
import asyncio
import datetime as _dt

import scheduler


def run(coro):
    return asyncio.run(coro)


class _FakeDT:
    """datetime.now(tz) → детерминированный момент (14:00 локального дня)."""
    FIXED = _dt.datetime(2026, 6, 3, 14, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return tz.localize(cls.FIXED) if tz else cls.FIXED


class _FakePool:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, **kw):
        self.jobs.append((name, kw))


def _setup_overdue(db, monkeypatch):
    """Общая подготовка: фикс времени + фейковый ARQ-пул. Возвращает пул."""
    monkeypatch.setattr(scheduler, "datetime", _FakeDT)
    pool = _FakePool()
    monkeypatch.setattr(scheduler, "_arq_pool", pool)
    return pool


def test_caregiver_notified_on_missed_dose(db, monkeypatch):
    """F7: подопечный-аккаунт пропускает собственное лекарство → пуш опекуну."""
    dep_uid = db.get_or_create_user(8001, "depuser")
    db.get_or_create_user(8002, "careuser")
    # связь опекун→подопечный (confirm форсирует strict_mode=1, strict_hours=1)
    code = db.ensure_caregiver_code(8001)
    link = db.create_caregiver_link(8002, code)
    assert db.confirm_caregiver_link(link["id"], 8001) == "ok"
    # просроченное лекарство подопечного: reminder 10:00 + 1ч < 14:00 (мок)
    mid = db.add_medication(dep_uid, "Аспирин", "100мг", "any", 1)
    db.add_schedule_rule(mid, "10:00", "daily")

    pool = _setup_overdue(db, monkeypatch)
    run(scheduler._apply_strict_autoskip(db.get_active_schedule_rows()))

    # приём помечен пропущенным
    care_jobs = [kw for name, kw in pool.jobs if kw["chat_id"] == 8002]
    assert care_jobs, "опекун не получил уведомление о пропуске"
    assert "Пропущен" in care_jobs[0]["text"]
    assert "@depuser" in care_jobs[0]["text"]


def test_viewer_notified_on_missed_local_dependent(db, monkeypatch):
    """F8: пропуск лекарства локального близкого → пуш наблюдателю."""
    owner_uid = db.get_or_create_user(8101, "owner")
    db.get_or_create_user(8102, "viewer")
    dep_id = db.add_dependent(8101, "Бабушка")
    # шаринг: viewer запрашивает, владелец подтверждает
    sc = db.ensure_dep_share_code(dep_id, 8101)
    req = db.request_dep_share(8102, sc)
    db.confirm_dep_share(req["share_id"], 8101)
    # владелец в строгом режиме (1ч)
    db.set_strict_mode(8101, True, 1)
    mid = db.add_medication(owner_uid, "Витамин", "1таб", "any", 1, dependent_id=dep_id)
    db.add_schedule_rule(mid, "10:00", "daily")

    pool = _setup_overdue(db, monkeypatch)
    run(scheduler._apply_strict_autoskip(db.get_active_schedule_rows()))

    viewer_jobs = [kw for name, kw in pool.jobs if kw["chat_id"] == 8102]
    assert viewer_jobs, "наблюдатель не получил уведомление о пропуске"
    assert "Бабушка" in viewer_jobs[0]["text"]
    assert "Пропущен" in viewer_jobs[0]["text"]
