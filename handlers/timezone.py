from datetime import datetime
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes, ConversationHandler
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim

_tf = TimezoneFinder()
_geolocator = Nominatim(user_agent="med_bot")
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from database import (get_or_create_user, get_user_timezone, set_user_timezone,
                      get_schedules_for_user, get_today_intake_statuses, log_intake)
from constants import SETUP_TZ, SETUP_CITY, ABOUT_TEXT
from utils import handle_db_errors, get_tz_for_user, escape_html, local_day_bounds_utc
import logging

logger = logging.getLogger(__name__)


def _geo_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура запроса геолокации или ручного ввода города."""
    rows = [
        [KeyboardButton("📍 Отправить геолокацию", request_location=True)],
        [KeyboardButton("✍️ Ввести город вручную")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


MINIAPP_URL = "https://medbot.isgood.host"


def _main_menu_keyboard():
    """Inline-клавиатура главного меню (F10-D: бот = напоминания + быстрая отметка).

    Управление лекарствами, статистика, настройки и забота — в приложении.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Открыть приложение", web_app=WebAppInfo(url=MINIAPP_URL))],
        [InlineKeyboardButton("📋 Препараты на сегодня", callback_data="menu:today")],
        [InlineKeyboardButton("ℹ️ О проекте", callback_data="menu:about")],
    ])


def back_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка «◀️ В меню» — возврат в главное меню (callback menu:main)."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="menu:main")]])


def _main_menu_text(first_name: str, hint: str = "") -> str:
    """Текст приветствия главного меню."""
    text = (
        f"Привет, {first_name}! 💊\n\n"
        "Напоминаю вовремя принять препараты и отмечаю приёмы одним касанием.\n"
        "Добавление препаратов, статистика, настройки и крутые фичи — "
        "в приложении 📱 (кнопка ниже)."
    )
    if hint:
        text += f"\n\n{hint}"
    return text


async def show_main_menu(update, first_name, hint: str = ""):
    """Отправляет приветственное сообщение с главным меню. hint — опциональная подсказка."""
    await update.message.reply_text(_main_menu_text(first_name, hint), parse_mode="HTML", reply_markup=_main_menu_keyboard())


def _owner_streak_hint(telegram_id: int, user_id: int) -> str:
    """Строка серии владельца для главного меню (F2): '🔥 N дней подряд' или ''.

    Считает только серию владельца (dependent_id=None); подопечные — на экране
    статистики. Любая ошибка → пустая строка (меню важнее мотивации)."""
    try:
        from database import get_streak_rows, get_intake_statuses_window
        from streak import streak_window, streaks_by_subject
        from streak import _streak_phrase
        rows = get_streak_rows(user_id)
        if not rows:
            return ""
        user_tz = get_tz_for_user(telegram_id)
        today, start_utc, end_utc = streak_window(user_tz)
        intakes = get_intake_statuses_window(user_id, start_utc, end_utc)
        subjects = streaks_by_subject(rows, intakes, user_tz, today)
        owner = next((s for s in subjects if s["dependent_id"] is None), None)
        if owner and owner["streak"] > 0:
            return _streak_phrase(owner["streak"])
    except Exception:
        pass
    return ""


def _today_keyboard(has_pending: bool) -> InlineKeyboardMarkup:
    """Клавиатура экрана «Лекарства на сегодня»: кнопка «Принять всё» если есть непринятые."""
    rows = []
    if has_pending:
        rows.append([InlineKeyboardButton("✅ Принять всё", callback_data="menu:take_all")])
    rows.append([InlineKeyboardButton("◀️ В меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


async def _render_today_screen(query, user):
    """Рендерит экран «Лекарства на сегодня» (edit-in-place)."""
    from schedule_utils import _rule_fires_today
    from constants import MEAL_LABELS_TEXT as _MEAL_LABELS
    rows = get_schedules_for_user(user.id)
    user_tz = get_tz_for_user(user.id)
    now_local = datetime.now(user_tz)
    today = now_local.date()
    meds: dict = {}
    for row in rows:
        if not _rule_fires_today(row, today):
            continue
        mid = row["medication_id"]
        if mid not in meds:
            meds[mid] = {"name": row["name"], "meal_relation": row["meal_relation"],
                         "dep_name": row["dependent_name"], "times": []}
        dosage = row["rule_dosage"] or row["med_dosage"]
        meds[mid]["times"].append((row["reminder_time"], mid, dosage))
    if not meds:
        await query.edit_message_text(
            "💊 Сегодня нет запланированных препаратов.",
            reply_markup=back_menu_kb()
        )
        return
    start_utc, end_utc = local_day_bounds_utc(user_tz, now_local)
    statuses = get_today_intake_statuses(user.id, start_utc, end_utc)
    lines = ["📋 <b>Препараты на сегодня:</b>\n"]
    pending_list = []
    for med in meds.values():
        meal = _MEAL_LABELS.get(med["meal_relation"], "")
        dep_label = f" <i>({escape_html(med['dep_name'])})</i>" if med["dep_name"] else ""
        lines.append(f"💊 <b>{escape_html(med['name'])}</b>{dep_label} — {meal}")
        for reminder_time, mid, dosage in sorted(med["times"]):
            st = statuses.get((mid, reminder_time))
            icon = "✅" if st == "taken" else ("❌" if st == "skipped" else "⏳")
            lines.append(f"   {icon} {reminder_time} — {escape_html(dosage)}")
            if st not in ("taken", "skipped"):
                pending_list.append((mid, reminder_time))
    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_today_keyboard(bool(pending_list))
    )


@handle_db_errors
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /menu — единая точка входа: открывает главное меню для навигации."""
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    await show_main_menu(update, user.first_name, hint=_owner_streak_hint(user.id, user_id))


@handle_db_errors
async def handle_menu_callback(update, context):
    """Навигация по главному меню (edit-in-place): menu:main/today/meds/stats/settings/about."""
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    msg = query.message
    user = update.effective_user

    if action == "main":
        user_id = get_or_create_user(user.id, user.username)
        await query.edit_message_text(
            _main_menu_text(user.first_name, _owner_streak_hint(user.id, user_id)),
            reply_markup=_main_menu_keyboard()
        )

    elif action == "today":
        await _render_today_screen(query, user)

    elif action == "take_all":
        # F6: принять все pending-приёмы за сегодня; skipped не перезаписываем
        from scheduler import _rule_fires_today, _pending, _update_stock_on_intake
        rows = get_schedules_for_user(user.id)
        user_tz = get_tz_for_user(user.id)
        now_local = datetime.now(user_tz)
        today = now_local.date()
        start_utc, end_utc = local_day_bounds_utc(user_tz, now_local)
        statuses = get_today_intake_statuses(user.id, start_utc, end_utc)
        for row in rows:
            if not _rule_fires_today(row, today):
                continue
            mid, t = row["medication_id"], row["reminder_time"]
            if statuses.get((mid, t)) in ("taken", "skipped"):
                continue
            try:
                old = log_intake(mid, t, "taken", start_utc, end_utc)
                _pending.pop((user.id, mid, t), None)
                await _update_stock_on_intake(
                    query.message.reply_text, mid, "taken", old, user.id, user_tz
                )
            except Exception as e:
                logger.error("take_all: ошибка для лекарства %s: %s", mid, e)
        await _render_today_screen(query, user)

    elif action == "about":
        await query.edit_message_text(
            ABOUT_TEXT,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=back_menu_kb()
        )


@handle_db_errors
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start: создаёт пользователя, запрашивает TZ если не задан."""
    user = update.effective_user
    get_or_create_user(user.id, user.username)
    tz = get_user_timezone(user.id)

    if tz == "UTC":
        await update.message.reply_text(
            f"Привет, {user.first_name}! 💊\n\n"
            "Для точных напоминаний мне нужен твой часовой пояс.\n"
            "Отправь геолокацию или введи город:",
            reply_markup=_geo_keyboard()
        )
        return SETUP_TZ

    await show_main_menu(update, user.first_name)
    return ConversationHandler.END


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /timezone: запускает флоу смены часового пояса."""
    await update.message.reply_text(
        "Отправь геолокацию или введи город:",
        reply_markup=_geo_keyboard()
    )
    return SETUP_TZ


async def handle_tz_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Маршрутизирует текстовый ввод: «Ввести город» → SETUP_CITY, иначе → геокодинг."""
    text = update.message.text
    if text == "✍️ Ввести город вручную":
        await update.message.reply_text(
            "Введи название города (можно на русском):",
            reply_markup=ReplyKeyboardRemove()
        )
        return SETUP_CITY
    return await handle_city_input(update, context)


@handle_db_errors
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Определяет TZ по переданной геолокации и сохраняет её для пользователя."""
    loc = update.message.location
    if loc is None:
        await update.message.reply_text(
            "📍 Геолокация недоступна на этом устройстве.\nВведи название своего города:",
            reply_markup=ReplyKeyboardRemove()
        )
        return SETUP_CITY
    tz_name = _tf.timezone_at(lat=loc.latitude, lng=loc.longitude)
    if tz_name:
        set_user_timezone(update.effective_user.id, tz_name)
        await update.message.reply_text(
            f"✅ Часовой пояс: <code>{tz_name}</code>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        await show_main_menu(update, update.effective_user.first_name,
                             hint="Открой 📱 <b>приложение</b> (кнопка ниже), чтобы добавить первый препарат.")
        return ConversationHandler.END
    await update.message.reply_text(
        "Не удалось определить часовой пояс. Введи город:",
        reply_markup=ReplyKeyboardRemove()
    )
    return SETUP_CITY


@handle_db_errors
async def handle_city_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Геокодирует введённый город через Nominatim и сохраняет найденный TZ."""
    city = update.message.text.strip()
    try:
        location = _geolocator.geocode(city, timeout=10)
    except (GeocoderTimedOut, GeocoderServiceError):
        await update.message.reply_text("Сервис геолокации недоступен. Попробуй ещё раз:")
        return SETUP_CITY
    if location:
        tz_name = _tf.timezone_at(lat=location.latitude, lng=location.longitude)
        if tz_name:
            set_user_timezone(update.effective_user.id, tz_name)
            await update.message.reply_text(
                f"✅ Часовой пояс: <code>{tz_name}</code>",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove()
            )
            await show_main_menu(update, update.effective_user.first_name,
                                 hint="Открой 📱 <b>приложение</b> (кнопка ниже), чтобы добавить первый препарат.")
            return ConversationHandler.END
    await update.message.reply_text("Город не найден. Попробуй ещё раз:")
    return SETUP_CITY
