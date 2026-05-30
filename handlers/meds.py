from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler,
                          CallbackQueryHandler, MessageHandler, filters)
from database import (get_or_create_user, add_medication, add_schedule,
                      get_user_medications, deactivate_medication,
                      get_medication_by_id, get_schedules_by_medication, update_medication)
from constants import (NAME, DOSAGE, MEAL, TIMES, SCHEDULE,
                       EDIT_NAME, EDIT_DOSAGE, EDIT_MEAL, EDIT_TIMES, EDIT_SCHEDULE,
                       MEAL_LABELS)
from utils import handle_db_errors

_CANCEL_BTN = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]])


@handle_db_errors
async def meds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    meds = get_user_medications(user_id)

    if not meds:
        await update.message.reply_text(
            "У тебя пока нет лекарств.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Добавить лекарство", callback_data="add_med")
            ]])
        )
        return

    await update.message.reply_text("💊 Твои лекарства:")
    for med in meds:
        times = med["times"] or "не указано"
        meal = MEAL_LABELS.get(med["meal_relation"], med["meal_relation"])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{med['id']}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{med['id']}"),
        ]])
        await update.message.reply_text(
            f"*{med['name']}* — {med['dosage']}\n"
            f"🍽 {meal}\n"
            f"⏰ {times}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

    await update.message.reply_text(
        "➕ Хочешь добавить ещё?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Добавить лекарство", callback_data="add_med")
        ]])
    )


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Отменено.")
    return ConversationHandler.END


async def handle_add_med_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Как называется лекарство?", reply_markup=_CANCEL_BTN)
    return NAME


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Как называется лекарство?", reply_markup=_CANCEL_BTN)
    return NAME


async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        "Укажи дозировку (например: 500мг, 1 таблетка):",
        reply_markup=_CANCEL_BTN
    )
    return DOSAGE


async def add_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["dosage"] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton(label, callback_data=key)]
        for key, label in MEAL_LABELS.items()
    ]
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")])
    await update.message.reply_text("Как принимать?", reply_markup=InlineKeyboardMarkup(keyboard))
    return MEAL


async def add_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["meal"] = query.data
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(1, 5)],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ]
    await query.edit_message_text("Сколько раз в день?", reply_markup=InlineKeyboardMarkup(keyboard))
    return TIMES


async def add_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    times = int(query.data)
    context.user_data["times"] = times
    context.user_data["collected_times"] = []
    await query.edit_message_text(
        f"Укажи время 1 из {times} приёмов (формат ЧЧ:ММ, например 08:00):",
        reply_markup=_CANCEL_BTN
    )
    return SCHEDULE


@handle_db_errors
async def add_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text.strip()
    try:
        h, m = map(int, time_str.split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        await update.message.reply_text("Неверный формат. Введи время как ЧЧ:ММ, например 09:30:")
        return SCHEDULE

    context.user_data["collected_times"].append(time_str)
    collected = context.user_data["collected_times"]
    total = context.user_data["times"]

    if len(collected) < total:
        await update.message.reply_text(
            f"Время {len(collected)} из {total} принято. "
            f"Введи время {len(collected) + 1} из {total}:",
            reply_markup=_CANCEL_BTN
        )
        return SCHEDULE

    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    med_id = add_medication(user_id, context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"], total)
    for t in collected:
        add_schedule(med_id, t)

    meal_label = MEAL_LABELS[context.user_data["meal"]]
    await update.message.reply_text(
        f"✅ Лекарство добавлено!\n\n"
        f"💊 {context.user_data['name']} — {context.user_data['dosage']}\n"
        f"🍽 {meal_label}\n"
        f"⏰ Напоминания: {', '.join(collected)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


@handle_db_errors
async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    medication_id = int(query.data.split(":")[1])
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    deactivate_medication(medication_id, user_id)
    await query.edit_message_text("✅ Лекарство удалено из списка, напоминания отключены.")


@handle_db_errors
async def handle_edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    medication_id = int(query.data.split(":")[1])
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    med = get_medication_by_id(medication_id, user_id)
    schedules = get_schedules_by_medication(medication_id)
    context.user_data["edit_id"] = medication_id
    context.user_data["edit_user_id"] = user_id
    context.user_data["edit_med"] = {"name": med["name"], "dosage": med["dosage"]}
    times = ", ".join([s["reminder_time"] for s in schedules])
    await query.edit_message_text(
        f"Редактируем: *{med['name']}*\n"
        f"Дозировка: {med['dosage']}\n"
        f"Приём: {MEAL_LABELS[med['meal_relation']]}\n"
        f"Времена: {times}\n\n"
        f"Введи новое название (или `-` чтобы оставить `{med['name']}`):",
        parse_mode="Markdown"
    )
    return EDIT_NAME


async def edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    med = context.user_data["edit_med"]
    val = update.message.text.strip()
    context.user_data["edit_name"] = med["name"] if val == "-" else val
    await update.message.reply_text(
        f"Введи новую дозировку (или `-` чтобы оставить `{med['dosage']}`):"
    )
    return EDIT_DOSAGE


async def edit_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    med = context.user_data["edit_med"]
    val = update.message.text.strip()
    context.user_data["edit_dosage"] = med["dosage"] if val == "-" else val
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"editmeal:{key}")]
        for key, label in MEAL_LABELS.items()
    ]
    await update.message.reply_text(
        "Выбери способ приёма:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDIT_MEAL


async def edit_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_meal"] = query.data.split(":")[1]
    keyboard = [[InlineKeyboardButton(str(i), callback_data=f"edittimes:{i}") for i in range(1, 5)]]
    await query.edit_message_text("Сколько раз в день?", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_TIMES


async def edit_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    times = int(query.data.split(":")[1])
    context.user_data["edit_times"] = times
    context.user_data["edit_collected"] = []
    await query.edit_message_text(f"Введи время 1 из {times} (формат ЧЧ:ММ):")
    return EDIT_SCHEDULE


@handle_db_errors
async def edit_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text.strip()
    try:
        h, m = map(int, time_str.split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        await update.message.reply_text("Неверный формат. Введи время как ЧЧ:ММ:")
        return EDIT_SCHEDULE

    context.user_data["edit_collected"].append(time_str)
    collected = context.user_data["edit_collected"]
    total = context.user_data["edit_times"]

    if len(collected) < total:
        await update.message.reply_text(
            f"Время {len(collected)} из {total} принято. Введи время {len(collected)+1}:"
        )
        return EDIT_SCHEDULE

    user_id = context.user_data["edit_user_id"]
    update_medication(context.user_data["edit_id"], user_id,
                      context.user_data["edit_name"], context.user_data["edit_dosage"],
                      context.user_data["edit_meal"], total, collected)
    await update.message.reply_text(
        f"✅ Лекарство обновлено!\n\n"
        f"💊 {context.user_data['edit_name']} — {context.user_data['edit_dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['edit_meal']]}\n"
        f"⏰ {', '.join(collected)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


def get_add_handler(cancel_handler):
    """Возвращает ConversationHandler для добавления лекарства."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            CallbackQueryHandler(handle_add_med_callback, pattern="^add_med$"),
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dosage)],
            MEAL: [CallbackQueryHandler(add_meal, pattern="^(before|after|with|any)$")],
            TIMES: [CallbackQueryHandler(add_times, pattern="^[1-4]$")],
            SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_schedule_time)],
        },
        fallbacks=[
            cancel_handler,
            CallbackQueryHandler(cancel_add, pattern="^cancel_add$"),
        ],
    )


def get_edit_handler(cancel_handler):
    """Возвращает ConversationHandler для редактирования лекарства."""
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_edit_select, pattern="^edit:\\d+$")],
        states={
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name)],
            EDIT_DOSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_dosage)],
            EDIT_MEAL: [CallbackQueryHandler(edit_meal, pattern="^editmeal:")],
            EDIT_TIMES: [CallbackQueryHandler(edit_times, pattern="^edittimes:")],
            EDIT_SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_schedule)],
        },
        fallbacks=[cancel_handler],
    )
