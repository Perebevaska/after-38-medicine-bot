from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler,
                          CallbackQueryHandler, MessageHandler, filters)
from database import (get_caregiver_mode, set_caregiver_mode,
                      get_dependents, add_dependent, delete_dependent, count_dependents)
from constants import ADD_DEPENDENT_NAME, MAX_DEPENDENTS, DEPENDENT_NAME_MAX_LEN
from utils import handle_db_errors, escape_html


def _caregiver_text(enabled: bool, dependents: list) -> str:
    status = "✅ Включён" if enabled else "❌ Выключен"
    dep_count = len(dependents)
    lines = [
        "👨‍👩‍👧 <b>Caregiver-режим</b>\n",
        f"Статус: {status}",
    ]
    if enabled and dependents:
        lines.append(f"Подопечные ({dep_count} из {MAX_DEPENDENTS}):")
        for d in dependents:
            lines.append(f"  • {escape_html(d['name'])}")
    lines.append(
        "\n<i>Позволяет отслеживать приём лекарств для близких. "
        "При добавлении лекарства бот спросит «Для кого?».</i>"
    )
    return "\n".join(lines)


def _caregiver_keyboard(enabled: bool, dependents: list) -> InlineKeyboardMarkup:
    toggle_label = "✅ Включён — нажми чтобы выключить" if enabled else "❌ Выключен — нажми чтобы включить"
    rows = [[InlineKeyboardButton(toggle_label, callback_data="caregiver:toggle")]]
    if enabled:
        for d in dependents:
            rows.append([
                InlineKeyboardButton(f"👤 {d['name']}", callback_data=f"caregiver:noop"),
                InlineKeyboardButton("🗑 Удалить", callback_data=f"caregiver:delete:{d['id']}"),
            ])
        if len(dependents) < MAX_DEPENDENTS:
            rows.append([InlineKeyboardButton("➕ Добавить подопечного", callback_data="caregiver:add")])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="caregiver:back")])
    return InlineKeyboardMarkup(rows)


@handle_db_errors
async def handle_caregiver_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает страницу настроек Caregiver-режима."""
    query = update.callback_query
    await query.answer()
    tid = update.effective_user.id
    enabled = get_caregiver_mode(tid)
    dependents = get_dependents(tid)
    await query.edit_message_text(
        _caregiver_text(enabled, dependents),
        parse_mode="HTML",
        reply_markup=_caregiver_keyboard(enabled, dependents)
    )


@handle_db_errors
async def handle_caregiver_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает caregiver-режим вкл/выкл."""
    query = update.callback_query
    await query.answer()
    tid = update.effective_user.id
    set_caregiver_mode(tid, not get_caregiver_mode(tid))
    enabled = get_caregiver_mode(tid)
    dependents = get_dependents(tid)
    await query.edit_message_text(
        _caregiver_text(enabled, dependents),
        parse_mode="HTML",
        reply_markup=_caregiver_keyboard(enabled, dependents)
    )


@handle_db_errors
async def handle_caregiver_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог добавления подопечного."""
    query = update.callback_query
    await query.answer()
    tid = update.effective_user.id
    if count_dependents(tid) >= MAX_DEPENDENTS:
        await query.answer(f"Максимум {MAX_DEPENDENTS} подопечных", show_alert=True)
        return ConversationHandler.END
    await query.message.reply_text(
        f"Как зовут подопечного? (не более {DEPENDENT_NAME_MAX_LEN} символов):",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="caregiver:cancel_add")
        ]])
    )
    return ADD_DEPENDENT_NAME


@handle_db_errors
async def handle_caregiver_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает имя подопечного, сохраняет и показывает обновлённую страницу."""
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Имя не может быть пустым. Введи ещё раз:")
        return ADD_DEPENDENT_NAME
    if len(name) > DEPENDENT_NAME_MAX_LEN:
        await update.message.reply_text(
            f"Имя не может быть длиннее {DEPENDENT_NAME_MAX_LEN} символов. Попробуй ещё раз:"
        )
        return ADD_DEPENDENT_NAME
    tid = update.effective_user.id
    add_dependent(tid, name)
    enabled = get_caregiver_mode(tid)
    dependents = get_dependents(tid)
    await update.message.reply_text(
        f"✅ Подопечный <b>{escape_html(name)}</b> добавлен.\n\n" + _caregiver_text(enabled, dependents),
        parse_mode="HTML",
        reply_markup=_caregiver_keyboard(enabled, dependents)
    )
    return ConversationHandler.END


async def cancel_caregiver_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет добавление подопечного."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отменено.")
    return ConversationHandler.END


@handle_db_errors
async def handle_caregiver_delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подтверждение удаления подопечного."""
    query = update.callback_query
    await query.answer()
    dep_id = int(query.data.split(":")[2])
    tid = update.effective_user.id
    dependents = get_dependents(tid)
    dep = next((d for d in dependents if d["id"] == dep_id), None)
    if not dep:
        return
    await query.edit_message_text(
        f"⚠️ Удалить подопечного <b>{escape_html(dep['name'])}</b>?\n\n"
        f"Все их лекарства и история приёмов будут удалены.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"caregiver:delete_confirm:{dep_id}"),
             InlineKeyboardButton("❌ Нет", callback_data="caregiver:delete_cancel")],
        ])
    )


@handle_db_errors
async def handle_caregiver_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет подопечного и возвращается на страницу настроек caregiver."""
    from scheduler import clear_pending_for_medication
    query = update.callback_query
    await query.answer()
    dep_id = int(query.data.split(":")[2])
    tid = update.effective_user.id
    med_ids = delete_dependent(tid, dep_id)
    for mid in med_ids:
        clear_pending_for_medication(mid)
    enabled = get_caregiver_mode(tid)
    dependents = get_dependents(tid)
    await query.edit_message_text(
        "✅ Подопечный удалён.\n\n" + _caregiver_text(enabled, dependents),
        parse_mode="HTML",
        reply_markup=_caregiver_keyboard(enabled, dependents)
    )


@handle_db_errors
async def handle_caregiver_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет удаление, возвращается на страницу caregiver."""
    query = update.callback_query
    await query.answer()
    tid = update.effective_user.id
    enabled = get_caregiver_mode(tid)
    dependents = get_dependents(tid)
    await query.edit_message_text(
        _caregiver_text(enabled, dependents),
        parse_mode="HTML",
        reply_markup=_caregiver_keyboard(enabled, dependents)
    )


@handle_db_errors
async def handle_caregiver_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат из caregiver-страницы на главную страницу /settings."""
    from handlers.settings import fetch_settings_data, _settings_text, _settings_keyboard
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    tz, mode_label, presets, dp, caregiver_enabled = fetch_settings_data(user.id)
    await query.edit_message_text(
        _settings_text(tz, mode_label, presets, dp, caregiver_enabled),
        parse_mode="HTML",
        reply_markup=_settings_keyboard(mode_label, dp, caregiver_enabled, user.id)
    )


async def handle_caregiver_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заглушка для кнопок с именем подопечного (нажатие не вызывает действия)."""
    await update.callback_query.answer()


def get_handlers(cancel_handler):
    """Возвращает список handlers для caregiver-режима."""
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_caregiver_add_start, pattern="^caregiver:add$")],
        states={
            ADD_DEPENDENT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_caregiver_add_name),
            ],
        },
        fallbacks=[
            cancel_handler,
            CallbackQueryHandler(cancel_caregiver_add, pattern="^caregiver:cancel_add$"),
        ],
    )
    return [
        add_conv,
        CallbackQueryHandler(handle_caregiver_settings, pattern="^settings:caregiver$"),
        CallbackQueryHandler(handle_caregiver_toggle, pattern="^caregiver:toggle$"),
        CallbackQueryHandler(handle_caregiver_delete_prompt, pattern="^caregiver:delete:\\d+$"),
        CallbackQueryHandler(handle_caregiver_delete_confirm, pattern="^caregiver:delete_confirm:\\d+$"),
        CallbackQueryHandler(handle_caregiver_delete_cancel, pattern="^caregiver:delete_cancel$"),
        CallbackQueryHandler(handle_caregiver_back, pattern="^caregiver:back$"),
        CallbackQueryHandler(handle_caregiver_noop, pattern="^caregiver:noop$"),
    ]
