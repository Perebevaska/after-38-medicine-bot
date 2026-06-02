import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_admin_stats
from utils import handle_db_errors

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0


@handle_db_errors
async def handle_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает админ-панель со статистикой; доступна только ADMIN_ID."""
    query = update.callback_query
    if update.effective_user.id != ADMIN_ID:
        await query.answer("Доступ запрещён.", show_alert=True)
        return
    await query.answer()
    stats = get_admin_stats()
    text = (
        f"🔧 <b>Админ панель</b>\n\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"💊 Активных лекарств: {stats['total_meds']}\n"
        f"📅 Активных сегодня: {stats['active_today']}"
    )
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Назад", callback_data="admin:back")
        ]])
    )


@handle_db_errors
async def handle_admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат с админ-панели на страницу настроек."""
    query = update.callback_query
    await query.answer()
    from handlers.settings import _settings_text, _settings_keyboard, fetch_settings_data
    user = update.effective_user
    tz, mode_label, presets, dp, cg = fetch_settings_data(user.id)
    await query.edit_message_text(
        _settings_text(tz, mode_label, presets, dp, cg),
        parse_mode="HTML",
        reply_markup=_settings_keyboard(mode_label, dp, cg, user.id)
    )
