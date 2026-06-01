from datetime import datetime
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim

_tf = TimezoneFinder()
_geolocator = Nominatim(user_agent="med_bot")
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from database import get_or_create_user, get_user_timezone, set_user_timezone, get_schedules_for_user, get_today_intake_statuses
from constants import SETUP_TZ, SETUP_CITY, ABOUT_TEXT
from utils import handle_db_errors, get_tz_for_user, escape_md, local_day_bounds_utc


def _geo_keyboard(with_back: bool = False) -> ReplyKeyboardMarkup:
    """Клавиатура запроса геолокации или ручного ввода города.

    with_back=True добавляет кнопку «◀️ Назад» (для входа из /settings и /timezone).
    """
    rows = [
        [KeyboardButton("📍 Отправить геолокацию", request_location=True)],
        [KeyboardButton("✍️ Ввести город вручную")],
    ]
    if with_back:
        rows.append([KeyboardButton("◀️ Назад в настройки")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def _main_menu_keyboard():
    """Inline-клавиатура главного меню."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Лекарства на сегодня", callback_data="menu:today")],
        [InlineKeyboardButton("💊 Мои лекарства", callback_data="menu:meds")],
        [InlineKeyboardButton("📊 Статистика", callback_data="menu:stats")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu:settings")],
        [InlineKeyboardButton("ℹ️ О проекте", callback_data="menu:about")],
    ])


def back_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка «◀️ В меню» — возврат в главное меню (callback menu:main)."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="menu:main")]])


def _main_menu_text(first_name: str, hint: str = "") -> str:
    """Текст приветствия главного меню."""
    text = f"Привет, {first_name}! 💊\n\nЯ помогу тебе не забывать принимать лекарства."
    if hint:
        text += f"\n\n{hint}"
    return text


async def show_main_menu(update, first_name, hint: str = ""):
    """Отправляет приветственное сообщение с главным меню. hint — опциональная подсказка."""
    await update.message.reply_text(_main_menu_text(first_name, hint), reply_markup=_main_menu_keyboard())


@handle_db_errors
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /menu — единая точка входа: открывает главное меню для навигации."""
    user = update.effective_user
    get_or_create_user(user.id, user.username)
    await show_main_menu(update, user.first_name)


@handle_db_errors
async def handle_menu_callback(update, context):
    """Навигация по главному меню (edit-in-place): menu:main/today/meds/stats/settings/about."""
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    msg = query.message
    user = update.effective_user

    if action == "main":
        await query.edit_message_text(
            _main_menu_text(user.first_name),
            reply_markup=_main_menu_keyboard()
        )

    elif action == "today":
        from scheduler import _rule_fires_today, _MEAL_LABELS
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
                "💊 Сегодня нет запланированных лекарств.",
                reply_markup=back_menu_kb()
            )
            return
        start_utc, end_utc = local_day_bounds_utc(user_tz, now_local)
        statuses = get_today_intake_statuses(user.id, start_utc, end_utc)
        lines = ["📋 *Лекарства на сегодня:*\n"]
        for med in meds.values():
            meal = _MEAL_LABELS.get(med["meal_relation"], "")
            dep_label = f" _({escape_md(med['dep_name'])})_" if med["dep_name"] else ""
            lines.append(f"💊 *{escape_md(med['name'])}*{dep_label} — {meal}")
            for reminder_time, mid, dosage in sorted(med["times"]):
                st = statuses.get((mid, reminder_time))
                icon = "✅" if st == "taken" else ("❌" if st == "skipped" else "⏳")
                lines.append(f"   {icon} {reminder_time} — {escape_md(dosage)}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown", reply_markup=back_menu_kb()
        )

    elif action == "meds":
        from handlers.meds import show_meds_list
        await show_meds_list(msg, user)

    elif action == "stats":
        from handlers.stats import _stats_period_keyboard
        await query.edit_message_text("Выбери период:", reply_markup=_stats_period_keyboard())

    elif action == "settings":
        from handlers.settings import _settings_text, _settings_keyboard, fetch_settings_data
        tz, mode_label, presets, dp, cg = fetch_settings_data(user.id)
        await query.edit_message_text(
            _settings_text(tz, mode_label, presets, dp, cg),
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(mode_label, dp, cg, user.id)
        )

    elif action == "about":
        await query.edit_message_text(
            ABOUT_TEXT,
            parse_mode="Markdown",
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
        reply_markup=_geo_keyboard(with_back=True)
    )
    return SETUP_TZ


async def handle_settings_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point смены TZ из меню настроек (кнопка «Изменить часовой пояс»)."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Отправь геолокацию или введи город:",
        reply_markup=_geo_keyboard(with_back=True)
    )
    return SETUP_TZ


async def _back_to_settings_from_tz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закрывает флоу TZ и возвращает пользователя на страницу /settings."""
    from handlers.settings import fetch_settings_data, _settings_text, _settings_keyboard
    user = update.effective_user
    tz, mode_label, presets, dp, cg = fetch_settings_data(user.id)
    # Сначала убираем reply-клавиатуру отдельным сообщением, затем рисуем настройки.
    await update.message.reply_text("⚙️ Возврат в настройки", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text(
        _settings_text(tz, mode_label, presets, dp, cg),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(mode_label, dp, cg, user.id)
    )
    return ConversationHandler.END


async def handle_tz_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Маршрутизирует текстовый ввод: «Назад» → /settings, «Ввести город» → SETUP_CITY, иначе → геокодинг."""
    text = update.message.text
    if text == "◀️ Назад в настройки":
        return await _back_to_settings_from_tz(update, context)
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
            f"✅ Часовой пояс: *{tz_name}*",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        await show_main_menu(update, update.effective_user.first_name,
                             hint="Нажми 💊 *Мои лекарства*, чтобы добавить первое лекарство.")
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
                f"✅ Часовой пояс: *{tz_name}*",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove()
            )
            await show_main_menu(update, update.effective_user.first_name,
                                 hint="Нажми 💊 *Мои лекарства*, чтобы добавить первое лекарство.")
            return ConversationHandler.END
    await update.message.reply_text("Город не найден. Попробуй ещё раз:")
    return SETUP_CITY
