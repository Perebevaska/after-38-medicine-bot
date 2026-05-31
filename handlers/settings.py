import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, CallbackQueryHandler, ConversationHandler,
                           MessageHandler, filters)
from database import (get_user_timezone, get_reminder_mode, set_reminder_mode,
                      get_user_time_presets, set_user_time_preset,
                      get_daily_plan_settings, set_daily_plan_enabled, set_daily_plan_time,
                      delete_user_data)
from scheduler import clear_pending_for_medication
from constants import PRESET_TIME, DAILY_PLAN_TIME, SLOT_ORDER, SLOT_LABELS
from utils import handle_db_errors, parse_time

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0


def _settings_text(tz: str, mode_label: str, presets: dict, daily_plan: dict) -> str:
    """Формирует текст страницы настроек с описанием всех параметров."""
    p = presets
    presets_line = f"🌅{p['morning']}  ☀️{p['lunch']}  🌇{p['evening']}  🌙{p['night']}"
    dp_line = f"✅ Вкл — {daily_plan['time']}" if daily_plan["enabled"] else "❌ Выкл"
    return (
        f"⚙️ *Настройки*\n\n"
        f"🌍 Часовой пояс: `{tz}`\n"
        f"🔔 Напоминания о приёме лекарств: {mode_label}\n"
        f"⏰ Время приёмов: {presets_line}\n"
        f"📋 План на день: {dp_line}\n\n"
        f"_🌍 Используется для точного времени напоминаний._\n"
        f"_🔔 «Один раз» — уведомление приходит один раз в назначенное время. "
        f"«Повторять» — каждые 5 мин до подтверждения приёма._\n"
        f"_⏰ Временные слоты при добавлении лекарства (Утро / Обед / Вечер / Ночь)._\n"
        f"_📋 Присылает утреннее сообщение со списком лекарств на сегодня._\n"
        f"_🗑 Удаляет все твои лекарства, расписания, историю приёмов и настройки._"
    )


def _settings_keyboard(mode_label: str, daily_plan: dict, telegram_id: int = 0) -> InlineKeyboardMarkup:
    """Inline-клавиатура настроек; добавляет кнопку Админ панели если telegram_id == ADMIN_ID."""
    dp_label = (
        f"📋 План на день: ✅ {daily_plan['time']}"
        if daily_plan["enabled"]
        else "📋 План на день: ❌ Выкл"
    )
    rows = [
        [InlineKeyboardButton("🌍 Изменить часовой пояс", callback_data="settings:timezone")],
        [InlineKeyboardButton(f"Напоминания о приёме лекарств: {mode_label}", callback_data="settings:reminder")],
        [InlineKeyboardButton("⏰ Настроить время приёмов", callback_data="settings:presets")],
        [InlineKeyboardButton(dp_label, callback_data="settings:daily_plan")],
        [InlineKeyboardButton("🗑 Удалить мои данные", callback_data="settings:delete")],
    ]
    if telegram_id == ADMIN_ID:
        rows.append([InlineKeyboardButton("🔧 Админ панель", callback_data="admin:panel")])
    return InlineKeyboardMarkup(rows)


def _daily_plan_keyboard(dp: dict) -> InlineKeyboardMarkup:
    """Inline-клавиатура настроек плана дня (вкл/выкл, время отправки, назад)."""
    toggle_label = "✅ Включён — нажми чтобы выключить" if dp["enabled"] else "❌ Выключен — нажми чтобы включить"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data="daily_plan:toggle")],
        [InlineKeyboardButton(f"⏰ Время отправки: {dp['time']}", callback_data="settings:daily_plan_time")],
        [InlineKeyboardButton("◀️ Назад", callback_data="daily_plan:back")],
    ])


def fetch_settings_data(telegram_id: int) -> tuple:
    """Возвращает (tz, mode_label, presets, daily_plan) для рендеринга настроек."""
    tz = get_user_timezone(telegram_id)
    mode = get_reminder_mode(telegram_id)
    presets = get_user_time_presets(telegram_id)
    dp = get_daily_plan_settings(telegram_id)
    mode_label = "🔔 Один раз" if mode == "once" else "🔁 Повторять каждые 5 минут"
    return tz, mode_label, presets, dp


def _presets_keyboard(presets: dict) -> InlineKeyboardMarkup:
    """Inline-клавиатура редактирования временных пресетов (Утро/Обед/Вечер/Ночь)."""
    rows = []
    for slot in SLOT_ORDER:
        rows.append([InlineKeyboardButton(
            f"✏️ {SLOT_LABELS[slot]}: {presets[slot]}",
            callback_data=f"preset:{slot}"
        )])
    return InlineKeyboardMarkup(rows)


@handle_db_errors
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /settings: показывает текущие настройки пользователя."""
    user = update.effective_user
    tz, mode_label, presets, dp = fetch_settings_data(user.id)
    await update.message.reply_text(
        _settings_text(tz, mode_label, presets, dp),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(mode_label, dp, user.id)
    )


@handle_db_errors
async def handle_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает режим напоминаний once ↔ repeat и обновляет страницу настроек."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    mode = get_reminder_mode(user.id)
    new_mode = "repeat" if mode == "once" else "once"
    set_reminder_mode(user.id, new_mode)
    tz, mode_label, presets, dp = fetch_settings_data(user.id)
    await query.edit_message_text(
        _settings_text(tz, mode_label, presets, dp),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(mode_label, dp, user.id)
    )


@handle_db_errors
async def handle_show_presets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает страницу редактирования временных пресетов приёма."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    presets = get_user_time_presets(user.id)
    await query.message.reply_text(
        "⏰ *Время приёмов*\n\nНажми чтобы изменить:",
        parse_mode="Markdown",
        reply_markup=_presets_keyboard(presets)
    )


@handle_db_errors
async def handle_preset_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор слота пресета (preset:morning/lunch/evening/night), запрашивает новое время."""
    query = update.callback_query
    await query.answer()
    slot = query.data.split(":")[1]
    context.user_data["preset_slot"] = slot
    label = SLOT_LABELS[slot]
    await query.message.reply_text(
        f"✏️ Введи новое время для *{label}* (ЧЧ:ММ, например 09:00):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_preset")
        ]])
    )
    return PRESET_TIME


@handle_db_errors
async def handle_preset_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает ввод нового времени пресета, валидирует и сохраняет."""
    try:
        time_str = parse_time(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Неверный формат. Введи время как ЧЧ:ММ, например 09:00:")
        return PRESET_TIME
    slot = context.user_data.get("preset_slot")
    user = update.effective_user
    set_user_time_preset(user.id, slot, time_str)
    presets = get_user_time_presets(user.id)
    label = SLOT_LABELS[slot]
    await update.message.reply_text(
        f"✅ *{label}* → {time_str}\n\nНажми чтобы изменить другое:",
        parse_mode="Markdown",
        reply_markup=_presets_keyboard(presets)
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет редактирование пресета и закрывает диалог."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Отменено.")
    return ConversationHandler.END


# ── Daily plan handlers ────────────────────────────────────────────────────

def _daily_plan_text(dp: dict) -> str:
    """Формирует текст страницы настройки плана дня."""
    status = "✅ Включён" if dp["enabled"] else "❌ Выключен"
    return (
        f"📋 *План на день*\n\n"
        f"Статус: {status}\n"
        f"Время отправки: {dp['time']}\n\n"
        f"Бот присылает список лекарств, которые сегодня нужно принять."
    )


@handle_db_errors
async def handle_daily_plan_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает страницу настроек плана дня."""
    query = update.callback_query
    await query.answer()
    dp = get_daily_plan_settings(update.effective_user.id)
    await query.edit_message_text(
        _daily_plan_text(dp),
        parse_mode="Markdown",
        reply_markup=_daily_plan_keyboard(dp)
    )


@handle_db_errors
async def handle_daily_plan_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает план дня вкл/выкл и обновляет страницу настроек."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    dp = get_daily_plan_settings(user.id)
    set_daily_plan_enabled(user.id, not dp["enabled"])
    dp = get_daily_plan_settings(user.id)
    await query.edit_message_text(
        _daily_plan_text(dp),
        parse_mode="Markdown",
        reply_markup=_daily_plan_keyboard(dp)
    )


@handle_db_errors
async def handle_daily_plan_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат со страницы плана дня на главную страницу настроек."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    tz, mode_label, presets, dp = fetch_settings_data(user.id)
    await query.edit_message_text(
        _settings_text(tz, mode_label, presets, dp),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(mode_label, dp, user.id)
    )


@handle_db_errors
async def handle_daily_plan_time_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает ввод нового времени отправки плана дня."""
    query = update.callback_query
    await query.answer()
    dp = get_daily_plan_settings(update.effective_user.id)
    await query.message.reply_text(
        f"⏰ Введи время отправки плана дня (ЧЧ:ММ):\nТекущее: {dp['time']}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_daily_plan_time")
        ]])
    )
    return DAILY_PLAN_TIME


@handle_db_errors
async def handle_daily_plan_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает ввод времени плана дня, валидирует и сохраняет."""
    try:
        time_str = parse_time(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Неверный формат. Введи время как ЧЧ:ММ, например 08:00:")
        return DAILY_PLAN_TIME
    user = update.effective_user
    set_daily_plan_time(user.id, time_str)
    dp = get_daily_plan_settings(user.id)
    await update.message.reply_text(
        f"✅ Время обновлено → {time_str}\n\n" + _daily_plan_text(dp),
        parse_mode="Markdown",
        reply_markup=_daily_plan_keyboard(dp)
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_daily_plan_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет ввод времени плана дня и возвращается на страницу плана."""
    query = update.callback_query
    await query.answer()
    dp = get_daily_plan_settings(update.effective_user.id)
    await query.edit_message_text(
        _daily_plan_text(dp),
        parse_mode="Markdown",
        reply_markup=_daily_plan_keyboard(dp)
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Delete data handlers ───────────────────────────────────────────────────

@handle_db_errors
async def handle_delete_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает запрос подтверждения полного удаления данных пользователя."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚠️ *Удаление данных*\n\n"
        "Это действие необратимо. Будут удалены:\n"
        "• Все лекарства и расписания\n"
        "• Вся история приёмов\n"
        "• Настройки (часовой пояс, напоминания)\n\n"
        "Уверен?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Да, удалить всё", callback_data="delete_data_confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="delete_data_cancel"),
        ]])
    )


@handle_db_errors
async def handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет все данные пользователя и очищает pending-напоминания."""
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    med_ids = delete_user_data(telegram_id)
    for med_id in med_ids:
        clear_pending_for_medication(med_id)
    await query.edit_message_text(
        "✅ Все твои данные удалены.\n\nНапиши /start чтобы начать заново."
    )


@handle_db_errors
async def handle_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет удаление данных и возвращается на страницу настроек."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    tz, mode_label, presets, dp = fetch_settings_data(user.id)
    await query.edit_message_text(
        _settings_text(tz, mode_label, presets, dp),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(mode_label, dp, user.id)
    )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /about: показывает информацию о проекте и планах развития."""
    await update.message.reply_text(
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


# ── Handler factories ──────────────────────────────────────────────────────

def get_handler():
    """Возвращает handler для переключения режима напоминаний."""
    return CallbackQueryHandler(handle_reminder_callback, pattern="^settings:reminder$")


def get_preset_handler(cancel_handler):
    """Возвращает ConversationHandler для редактирования временных пресетов."""
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_preset_select, pattern="^preset:")],
        states={
            PRESET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_preset_time_input)],
        },
        fallbacks=[
            cancel_handler,
            CallbackQueryHandler(cancel_preset, pattern="^cancel_preset$"),
        ],
    )


def get_daily_plan_time_handler(cancel_handler):
    """Возвращает ConversationHandler для ввода времени плана дня."""
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_daily_plan_time_select, pattern="^settings:daily_plan_time$")],
        states={
            DAILY_PLAN_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_daily_plan_time_input)],
        },
        fallbacks=[
            cancel_handler,
            CallbackQueryHandler(cancel_daily_plan_time, pattern="^cancel_daily_plan_time$"),
        ],
    )
