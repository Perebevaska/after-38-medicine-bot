from datetime import datetime
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim

_tf = TimezoneFinder()
_geolocator = Nominatim(user_agent="med_bot")
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from database import get_or_create_user, get_user_timezone, set_user_timezone, get_schedules_for_user, get_today_intake_statuses
from constants import SETUP_TZ, SETUP_CITY
from utils import handle_db_errors, get_tz_for_user, escape_md


def _geo_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура запроса геолокации или ручного ввода города."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить геолокацию", request_location=True)],
         [KeyboardButton("✍️ Ввести город вручную")]],
        resize_keyboard=True, one_time_keyboard=True
    )


def _main_menu_keyboard():
    """Inline-клавиатура главного меню."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Лекарства на сегодня", callback_data="menu:today")],
        [InlineKeyboardButton("💊 Мои лекарства", callback_data="menu:meds")],
        [InlineKeyboardButton("📊 Статистика", callback_data="menu:stats")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu:settings")],
        [InlineKeyboardButton("ℹ️ О проекте", callback_data="menu:about")],
    ])


async def show_main_menu(update, first_name, hint: str = ""):
    """Отправляет приветственное сообщение с главным меню. hint — опциональная подсказка."""
    text = f"Привет, {first_name}! 💊\n\nЯ помогу тебе не забывать принимать лекарства."
    if hint:
        text += f"\n\n{hint}"
    await update.message.reply_text(text, reply_markup=_main_menu_keyboard())


@handle_db_errors
async def handle_menu_callback(update, context):
    """Обрабатывает нажатия кнопок главного меню (menu:today/meds/stats/settings/about)."""
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    msg = query.message
    user = update.effective_user

    if action == "today":
        from scheduler import _rule_fires_today, _MEAL_LABELS
        rows = get_schedules_for_user(user.id)
        if not rows:
            await msg.reply_text("💊 Сегодня нет запланированных лекарств.")
            return
        user_tz = get_tz_for_user(user.id)
        today = datetime.now(user_tz).date()
        meds: dict = {}
        for row in rows:
            if not _rule_fires_today(row, today):
                continue
            mid = row["medication_id"]
            if mid not in meds:
                meds[mid] = {"name": row["name"], "meal_relation": row["meal_relation"], "times": []}
            dosage = row["rule_dosage"] or row["med_dosage"]
            meds[mid]["times"].append((row["reminder_time"], mid, dosage))
        if not meds:
            await msg.reply_text("💊 Сегодня нет запланированных лекарств.")
            return
        statuses = get_today_intake_statuses(user.id)
        lines = ["📋 *Лекарства на сегодня:*\n"]
        for med in meds.values():
            meal = _MEAL_LABELS.get(med["meal_relation"], "")
            lines.append(f"💊 *{escape_md(med['name'])}* — {meal}")
            for reminder_time, mid, dosage in sorted(med["times"]):
                st = statuses.get((mid, reminder_time))
                icon = "✅" if st == "taken" else ("❌" if st == "skipped" else "⏳")
                lines.append(f"   {icon} {reminder_time} — {escape_md(dosage)}")
        await msg.reply_text("\n".join(lines), parse_mode="Markdown")

    elif action == "meds":
        from handlers.meds import show_meds_list
        await show_meds_list(msg, user)

    elif action == "stats":
        await msg.reply_text(
            "Выбери период:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 За 7 дней", callback_data="stats:week")],
                [InlineKeyboardButton("📆 План на 7 дней", callback_data="stats:plan")],
            ])
        )

    elif action == "settings":
        from handlers.settings import _settings_text, _settings_keyboard, fetch_settings_data
        tz, mode_label, presets, dp = fetch_settings_data(user.id)
        await msg.reply_text(
            _settings_text(tz, mode_label, presets, dp),
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(mode_label, dp, user.id)
        )

    elif action == "about":
        await msg.reply_text(
            "ℹ️ *О проекте*\n\n"
            "After 30 Med Bot — вайб-кодинг проект: написан в паре с AI (Claude).\n"
            "Код живой, рабочий, итерируем дальше 🚀\n\n"
            "📦 [GitHub](https://github.com/Perebevaska/after-30-medicine-bot)\n\n"
            "*В планах:*\n"
            "💊 Напоминание о пополнении запаса таблеток\n"
            "👨‍👩‍👧 Caregiver режим — следить за приёмами другого пользователя\n"
            "📱 Telegram Mini App",
            parse_mode="Markdown",
            disable_web_page_preview=True
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


async def handle_settings_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point смены TZ из меню настроек (кнопка «Изменить часовой пояс»)."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Отправь геолокацию или введи город:",
        reply_markup=_geo_keyboard()
    )
    return SETUP_TZ


async def handle_tz_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Маршрутизирует текстовый ввод: «Ввести город вручную» → SETUP_CITY, иначе → handle_city_input."""
    if update.message.text == "✍️ Ввести город вручную":
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
