"""Экран «📦 Запас» лекарства (F5): остаток, расход за приём, порог, прогноз.

Управление запасом вынесено в отдельный экран у каждого лекарства — не трогает
add/edit-диалог. Списание происходит автоматически при «✅ Принял»
(см. scheduler.handle_intake_callback).
"""
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, CallbackQueryHandler,
                          MessageHandler, filters)

from database import (get_or_create_user, get_medication_by_id, get_schedules_by_medication,
                      set_medication_stock, add_medication_stock, set_units_per_dose,
                      set_low_stock_days, disable_stock_tracking)
from schedule_utils import days_of_stock_left
from utils import handle_db_errors, get_tz_for_user, escape_html
from constants import STOCK_INPUT

logger = logging.getLogger(__name__)


def _num(x) -> str:
    """Форматирует число без лишних нулей (30.0 → «30», 2.5 → «2.5»)."""
    return f"{x:g}"


def _stock_text(med, days_left) -> str:
    """Текст экрана запаса для лекарства med (row)."""
    name = escape_html(med["name"])
    if med["stock_qty"] is None:
        return (
            f"📦 <b>Запас: {name}</b>\n\n"
            "Учёт запаса выключен.\n\n"
            "<i>Укажи остаток — и бот предупредит, когда таблетки будут заканчиваться.</i>"
        )
    qty = _num(med["stock_qty"])
    units = _num(med["units_per_dose"] or 1)
    thr = med["low_stock_days"]
    if days_left is None:
        left_line = "—"
    elif days_left >= 365:
        left_line = "≥ 365 дн."
    else:
        left_line = f"~{days_left} дн."
    warn = "\n\n⚠️ <i>Запас заканчивается — пора пополнить.</i>" if (days_left is not None and days_left <= thr) else ""
    return (
        f"📦 <b>Запас: {name}</b>\n\n"
        f"Остаток: <b>{qty}</b> шт.\n"
        f"Расход за приём: {units} шт.\n"
        f"Порог предупреждения: {thr} дн.\n"
        f"Хватит примерно на: <b>{left_line}</b>{warn}"
    )


def _stock_keyboard(med) -> InlineKeyboardMarkup:
    """Клавиатура экрана запаса (разная для вкл/выкл трекинга)."""
    mid = med["id"]
    if med["stock_qty"] is None:
        rows = [
            [InlineKeyboardButton("📦 Указать запас", callback_data=f"stock_set:{mid}")],
            [InlineKeyboardButton(f"💊 Единиц за приём: {_num(med['units_per_dose'] or 1)}",
                                  callback_data=f"stock_units:{mid}")],
        ]
    else:
        rows = [
            [InlineKeyboardButton("➕ Пополнить", callback_data=f"stock_add:{mid}"),
             InlineKeyboardButton("✏️ Изменить остаток", callback_data=f"stock_set:{mid}")],
            [InlineKeyboardButton(f"💊 За приём: {_num(med['units_per_dose'] or 1)}",
                                  callback_data=f"stock_units:{mid}")],
            [InlineKeyboardButton(f"⏰ Порог: {med['low_stock_days']} дн.",
                                  callback_data=f"stock_thr:{mid}")],
            [InlineKeyboardButton("🚫 Выключить учёт", callback_data=f"stock_off:{mid}")],
        ]
    rows.append([InlineKeyboardButton("◀️ В меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


async def _render_stock(target, med_id: int, user, edit: bool):
    """Отрисовывает экран запаса (edit — редактирует сообщение, иначе шлёт новое)."""
    user_id = get_or_create_user(user.id, user.username)
    med = get_medication_by_id(med_id, user_id)
    if med is None:
        if edit:
            await target.edit_message_text("Лекарство не найдено.")
        else:
            await target.reply_text("Лекарство не найдено.")
        return
    rules = get_schedules_by_medication(med_id)
    today = datetime.now(get_tz_for_user(user.id)).date()
    days_left = days_of_stock_left(rules, med["stock_qty"], med["units_per_dose"], today)
    text, kb = _stock_text(med, days_left), _stock_keyboard(med)
    if edit:
        await target.edit_message_text(text, parse_mode="HTML",reply_markup=kb)
    else:
        await target.reply_text(text, parse_mode="HTML",reply_markup=kb)


@handle_db_errors
async def show_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает экран запаса (callback stock:<id>) — редактирует карточку лекарства."""
    query = update.callback_query
    await query.answer()
    med_id = int(query.data.split(":")[1])
    await _render_stock(query, med_id, update.effective_user, edit=True)


@handle_db_errors
async def stock_toggle_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выключает учёт запаса (stock_off:<id>)."""
    query = update.callback_query
    await query.answer("Учёт запаса выключен")
    med_id = int(query.data.split(":")[1])
    user_id = get_or_create_user(update.effective_user.id, update.effective_user.username)
    disable_stock_tracking(med_id, user_id)
    await _render_stock(query, med_id, update.effective_user, edit=True)


_PROMPTS = {
    "set":   "Введи текущий остаток (штук), например 30:",
    "add":   "Сколько штук добавить (пополнение упаковкой)?",
    "units": "Сколько единиц за один приём? (например 1 или 2):",
    "thr":   "За сколько дней до конца предупреждать? (например 5):",
}


@handle_db_errors
async def stock_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry: запрашивает число для поля запаса (stock_set/add/units/thr:<id>)."""
    query = update.callback_query
    await query.answer()
    field, mid = query.data.split(":")[0].replace("stock_", ""), int(query.data.split(":")[1])
    context.user_data["stock_field"] = field
    context.user_data["stock_med_id"] = mid
    await query.message.reply_text(
        _PROMPTS[field],
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data=f"stock_cancel:{mid}")
        ]])
    )
    return STOCK_INPUT


@handle_db_errors
async def stock_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает число и применяет к выбранному полю запаса."""
    field = context.user_data.get("stock_field")
    med_id = context.user_data.get("stock_med_id")
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    raw = update.message.text.strip().replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        await update.message.reply_text("Нужно число, например 30. Попробуй ещё раз:")
        return STOCK_INPUT

    if field in ("units",) and val <= 0:
        await update.message.reply_text("Должно быть больше нуля. Попробуй ещё раз:")
        return STOCK_INPUT
    if field in ("set", "add", "thr") and val < 0:
        await update.message.reply_text("Не может быть отрицательным. Попробуй ещё раз:")
        return STOCK_INPUT
    if field == "thr" and val < 1:
        await update.message.reply_text("Порог — минимум 1 день. Попробуй ещё раз:")
        return STOCK_INPUT

    if field == "set":
        set_medication_stock(med_id, user_id, val)
    elif field == "add":
        add_medication_stock(med_id, user_id, val)
    elif field == "units":
        set_units_per_dose(med_id, user_id, val)
    elif field == "thr":
        set_low_stock_days(med_id, user_id, int(val))

    context.user_data.pop("stock_field", None)
    context.user_data.pop("stock_med_id", None)
    await _render_stock(update.message, med_id, user, edit=False)

    # При ручном изменении остатка/расхода/порога уведомляем сразу, если запас уже ниже порога.
    # Событийное пересечение в handle_intake_callback не срабатывает в этих случаях.
    if field in ("set", "units", "thr"):
        try:
            med = get_medication_by_id(med_id, user_id)
            if med and med["stock_qty"] is not None:
                rules = get_schedules_by_medication(med_id)
                today = datetime.now(get_tz_for_user(user.id)).date()
                days_left = days_of_stock_left(rules, med["stock_qty"], med["units_per_dose"], today)
                if days_left is not None and days_left <= med["low_stock_days"]:
                    name = escape_html(med["name"])
                    qty = _num(med["stock_qty"])
                    await update.message.reply_text(
                        f"⚠️ <b>{name}</b> скоро закончится: осталось примерно на {days_left} дн. ({qty} шт.).\n"
                        f"Не забудь пополнить запас 📦",
                        parse_mode="HTML",
                    )
        except Exception as e:
            logger.error("Ошибка проверки порога запаса: %s", e)

    return ConversationHandler.END


@handle_db_errors
async def stock_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена ввода — возвращает экран запаса."""
    query = update.callback_query
    await query.answer()
    med_id = int(query.data.split(":")[1])
    context.user_data.pop("stock_field", None)
    context.user_data.pop("stock_med_id", None)
    await _render_stock(query, med_id, update.effective_user, edit=True)
    return ConversationHandler.END


def get_handlers(cancel_handler):
    """Handlers экрана запаса: показ/выключение + диалог ввода чисел."""
    input_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(stock_ask, pattern=r"^stock_(set|add|units|thr):\d+$"),
        ],
        states={
            STOCK_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, stock_receive)],
        },
        fallbacks=[
            cancel_handler,
            CallbackQueryHandler(stock_cancel, pattern=r"^stock_cancel:\d+$"),
        ],
    )
    return [
        input_conv,
        CallbackQueryHandler(show_stock, pattern=r"^stock:\d+$"),
        CallbackQueryHandler(stock_toggle_off, pattern=r"^stock_off:\d+$"),
    ]
