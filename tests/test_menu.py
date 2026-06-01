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
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_menu_main_renders_menu():
    q = FakeQuery("menu:main")
    run(tz.handle_menu_callback(FakeUpdate(q), None))
    text, markup = q.edits[-1]
    assert text == tz._main_menu_text("U")
    cbs = _callbacks(markup)
    assert cbs == ["menu:today", "menu:meds", "menu:stats", "menu:settings", "menu:about"]


def test_menu_about_has_back():
    q = FakeQuery("menu:about")
    run(tz.handle_menu_callback(FakeUpdate(q), None))
    text, markup = q.edits[-1]
    assert text == ABOUT_TEXT
    assert "menu:main" in _callbacks(markup)


def test_menu_stats_period_has_back():
    q = FakeQuery("menu:stats")
    run(tz.handle_menu_callback(FakeUpdate(q), None))
    text, markup = q.edits[-1]
    assert text == "Выбери период:"
    cbs = _callbacks(markup)
    assert "stats:week" in cbs and "stats:plan" in cbs
    assert "menu:main" in cbs


def test_back_menu_kb_points_to_main():
    assert _callbacks(tz.back_menu_kb()) == ["menu:main"]
