"""F1 — PDF «Отчёт для врача» (календарь приверженности): рендер и пустые случаи."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest


def run(coro):
    return asyncio.run(coro)


class FakeMessage:
    def __init__(self):
        self.replies = []
        self.documents = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)

    async def reply_document(self, document=None, filename=None, caption=None, **kw):
        self.documents.append((filename, document.getvalue() if document else b"", caption))


class FakeQuery:
    def __init__(self, data="export:doctor"):
        self.data = data
        self.message = FakeMessage()

    async def answer(self, *a, **kw):
        pass


class FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.username = "patient"


class FakeUpdate:
    def __init__(self, uid):
        self.callback_query = FakeQuery()
        self.effective_user = FakeUser(uid)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import database as d
    monkeypatch.setattr(d, "DB_PATH", str(tmp_path / "test.db"))
    d.init_db()
    d.migrate()
    import handlers.export as export
    return d, export


def _log(d, mid, days_ago, status):
    """Прямая вставка записи intake_log с taken_at N дней назад (UTC)."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with d.get_connection() as conn:
        conn.execute(
            "INSERT INTO intake_log (medication_id, scheduled_time, status, taken_at) VALUES (?, ?, ?, ?)",
            (mid, "09:00", status, ts))


def test_doctor_report_pdf_generated(env):
    d, export = env
    uid = d.get_or_create_user(6001, "patient")
    m1 = d.add_medication(uid, "Аспирин", "100мг", "after", 1)
    d.add_schedule_rule(m1, "09:00", "daily")
    m2 = d.add_medication(uid, "Витамин D", "1т", "any", 1)
    d.add_schedule_rule(m2, "09:00", "daily")
    # разноцветные дни: часть принято, часть пропущено
    for da in range(0, 10):
        _log(d, m1, da, "taken" if da % 2 == 0 else "skipped")
        _log(d, m2, da, "taken")

    upd = FakeUpdate(6001)
    run(export.export_doctor_report(upd, None))

    docs = upd.callback_query.message.documents
    assert len(docs) == 1
    filename, content, caption = docs[0]
    assert filename.startswith("doctor_report_") and filename.endswith(".pdf")
    assert content[:4] == b"%PDF"
    assert len(content) > 1500           # непустой календарь
    assert "врача" in caption


def test_doctor_report_no_meds(env):
    d, export = env
    d.get_or_create_user(6002, "patient")
    upd = FakeUpdate(6002)
    run(export.export_doctor_report(upd, None))
    assert upd.callback_query.message.documents == []
    assert any("Нет активных лекарств" in r for r in upd.callback_query.message.replies)


def test_doctor_report_paused_excluded(env):
    """Лекарство на паузе не попадает в отчёт (как и в adherence)."""
    d, export = env
    uid = d.get_or_create_user(6003, "patient")
    mid = d.add_medication(uid, "Магний", "1", "any", 1)
    d.add_schedule_rule(mid, "09:00", "daily")
    d.set_medication_paused(mid, uid, True)
    upd = FakeUpdate(6003)
    run(export.export_doctor_report(upd, None))
    # единственное лекарство на паузе → нечего показывать
    assert upd.callback_query.message.documents == []
