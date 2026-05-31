from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, CallbackQueryHandler, ConversationHandler,
                           MessageHandler, filters)
from database import (get_user_timezone, get_reminder_mode, set_reminder_mode,
                      get_user_time_presets, set_user_time_preset)
from constants import PRESET_TIME, SLOT_ORDER, SLOT_LABELS
from utils import handle_db_errors


def _parse_time(time_str: str) -> str:
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError
    return f"{h:02d}:{m:02d}"


def _settings_text(tz: str, mode_label: str, presets: dict) -> str:
    p = presets
    presets_line = f"🌅{p['morning']}  ☀️{p['lunch']}  🌇{p['evening']}  🌙{p['night']}"
    return (
        f"⚙️ *Настройки*\n\n"
        f"🌍 Часовой пояс: `{tz}`\n"
        f"🔔 Напоминания: {mode_label}\n"
        f"⏰ Время приёмов: {presets_line}"
    )


def _settings_keyboard(mode_label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Изменить часовой пояс", callback_data="settings:timezone")],
        [InlineKeyboardButton(f"Напоминания: {mode_label}", callback_data="settings:reminder")],
        [InlineKeyboardButton("⏰ Настроить время приёмов", callback_data="settings:presets")],
    ])


def _presets_keyboard(presets: dict) -> InlineKeyboardMarkup:
    rows = []
    for slot in SLOT_ORDER:
        rows.append([InlineKeyboardButton(
            f"✏️ {SLOT_LABELS[slot]}: {presets[slot]}",
            callback_data=f"preset:{slot}"
        )])
    return InlineKeyboardMarkup(rows)


@handle_db_errors
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tz = get_user_timezone(user.id)
    mode = get_reminder_mode(user.id)
    presets = get_user_time_presets(user.id)
    mode_label = "🔔 Один раз" if mode == "once" else "🔁 Повторять каждые 5 минут"
    await update.message.reply_text(
        _settings_text(tz, mode_label, presets),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(mode_label)
    )


@handle_db_errors
async def handle_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    mode = get_reminder_mode(user.id)
    new_mode = "repeat" if mode == "once" else "once"
    set_reminder_mode(user.id, new_mode)
    new_label = "🔁 Повторять каждые 5 минут" if new_mode == "repeat" else "🔔 Один раз"
    tz = get_user_timezone(user.id)
    presets = get_user_time_presets(user.id)
    await query.edit_message_text(
        _settings_text(tz, new_label, presets),
        parse_mode="Markdown",
        reply_markup=_settings_keyboard(new_label)
    )


@handle_db_errors
async def handle_show_presets(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    try:
        time_str = _parse_time(update.message.text.strip())
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
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Отменено.")
    return ConversationHandler.END


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *О проекте*\n\n"
        "After 30 Med Bot — вайб-кодинг проект: написан в паре с AI (Claude).\n"
        "Код живой, рабочий, итерируем дальше 🚀\n\n"
        "📦 [GitHub](https://github.com/Perebevaska/after-38-medicine-bot)\n\n"
        "*В планах:*\n"
        "💊 Напоминание о пополнении запаса таблеток\n"
        "👨‍👩‍👧 Caregiver режим — следить за приёмами другого пользователя\n"
        "📄 Экспорт истории в PDF\n"
        "📱 Telegram Mini App",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


def get_handler():
    return CallbackQueryHandler(handle_reminder_callback, pattern="^settings:reminder$")


def get_preset_handler(cancel_handler):
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
