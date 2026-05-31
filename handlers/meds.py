from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler,
                          CallbackQueryHandler, MessageHandler, filters)
from database import (get_or_create_user, add_medication, add_schedule_rule,
                      get_user_medications, deactivate_medication,
                      get_medication_by_id, get_schedules_by_medication, update_medication,
                      count_active_medications)
from scheduler import clear_pending_for_medication
from constants import (NAME, DOSAGE, MEAL, TIMES, SCHEDULE,
                       EDIT_NAME, EDIT_DOSAGE, EDIT_MEAL, EDIT_TIMES, EDIT_SCHEDULE,
                       FREQ_TYPE, FREQ_INTERVAL, FREQ_WEEKDAYS, FREQ_MONTHDAY, FREQ_TIME,
                       EDIT_FREQ_TYPE, EDIT_FREQ_INTERVAL, EDIT_FREQ_WEEKDAYS,
                       EDIT_FREQ_MONTHDAY, EDIT_FREQ_TIME,
                       MEAL_LABELS, MAX_MEDICATIONS_PER_USER)
from utils import handle_db_errors

WEEKDAY_NAMES = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}

_CANCEL_BTN = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]])

_EDIT_NAME_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("➡️ Оставить текущее", callback_data="keep_edit_name")],
    [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
])
_EDIT_DOSAGE_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("➡️ Оставить текущее", callback_data="keep_edit_dosage")],
    [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
])


def _freq_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Каждый день", callback_data="freq:daily")],
        [InlineKeyboardButton("🔄 Через N дней", callback_data="freq:interval")],
        [InlineKeyboardButton("📆 По дням недели", callback_data="freq:weekdays")],
        [InlineKeyboardButton("🗓 Раз в месяц", callback_data="freq:monthly")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _edit_freq_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Оставить расписание", callback_data="keep_edit_schedule")],
        [InlineKeyboardButton("📅 Каждый день", callback_data="editfreq:daily")],
        [InlineKeyboardButton("🔄 Через N дней", callback_data="editfreq:interval")],
        [InlineKeyboardButton("📆 По дням недели", callback_data="editfreq:weekdays")],
        [InlineKeyboardButton("🗓 Раз в месяц", callback_data="editfreq:monthly")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _weekdays_keyboard(selected: set) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(
            f"✅ {name}" if d in selected else name,
            callback_data=f"weekday:{d}"
        )
        for d, name in WEEKDAY_NAMES.items()
    ]
    return InlineKeyboardMarkup([
        row[:4], row[4:],
        [InlineKeyboardButton("✔️ Готово", callback_data="weekdays_confirm"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _edit_weekdays_keyboard(selected: set) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(
            f"✅ {name}" if d in selected else name,
            callback_data=f"editweekday:{d}"
        )
        for d, name in WEEKDAY_NAMES.items()
    ]
    return InlineKeyboardMarkup([
        row[:4], row[4:],
        [InlineKeyboardButton("✔️ Готово", callback_data="edit_weekdays_confirm"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _edit_meal_keyboard(current_label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"➡️ Оставить ({current_label})", callback_data="keep_edit_meal")]]
        + [[InlineKeyboardButton(label, callback_data=f"editmeal:{key}")] for key, label in MEAL_LABELS.items()]
        + [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]]
    )


def _edit_times_keyboard(current_times: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"➡️ Оставить ({current_times} раз)", callback_data="keep_edit_times")],
        [InlineKeyboardButton(str(i), callback_data=f"edittimes:{i}") for i in range(1, 5)],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _format_schedule_rule(rule) -> str:
    time = rule["reminder_time"]
    freq = rule["frequency"]
    if freq == "daily":
        return time
    if freq == "interval":
        return f"каждые {rule['interval_days']} дн. в {time}"
    if freq == "weekdays":
        days = [WEEKDAY_NAMES[int(d)] for d in rule["weekdays"].split(",") if d]
        return f"{', '.join(days)} в {time}"
    if freq == "monthly":
        return f"{rule['month_day']}-го числа в {time}"
    return time


def _freq_label(freq: str, interval_days, weekdays_str, month_day) -> str:
    if freq == "daily":
        return "каждый день"
    if freq == "interval":
        return f"каждые {interval_days} дн."
    if freq == "weekdays" and weekdays_str:
        days = [WEEKDAY_NAMES[int(d)] for d in weekdays_str.split(",") if d]
        return ", ".join(days)
    if freq == "monthly":
        return f"{month_day}-го числа"
    return freq


# ── Display ────────────────────────────────────────────────────────────────

async def show_meds_list(message, user):
    user_id = get_or_create_user(user.id, user.username)
    meds = get_user_medications(user_id)

    if not meds:
        await message.reply_text(
            "У тебя пока нет лекарств.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Добавить лекарство", callback_data="add_med")
            ]])
        )
        return

    await message.reply_text("💊 Твои лекарства:")
    for med in meds:
        rules = get_schedules_by_medication(med["id"])
        has_advanced = any(r["frequency"] != "daily" for r in rules)
        if not has_advanced:
            schedule_str = ", ".join(r["reminder_time"] for r in rules) or "не указано"
        else:
            schedule_str = "\n".join(_format_schedule_rule(r) for r in rules) or "не указано"
        meal = MEAL_LABELS.get(med["meal_relation"], med["meal_relation"])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{med['id']}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{med['id']}"),
        ]])
        text = (
            f"*{med['name']}* — {med['dosage']}\n"
            f"🍽 {meal}\n"
        )
        if not has_advanced:
            text += f"🔢 {med['times_per_day']} раз в день\n"
        text += f"⏰ {schedule_str}"
        await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

    await message.reply_text(
        "➕ Хочешь добавить ещё?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Добавить лекарство", callback_data="add_med")
        ]])
    )


@handle_db_errors
async def meds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_meds_list(update.message, update.effective_user)


# ── Common ─────────────────────────────────────────────────────────────────

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Отменено.")
    return ConversationHandler.END


def _parse_time(time_str: str) -> str:
    """Парсит и нормализует время в формат ЧЧ:ММ. Поднимает ValueError при ошибке."""
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError
    return f"{h:02d}:{m:02d}"


# ── Add flow: entry ────────────────────────────────────────────────────────

async def handle_add_med_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    if count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
        await query.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств."
        )
        return ConversationHandler.END
    await query.message.reply_text("Как называется лекарство?", reply_markup=_CANCEL_BTN)
    return NAME


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    if count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
        await update.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств."
        )
        return ConversationHandler.END
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
        [InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(1, 5)],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ]
    await update.message.reply_text(
        "Сколько раз в день?\n_Или введи своё число:_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return TIMES


async def add_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["meal"] = query.data
    await query.edit_message_text("Тип расписания:", reply_markup=_freq_type_keyboard())
    return FREQ_TYPE


# ── Add flow: standard daily ───────────────────────────────────────────────

async def add_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["times"] = int(query.data)
    keyboard = [
        [InlineKeyboardButton(label, callback_data=key)]
        for key, label in MEAL_LABELS.items()
    ]
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")])
    await query.edit_message_text("Как принимать с пищей?", reply_markup=InlineKeyboardMarkup(keyboard))
    return MEAL


async def add_times_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        times = int(update.message.text.strip())
        assert 1 <= times <= 10
    except (ValueError, AssertionError):
        await update.message.reply_text("Введи число от 1 до 10:", reply_markup=_CANCEL_BTN)
        return TIMES
    context.user_data["times"] = times
    keyboard = [
        [InlineKeyboardButton(label, callback_data=key)]
        for key, label in MEAL_LABELS.items()
    ]
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")])
    await update.message.reply_text("Как принимать с пищей?", reply_markup=InlineKeyboardMarkup(keyboard))
    return MEAL


@handle_db_errors
async def add_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        time_str = _parse_time(update.message.text.strip())
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
    if count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
        await update.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств."
        )
        context.user_data.clear()
        return ConversationHandler.END

    med_id = add_medication(user_id, context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"], total)
    for t in collected:
        add_schedule_rule(med_id, t, "daily")

    await update.message.reply_text(
        f"✅ Лекарство добавлено!\n\n"
        f"💊 {context.user_data['name']} — {context.user_data['dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ Напоминания: {', '.join(collected)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Add flow: advanced scheduling ──────────────────────────────────────────

async def choose_freq_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    freq = query.data.split(":")[1]
    context.user_data["freq_type"] = freq

    if freq == "daily":
        total = context.user_data.get("times", 1)
        context.user_data["collected_times"] = []
        await query.edit_message_text(
            f"Укажи время 1 из {total} приёмов (формат ЧЧ:ММ, например 08:00):",
            reply_markup=_CANCEL_BTN
        )
        return SCHEDULE

    if freq == "interval":
        await query.edit_message_text("Каждые сколько дней? (например: 2):", reply_markup=_CANCEL_BTN)
        return FREQ_INTERVAL

    if freq == "weekdays":
        context.user_data["freq_weekdays"] = set()
        await query.edit_message_text(
            "Выбери дни недели, затем нажми Готово:",
            reply_markup=_weekdays_keyboard(set())
        )
        return FREQ_WEEKDAYS

    if freq == "monthly":
        await query.edit_message_text("Какого числа каждого месяца? (1–31):", reply_markup=_CANCEL_BTN)
        return FREQ_MONTHDAY

    return FREQ_TYPE


async def add_freq_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        assert 2 <= n <= 90
    except (ValueError, AssertionError):
        await update.message.reply_text("Введи число от 2 до 90:", reply_markup=_CANCEL_BTN)
        return FREQ_INTERVAL
    context.user_data["freq_interval_days"] = n
    total = context.user_data.get("times", 1)
    await update.message.reply_text(
        f"Укажи время 1 из {total} приёмов (формат ЧЧ:ММ, например 08:00):", reply_markup=_CANCEL_BTN
    )
    return FREQ_TIME


async def toggle_weekday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = int(query.data.split(":")[1])
    selected = context.user_data.setdefault("freq_weekdays", set())
    selected.discard(day) if day in selected else selected.add(day)
    await query.edit_message_reply_markup(reply_markup=_weekdays_keyboard(selected))
    return FREQ_WEEKDAYS


async def confirm_weekdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("freq_weekdays", set())
    if not selected:
        await query.answer("Выбери хотя бы один день", show_alert=True)
        return FREQ_WEEKDAYS
    await query.answer()
    total = context.user_data.get("times", 1)
    await query.edit_message_text(
        f"Укажи время 1 из {total} приёмов (формат ЧЧ:ММ, например 08:00):", reply_markup=_CANCEL_BTN
    )
    return FREQ_TIME


async def add_freq_monthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        day = int(update.message.text.strip())
        assert 1 <= day <= 31
    except (ValueError, AssertionError):
        await update.message.reply_text("Введи число от 1 до 31:", reply_markup=_CANCEL_BTN)
        return FREQ_MONTHDAY
    context.user_data["freq_month_day"] = day
    total = context.user_data.get("times", 1)
    await update.message.reply_text(
        f"Укажи время 1 из {total} приёмов (формат ЧЧ:ММ, например 08:00):", reply_markup=_CANCEL_BTN
    )
    return FREQ_TIME


@handle_db_errors
async def add_freq_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        time_str = _parse_time(update.message.text.strip())
    except Exception:
        await update.message.reply_text("Неверный формат. Введи время как ЧЧ:ММ, например 09:30:")
        return FREQ_TIME

    collected = context.user_data.setdefault("freq_collected_times", [])
    collected.append(time_str)
    total = context.user_data.get("times", 1)

    if len(collected) < total:
        await update.message.reply_text(
            f"Время {len(collected)} из {total} принято. "
            f"Введи время {len(collected) + 1} из {total}:",
            reply_markup=_CANCEL_BTN
        )
        return FREQ_TIME

    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    if count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
        await update.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств."
        )
        context.user_data.clear()
        return ConversationHandler.END

    freq = context.user_data["freq_type"]
    interval_days = context.user_data.get("freq_interval_days")
    weekdays_set = context.user_data.get("freq_weekdays", set())
    weekdays = ",".join(str(d) for d in sorted(weekdays_set)) or None
    month_day = context.user_data.get("freq_month_day")
    anchor_date = date.today().isoformat() if freq == "interval" else None

    med_id = add_medication(user_id, context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"], total)
    for t in collected:
        add_schedule_rule(med_id, t, freq,
                          interval_days=interval_days, weekdays=weekdays,
                          month_day=month_day, anchor_date=anchor_date)

    freq_label = _freq_label(freq, interval_days, weekdays, month_day)
    await update.message.reply_text(
        f"✅ Лекарство добавлено!\n\n"
        f"💊 {context.user_data['name']} — {context.user_data['dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(collected)} — {freq_label}"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Edit flow: entry & name/dosage ─────────────────────────────────────────

@handle_db_errors
async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    medication_id = int(query.data.split(":")[1])
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    deactivate_medication(medication_id, user_id)
    clear_pending_for_medication(medication_id)
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
    schedule_rules = [dict(s) for s in schedules]
    context.user_data["edit_id"] = medication_id
    context.user_data["edit_user_id"] = user_id
    context.user_data["edit_med"] = {
        "name": med["name"],
        "dosage": med["dosage"],
        "meal_relation": med["meal_relation"],
        "times_per_day": med["times_per_day"],
        "schedule_rules": schedule_rules,
    }
    schedule_str = "\n".join(_format_schedule_rule(r) for r in schedule_rules) or "не указано"
    await query.edit_message_text(
        f"Редактируем: *{med['name']}*\n"
        f"Дозировка: {med['dosage']}\n"
        f"Приём: {MEAL_LABELS[med['meal_relation']]}\n"
        f"Расписание: {schedule_str}\n\n"
        f"Введи новое название:",
        parse_mode="Markdown",
        reply_markup=_EDIT_NAME_KB
    )
    return EDIT_NAME


async def keep_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    med = context.user_data["edit_med"]
    context.user_data["edit_name"] = med["name"]
    await query.edit_message_text(
        f"Введи новую дозировку\n(текущая: *{med['dosage']}*):",
        parse_mode="Markdown",
        reply_markup=_EDIT_DOSAGE_KB
    )
    return EDIT_DOSAGE


async def edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["edit_name"] = update.message.text.strip()
    med = context.user_data["edit_med"]
    await update.message.reply_text(
        f"Введи новую дозировку\n(текущая: *{med['dosage']}*):",
        parse_mode="Markdown",
        reply_markup=_EDIT_DOSAGE_KB
    )
    return EDIT_DOSAGE


async def keep_edit_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_dosage"] = context.user_data["edit_med"]["dosage"]
    await query.edit_message_text("Выбери тип расписания:", reply_markup=_edit_freq_type_keyboard())
    return EDIT_FREQ_TYPE


async def edit_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["edit_dosage"] = update.message.text.strip()
    await update.message.reply_text("Выбери тип расписания:", reply_markup=_edit_freq_type_keyboard())
    return EDIT_FREQ_TYPE


# ── Edit flow: freq type ───────────────────────────────────────────────────

@handle_db_errors
async def keep_edit_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    edit_med = context.user_data["edit_med"]
    user_id = context.user_data["edit_user_id"]
    update_medication(
        context.user_data["edit_id"], user_id,
        context.user_data["edit_name"], context.user_data["edit_dosage"],
        edit_med["meal_relation"], edit_med["times_per_day"],
        edit_med["schedule_rules"]
    )
    schedule_str = "\n".join(_format_schedule_rule(r) for r in edit_med["schedule_rules"])
    await query.edit_message_text(
        f"✅ Лекарство обновлено!\n\n"
        f"💊 {context.user_data['edit_name']} — {context.user_data['edit_dosage']}\n"
        f"🍽 {MEAL_LABELS[edit_med['meal_relation']]}\n"
        f"⏰ {schedule_str}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def choose_edit_freq_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    freq = query.data.split(":")[1]
    context.user_data["edit_freq_type"] = freq
    edit_med = context.user_data["edit_med"]
    current_label = MEAL_LABELS.get(edit_med["meal_relation"], edit_med["meal_relation"])
    await query.edit_message_text(
        "Выбери способ приёма:",
        reply_markup=_edit_meal_keyboard(current_label)
    )
    return EDIT_MEAL


# ── Edit flow: meal → route by freq type ──────────────────────────────────

async def keep_edit_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_meal"] = context.user_data["edit_med"]["meal_relation"]
    return await _route_after_edit_meal(query, context)


async def edit_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_meal"] = query.data.split(":")[1]
    return await _route_after_edit_meal(query, context)


async def _route_after_edit_meal(query, context):
    freq = context.user_data.get("edit_freq_type", "daily")
    edit_med = context.user_data["edit_med"]

    if freq == "daily":
        await query.edit_message_text(
            "Сколько раз в день?\n_Или введи своё число:_",
            reply_markup=_edit_times_keyboard(edit_med["times_per_day"]),
            parse_mode="Markdown"
        )
        return EDIT_TIMES

    edit_med = context.user_data["edit_med"]
    if "edit_times" not in context.user_data:
        context.user_data["edit_times"] = edit_med["times_per_day"]

    if freq == "interval":
        await query.edit_message_text("Каждые сколько дней? (например: 2):", reply_markup=_CANCEL_BTN)
        return EDIT_FREQ_INTERVAL

    if freq == "weekdays":
        context.user_data["edit_freq_weekdays"] = set()
        await query.edit_message_text(
            "Выбери дни недели, затем нажми Готово:",
            reply_markup=_edit_weekdays_keyboard(set())
        )
        return EDIT_FREQ_WEEKDAYS

    if freq == "monthly":
        await query.edit_message_text("Какого числа каждого месяца? (1–31):", reply_markup=_CANCEL_BTN)
        return EDIT_FREQ_MONTHDAY

    return EDIT_TIMES


# ── Edit flow: standard daily ──────────────────────────────────────────────

async def edit_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    times = int(query.data.split(":")[1])
    context.user_data["edit_times"] = times
    context.user_data["edit_collected"] = []
    await query.edit_message_text(
        f"Введи время 1 из {times} (формат ЧЧ:ММ, например 08:00):",
        reply_markup=_CANCEL_BTN
    )
    return EDIT_SCHEDULE


async def edit_times_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        times = int(update.message.text.strip())
        assert 1 <= times <= 10
    except (ValueError, AssertionError):
        await update.message.reply_text("Введи число от 1 до 10:", reply_markup=_CANCEL_BTN)
        return EDIT_TIMES
    context.user_data["edit_times"] = times
    context.user_data["edit_collected"] = []
    await update.message.reply_text(
        f"Введи время 1 из {times} (формат ЧЧ:ММ, например 08:00):",
        reply_markup=_CANCEL_BTN
    )
    return EDIT_SCHEDULE


async def keep_edit_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    edit_med = context.user_data["edit_med"]
    context.user_data["edit_times"] = edit_med["times_per_day"]
    context.user_data["edit_collected"] = []
    schedules_str = ", ".join(r["reminder_time"] for r in edit_med["schedule_rules"])
    await query.edit_message_text(
        f"Введи время 1 из {edit_med['times_per_day']} (формат ЧЧ:ММ)\n(текущие: {schedules_str}):",
        reply_markup=_CANCEL_BTN
    )
    return EDIT_SCHEDULE


@handle_db_errors
async def edit_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        time_str = _parse_time(update.message.text.strip())
    except Exception:
        await update.message.reply_text("Неверный формат. Введи время как ЧЧ:ММ:")
        return EDIT_SCHEDULE

    context.user_data["edit_collected"].append(time_str)
    collected = context.user_data["edit_collected"]
    total = context.user_data["edit_times"]

    if len(collected) < total:
        await update.message.reply_text(
            f"Время {len(collected)} из {total} принято. Введи время {len(collected)+1}:",
            reply_markup=_CANCEL_BTN
        )
        return EDIT_SCHEDULE

    user_id = context.user_data["edit_user_id"]
    rules = [{"reminder_time": t, "frequency": "daily"} for t in collected]
    update_medication(context.user_data["edit_id"], user_id,
                      context.user_data["edit_name"], context.user_data["edit_dosage"],
                      context.user_data["edit_meal"], total, rules)
    await update.message.reply_text(
        f"✅ Лекарство обновлено!\n\n"
        f"💊 {context.user_data['edit_name']} — {context.user_data['edit_dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['edit_meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(collected)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Edit flow: advanced paths ──────────────────────────────────────────────

async def edit_freq_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        assert 2 <= n <= 90
    except (ValueError, AssertionError):
        await update.message.reply_text("Введи число от 2 до 90:", reply_markup=_CANCEL_BTN)
        return EDIT_FREQ_INTERVAL
    context.user_data["edit_freq_interval_days"] = n
    total = context.user_data.get("edit_times", 1)
    await update.message.reply_text(
        f"Укажи время 1 из {total} приёмов (формат ЧЧ:ММ):", reply_markup=_CANCEL_BTN
    )
    return EDIT_FREQ_TIME


async def toggle_edit_weekday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = int(query.data.split(":")[1])
    selected = context.user_data.setdefault("edit_freq_weekdays", set())
    selected.discard(day) if day in selected else selected.add(day)
    await query.edit_message_reply_markup(reply_markup=_edit_weekdays_keyboard(selected))
    return EDIT_FREQ_WEEKDAYS


async def confirm_edit_weekdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("edit_freq_weekdays", set())
    if not selected:
        await query.answer("Выбери хотя бы один день", show_alert=True)
        return EDIT_FREQ_WEEKDAYS
    await query.answer()
    total = context.user_data.get("edit_times", 1)
    await query.edit_message_text(
        f"Укажи время 1 из {total} приёмов (формат ЧЧ:ММ):", reply_markup=_CANCEL_BTN
    )
    return EDIT_FREQ_TIME


async def edit_freq_monthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        day = int(update.message.text.strip())
        assert 1 <= day <= 31
    except (ValueError, AssertionError):
        await update.message.reply_text("Введи число от 1 до 31:", reply_markup=_CANCEL_BTN)
        return EDIT_FREQ_MONTHDAY
    context.user_data["edit_freq_month_day"] = day
    total = context.user_data.get("edit_times", 1)
    await update.message.reply_text(
        f"Укажи время 1 из {total} приёмов (формат ЧЧ:ММ):", reply_markup=_CANCEL_BTN
    )
    return EDIT_FREQ_TIME


@handle_db_errors
async def edit_freq_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        time_str = _parse_time(update.message.text.strip())
    except Exception:
        await update.message.reply_text("Неверный формат. Введи время как ЧЧ:ММ:")
        return EDIT_FREQ_TIME

    collected = context.user_data.setdefault("edit_freq_collected_times", [])
    collected.append(time_str)
    total = context.user_data.get("edit_times", 1)

    if len(collected) < total:
        await update.message.reply_text(
            f"Время {len(collected)} из {total} принято. "
            f"Введи время {len(collected) + 1} из {total}:",
            reply_markup=_CANCEL_BTN
        )
        return EDIT_FREQ_TIME

    user_id = context.user_data["edit_user_id"]
    freq = context.user_data["edit_freq_type"]
    interval_days = context.user_data.get("edit_freq_interval_days")
    weekdays_set = context.user_data.get("edit_freq_weekdays", set())
    weekdays = ",".join(str(d) for d in sorted(weekdays_set)) or None
    month_day = context.user_data.get("edit_freq_month_day")
    anchor_date = date.today().isoformat() if freq == "interval" else None

    rules = [
        {"reminder_time": t, "frequency": freq, "interval_days": interval_days,
         "weekdays": weekdays, "month_day": month_day, "anchor_date": anchor_date}
        for t in collected
    ]
    update_medication(context.user_data["edit_id"], user_id,
                      context.user_data["edit_name"], context.user_data["edit_dosage"],
                      context.user_data["edit_meal"], total, rules)

    freq_label = _freq_label(freq, interval_days, weekdays, month_day)
    await update.message.reply_text(
        f"✅ Лекарство обновлено!\n\n"
        f"💊 {context.user_data['edit_name']} — {context.user_data['edit_dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['edit_meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(collected)} — {freq_label}"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── ConversationHandler factories ──────────────────────────────────────────

def get_add_handler(cancel_handler):
    return ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            CallbackQueryHandler(handle_add_med_callback, pattern="^add_med$"),
        ],
        states={
            NAME:          [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            DOSAGE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, add_dosage)],
            MEAL:          [CallbackQueryHandler(add_meal, pattern="^(before|after|with|any)$")],
            TIMES:         [
                CallbackQueryHandler(add_times, pattern="^[1-4]$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_times_text),
            ],
            SCHEDULE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_schedule_time)],
            FREQ_TYPE:     [CallbackQueryHandler(choose_freq_type, pattern="^freq:")],
            FREQ_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_interval)],
            FREQ_WEEKDAYS: [
                CallbackQueryHandler(toggle_weekday, pattern="^weekday:\\d+$"),
                CallbackQueryHandler(confirm_weekdays, pattern="^weekdays_confirm$"),
            ],
            FREQ_MONTHDAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_monthday)],
            FREQ_TIME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_time)],
        },
        fallbacks=[
            cancel_handler,
            CallbackQueryHandler(cancel_add, pattern="^cancel_add$"),
        ],
    )


def get_edit_handler(cancel_handler):
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_edit_select, pattern="^edit:\\d+$")],
        states={
            EDIT_NAME:          [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name),
                CallbackQueryHandler(keep_edit_name, pattern="^keep_edit_name$"),
            ],
            EDIT_DOSAGE:        [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_dosage),
                CallbackQueryHandler(keep_edit_dosage, pattern="^keep_edit_dosage$"),
            ],
            EDIT_FREQ_TYPE:     [
                CallbackQueryHandler(keep_edit_schedule, pattern="^keep_edit_schedule$"),
                CallbackQueryHandler(choose_edit_freq_type, pattern="^editfreq:"),
            ],
            EDIT_MEAL:          [
                CallbackQueryHandler(edit_meal, pattern="^editmeal:"),
                CallbackQueryHandler(keep_edit_meal, pattern="^keep_edit_meal$"),
            ],
            EDIT_TIMES:         [
                CallbackQueryHandler(edit_times, pattern="^edittimes:"),
                CallbackQueryHandler(keep_edit_times, pattern="^keep_edit_times$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_times_text),
            ],
            EDIT_SCHEDULE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_schedule)],
            EDIT_FREQ_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_freq_interval)],
            EDIT_FREQ_WEEKDAYS: [
                CallbackQueryHandler(toggle_edit_weekday, pattern="^editweekday:\\d+$"),
                CallbackQueryHandler(confirm_edit_weekdays, pattern="^edit_weekdays_confirm$"),
            ],
            EDIT_FREQ_MONTHDAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_freq_monthday)],
            EDIT_FREQ_TIME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_freq_time)],
        },
        fallbacks=[
            cancel_handler,
            CallbackQueryHandler(cancel_add, pattern="^cancel_add$"),
        ],
    )
