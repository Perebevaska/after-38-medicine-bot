"""Тесты единого меню (/menu) и навигации edit-in-place с кнопкой «◀️ В меню»."""
import asyncio

import handlers.timezone as tz
from constants import ABOUT_TEXT


def run(coro):
    return asyncio.run(coro)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.edits = []  # (text, reply_markup)

    async def answer(self, *a, **kw):
        pass

    async def edit_message_text(self, text, reply_markup=None, **kw):
        self.edits.append((text, reply_markup))

    @property
    def message(self):
        return self


class FakeUser:
    id = 123
    username = "u"
    first_name = "U"


class FakeUpdate:
    def __init__(self, query):
        self.callback_query = query
        self.effective_user = FakeUser()


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data is not None]


def test_menu_main_renders_menu(monkeypatch):
    import handlers.timezone as _tz
    monkeypatch.setattr(_tz, "get_or_create_user", lambda *a, **kw: 1)
    monkeypatch.setattr(_tz, "_owner_streak_hint", lambda *a, **kw: None)
    q = FakeQuery("menu:main")
    run(tz.handle_menu_callback(FakeUpdate(q), None))
    text, markup = q.edits[-1]
    assert text == tz._main_menu_text("U")
    cbs = _callbacks(markup)
    # F10-D: меню сведено к 3 пунктам (приложение / сегодня / о проекте)
    assert cbs == ["menu:today", "menu:about"]


def test_menu_about_has_back():
    q = FakeQuery("menu:about")
    run(tz.handle_menu_callback(FakeUpdate(q), None))
    text, markup = q.edits[-1]
    assert text == ABOUT_TEXT
    assert "menu:main" in _callbacks(markup)


def test_back_menu_kb_points_to_main():
    assert _callbacks(tz.back_menu_kb()) == ["menu:main"]


def test_today_keyboard_with_pending():
    kb = tz._today_keyboard(has_pending=True)
    cbs = _callbacks(kb)
    assert "menu:take_all" in cbs
    assert "menu:main" in cbs


def test_today_keyboard_no_pending():
    kb = tz._today_keyboard(has_pending=False)
    cbs = _callbacks(kb)
    assert "menu:take_all" not in cbs
    assert "menu:main" in cbs
