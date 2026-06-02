import logging
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import (get_or_create_user, add_medication, add_schedule_rule,
                      update_medication, count_active_medications, get_user_time_presets,
                      get_caregiver_mode, get_dependents, add_dependent, count_dependents)
from scheduler import clear_pending_for_medication
from constants import (NAME, DOSAGE, MEAL, TIMES, DOSAGE_B, TIMES_B,
                       FREQ_TYPE, FREQ_INTERVAL, FREQ_WEEKDAYS, FREQ_MONTHDAY,
                       FREQ_TYPE_B, FREQ_INTERVAL_B, FREQ_WEEKDAYS_B, FREQ_MONTHDAY_B,
                       SELECT_DEPENDENT, ADD_DEPENDENT_NAME,
                       MEAL_LABELS, MAX_MEDICATIONS_PER_USER, MAX_DEPENDENTS,
                       DEPENDENT_NAME_MAX_LEN, SLOT_ORDER)
from utils import handle_db_errors, escape_html, NAME_MAX_LEN, DOSAGE_MAX_LEN
from handlers.meds_common import (
    _CANCEL_BTN, _ADD_DOSAGE_KB, _ADD_FREQ_INTERVAL_KB, _ADD_FREQ_MONTHDAY_KB,
    _back_cancel_kb, _freq_type_keyboard, _freq_type_b_keyboard,
    _weekdays_keyboard, _weekdays_b_keyboard,
    _timeslots_keyboard, _timeslots_b_keyboard,
    _format_schedule_rule, _monthday_warning, _med_saved_text, _parse_int_range,
    _saved_keyboard, _freq_label, _dosage_a_summary,
)

logger = logging.getLogger(__name__)


# ── Caregiver: «Для кого?» ─────────────────────────────────────────────────

def _dependent_select_keyboard(dependents: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("👤 Для себя", callback_data="select_dep:self")]]
    for d in dependents:
        rows.append([InlineKeyboardButton(f"👧 {d['name']}", callback_data=f"select_dep:{d['id']}")])
    rows.append([InlineKeyboardButton("➕ Новый подопечный", callback_data="select_dep:new")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")])
    return InlineKeyboardMarkup(rows)


def _dependent_select_keyboard_no_add(dependents: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("👤 Для себя", callback_data="select_dep:self")]]
    for d in dependents:
        rows.append([InlineKeyboardButton(f"👧 {d['name']}", callback_data=f"select_dep:{d['id']}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")])
    return InlineKeyboardMarkup(rows)


@handle_db_errors
async def handle_select_dependent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    user_id = context.user_data.get("_add_user_id") or get_or_create_user(user.id, user.username)
    context.user_data["_add_user_id"] = user_id

    if data == "select_dep:new":
        if count_dependents(user.id) >= MAX_DEPENDENTS:
            await query.answer(f"Максимум {MAX_DEPENDENTS} подопечных", show_alert=True)
            return SELECT_DEPENDENT
        await query.edit_message_text(
            f"Как зовут подопечного? (не более {DEPENDENT_NAME_MAX_LEN} символов):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")
            ]])
        )
        return ADD_DEPENDENT_NAME

    if data == "select_dep:self":
        dep_id = None
    else:
        dep_id = int(data.split(":")[1])
    context.user_data["dependent_id"] = dep_id

    if count_active_medications(user_id, dep_id) >= MAX_MEDICATIONS_PER_USER:
        entity = "у тебя" if dep_id is None else "у подопечного"
        await query.edit_message_text(
            f"⚠️ {entity.capitalize()} достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств."
        )
        context.user_data.clear()
        return ConversationHandler.END

    await query.edit_message_text("Как называется лекарство?", reply_markup=_CANCEL_BTN)
    return NAME


@handle_db_errors
async def handle_new_dependent_name_in_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Имя не может быть пустым. Введи ещё раз:")
        return ADD_DEPENDENT_NAME
    if len(name) > DEPENDENT_NAME_MAX_LEN:
        await update.message.reply_text(
            f"Имя не может быть длиннее {DEPENDENT_NAME_MAX_LEN} символов. Попробуй ещё раз:"
        )
        return ADD_DEPENDENT_NAME
    user = update.effective_user
    user_id = context.user_data.get("_add_user_id") or get_or_create_user(user.id, user.username)
    context.user_data["_add_user_id"] = user_id
    dep_id = add_dependent(user.id, name)
    context.user_data["dependent_id"] = dep_id

    if count_active_medications(user_id, dep_id) >= MAX_MEDICATIONS_PER_USER:
        await update.message.reply_text(
            f"⚠️ У подопечного достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств."
        )
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(
        f"✅ Подопечный <b>{escape_html(name)}</b> добавлен.\n\nКак называется лекарство?",
        parse_mode="HTML",
        reply_markup=_CANCEL_BTN
    )
    return NAME


# ── Add flow: entry ────────────────────────────────────────────────────────

async def _begin_add_flow(send, user, context):
    user_id = get_or_create_user(user.id, user.username)
    context.user_data["_add_user_id"] = user_id

    if get_caregiver_mode(user.id):
        dependents = get_dependents(user.id)
        kb = (_dependent_select_keyboard(dependents)
              if len(dependents) < MAX_DEPENDENTS
              else _dependent_select_keyboard_no_add(dependents))
        await send.reply_text("👨‍👩‍👧 Для кого добавляем лекарство?", reply_markup=kb)
        return SELECT_DEPENDENT

    if count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
        await send.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств."
        )
        return ConversationHandler.END
    await send.reply_text("Как называется лекарство?", reply_markup=_CANCEL_BTN)
    return NAME


async def handle_add_med_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await _begin_add_flow(query.message, update.effective_user, context)


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _begin_add_flow(update.message, update.effective_user, context)


async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) > NAME_MAX_LEN:
        await update.message.reply_text(f"Название не может быть длиннее {NAME_MAX_LEN} символов. Попробуй ещё раз:")
        return NAME
    context.user_data["name"] = name
    await update.message.reply_text(
        "Укажи дозировку (например: 500мг, 1 таблетка):",
        reply_markup=_ADD_DOSAGE_KB
    )
    return DOSAGE


async def enter_multi_dosage_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["multi_dosage"] = True
    await query.edit_message_text(
        "Введи <b>дозировку А</b> (например: 25 мкг):",
        parse_mode="HTML",
        reply_markup=_back_cancel_kb("back_add_to_name")
    )
    return DOSAGE


async def add_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dosage = update.message.text.strip()
    if len(dosage) > DOSAGE_MAX_LEN:
        await update.message.reply_text(f"Дозировка не может быть длиннее {DOSAGE_MAX_LEN} символов. Попробуй ещё раз:")
        return DOSAGE
    context.user_data["dosage"] = dosage
    if context.user_data.get("multi_dosage"):
        dosage_a = context.user_data["dosage"]
        await update.message.reply_text(
            f"Введи <b>дозировку Б</b> (например: 50 мкг):\n<i>Дозировка А: {escape_html(dosage_a)}</i>",
            parse_mode="HTML",
            reply_markup=_back_cancel_kb("back_multi_to_dosage_a")
        )
        return DOSAGE_B
    context.user_data.setdefault("selected_slots", set())
    selected = context.user_data["selected_slots"]
    presets = get_user_time_presets(update.effective_user.id)
    await update.message.reply_text(
        "⏰ <b>Когда принимать?</b> — выбери один или несколько:\n\n<i>Время слотов меняется в ⚙️ Настройки → ⏰ Время приёмов.</i>",
        parse_mode="HTML",
        reply_markup=_timeslots_keyboard(selected, presets)
    )
    return TIMES


async def add_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dosage_b = update.message.text.strip()
    if len(dosage_b) > DOSAGE_MAX_LEN:
        await update.message.reply_text(f"Дозировка не может быть длиннее {DOSAGE_MAX_LEN} символов. Попробуй ещё раз:")
        return DOSAGE_B
    context.user_data["dosage_b"] = dosage_b
    dosage_a = context.user_data["dosage"]
    context.user_data.setdefault("selected_slots", set())
    presets = get_user_time_presets(update.effective_user.id)
    await update.message.reply_text(
        f"⏰ <b>Когда принимать дозировку А ({escape_html(dosage_a)})?</b>\nВыбери один или несколько:",
        parse_mode="HTML",
        reply_markup=_timeslots_keyboard(set(), presets, back_cb="back_multi_to_dosage_b")
    )
    return TIMES


# ── Add flow: slot toggle A → meal ─────────────────────────────────────────

async def add_timeslot_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slot = query.data.split(":")[1]
    selected = context.user_data.setdefault("selected_slots", set())
    selected.discard(slot) if slot in selected else selected.add(slot)
    presets = get_user_time_presets(update.effective_user.id)
    if context.user_data.get("edit_id") and context.user_data.get("multi_dosage"):
        back_cb = "back_edit_to_freq_type"
    elif context.user_data.get("multi_dosage"):
        back_cb = "back_multi_to_dosage_b"
    else:
        back_cb = "back_add_to_dosage"
    await query.edit_message_reply_markup(reply_markup=_timeslots_keyboard(selected, presets, back_cb=back_cb))
    return TIMES


async def add_timeslots_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("selected_slots", set())
    if not selected:
        await query.answer("Выбери хотя бы один приём", show_alert=True)
        return TIMES
    await query.answer()
    presets = get_user_time_presets(update.effective_user.id)
    context.user_data["collected_times"] = [presets[s] for s in SLOT_ORDER if s in selected]

    if context.user_data.get("multi_dosage"):
        dosage_b = context.user_data["dosage_b"]
        context.user_data.setdefault("selected_slots_b", set())
        summary_a = _dosage_a_summary(context.user_data)
        await query.edit_message_text(
            f"{summary_a}\n\n⏰ <b>Когда принимать дозировку Б ({escape_html(dosage_b)})?</b>\nВыбери один или несколько:",
            parse_mode="HTML",
            reply_markup=_timeslots_b_keyboard(context.user_data["selected_slots_b"], presets)
        )
        return TIMES_B

    keyboard = [
        [InlineKeyboardButton(label, callback_data=key)]
        for key, label in MEAL_LABELS.items()
    ]
    keyboard.append([
        InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_times"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_add"),
    ])
    await query.edit_message_text(
        "🍽 <b>Как принимать с пищей?</b>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MEAL


# ── Add flow: slot toggle B ────────────────────────────────────────────────

async def add_timeslot_b_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slot = query.data.split(":")[1]
    selected = context.user_data.setdefault("selected_slots_b", set())
    selected.discard(slot) if slot in selected else selected.add(slot)
    presets = get_user_time_presets(update.effective_user.id)
    await query.edit_message_reply_markup(reply_markup=_timeslots_b_keyboard(selected, presets))
    return TIMES_B


async def add_timeslots_b_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("selected_slots_b", set())
    if not selected:
        await query.answer("Выбери хотя бы один приём для дозировки Б", show_alert=True)
        return TIMES_B
    await query.answer()
    presets = get_user_time_presets(update.effective_user.id)
    context.user_data["collected_times_b"] = [presets[s] for s in SLOT_ORDER if s in selected]
    if context.user_data.get("edit_id"):
        dosage_a = context.user_data["dosage"]
        await query.edit_message_text(
            f"📅 <b>Расписание для дозировки А ({escape_html(dosage_a)})</b> — выбери:",
            parse_mode="HTML", reply_markup=_freq_type_keyboard()
        )
        return FREQ_TYPE
    keyboard = [
        [InlineKeyboardButton(label, callback_data=key)]
        for key, label in MEAL_LABELS.items()
    ]
    keyboard.append([
        InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_times"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_add"),
    ])
    await query.edit_message_text(
        "🍽 <b>Как принимать с пищей?</b> (для обеих дозировок)",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MEAL


# ── Add flow: meal ─────────────────────────────────────────────────────────

async def add_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["meal"] = query.data
    if context.user_data.get("multi_dosage"):
        dosage_a = context.user_data["dosage"]
        await query.edit_message_text(
            f"📅 <b>Расписание для дозировки А ({escape_html(dosage_a)})</b> — выбери:",
            parse_mode="HTML", reply_markup=_freq_type_keyboard()
        )
    else:
        await query.edit_message_text(
            "📅 <b>Тип расписания</b> — выбери:",
            parse_mode="HTML", reply_markup=_freq_type_keyboard()
        )
    return FREQ_TYPE


# ── Add flow: freq type A ──────────────────────────────────────────────────

async def _go_to_freq_type_b(edit_target, context, from_message: bool = False):
    summary = _dosage_a_summary(context.user_data)
    dosage_b = context.user_data.get("dosage_b", "")
    text = f"{summary}\n\n📅 <b>Расписание для дозировки Б ({escape_html(dosage_b)})</b> — выбери:"
    if from_message:
        await edit_target.reply_text(text, parse_mode="HTML", reply_markup=_freq_type_b_keyboard())
    else:
        await edit_target.edit_message_text(text, parse_mode="HTML", reply_markup=_freq_type_b_keyboard())
    return FREQ_TYPE_B


@handle_db_errors
async def choose_freq_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    freq = query.data.split(":")[1]
    multi = context.user_data.get("multi_dosage")

    if freq == "daily":
        if multi:
            context.user_data["freq_a"] = {"type": "daily"}
            return await _go_to_freq_type_b(query, context)
        user = update.effective_user
        user_id = context.user_data.get("_add_user_id") or get_or_create_user(user.id, user.username)
        dep_id = context.user_data.get("dependent_id")
        if count_active_medications(user_id, dep_id) >= MAX_MEDICATIONS_PER_USER:
            await query.message.reply_text(
                f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств.")
            context.user_data.clear()
            return ConversationHandler.END
        collected = context.user_data["collected_times"]
        total = len(collected)
        med_id = add_medication(user_id, context.user_data["name"],
                                context.user_data["dosage"], context.user_data["meal"], total,
                                dependent_id=dep_id)
        for t in collected:
            add_schedule_rule(med_id, t, "daily")
        await query.edit_message_text(
            _med_saved_text("добавлено", context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"],
                            total, collected),
            reply_markup=_saved_keyboard(med_id)
        )
        context.user_data.clear()
        return ConversationHandler.END

    if freq == "interval":
        await query.edit_message_text("🔄 <b>Через сколько дней?</b> (например: 2):",
                                      parse_mode="HTML", reply_markup=_ADD_FREQ_INTERVAL_KB)
        return FREQ_INTERVAL

    if freq == "weekdays":
        context.user_data["freq_weekdays"] = set()
        await query.edit_message_text(
            "📆 <b>По дням недели</b> — выбери и нажми Готово:",
            parse_mode="HTML", reply_markup=_weekdays_keyboard(set())
        )
        return FREQ_WEEKDAYS

    if freq == "monthly":
        await query.edit_message_text("🗓 <b>Какого числа каждого месяца?</b> (1–31):",
                                      parse_mode="HTML", reply_markup=_ADD_FREQ_MONTHDAY_KB)
        return FREQ_MONTHDAY

    return FREQ_TYPE


@handle_db_errors
async def add_freq_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = _parse_int_range(update.message.text, 2, 90)
    if n is None:
        await update.message.reply_text("Введи число от 2 до 90:", reply_markup=_ADD_FREQ_INTERVAL_KB)
        return FREQ_INTERVAL
    if context.user_data.get("multi_dosage"):
        context.user_data["freq_a"] = {
            "type": "interval",
            "interval_days": n,
            "anchor_date": date.today().isoformat(),
        }
        return await _go_to_freq_type_b(update.message, context, from_message=True)
    user = update.effective_user
    user_id = context.user_data.get("_add_user_id") or get_or_create_user(user.id, user.username)
    dep_id = context.user_data.get("dependent_id")
    if count_active_medications(user_id, dep_id) >= MAX_MEDICATIONS_PER_USER:
        await update.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств.")
        context.user_data.clear()
        return ConversationHandler.END
    collected = context.user_data["collected_times"]
    total = len(collected)
    anchor_date = date.today().isoformat()
    med_id = add_medication(user_id, context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"], total,
                            dependent_id=dep_id)
    for t in collected:
        add_schedule_rule(med_id, t, "interval", interval_days=n, anchor_date=anchor_date)
    await update.message.reply_text(
        _med_saved_text("добавлено", context.user_data["name"], context.user_data["dosage"],
                        context.user_data["meal"], total, collected,
                        freq_suffix=f" — {_freq_label('interval', n, None, None)}"),
        reply_markup=_saved_keyboard(med_id)
    )
    context.user_data.clear()
    return ConversationHandler.END


async def toggle_weekday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = int(query.data.split(":")[1])
    selected = context.user_data.setdefault("freq_weekdays", set())
    selected.discard(day) if day in selected else selected.add(day)
    await query.edit_message_reply_markup(reply_markup=_weekdays_keyboard(selected))
    return FREQ_WEEKDAYS


@handle_db_errors
async def confirm_weekdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("freq_weekdays", set())
    if not selected:
        await query.answer("Выбери хотя бы один день", show_alert=True)
        return FREQ_WEEKDAYS
    await query.answer()
    weekdays = ",".join(str(d) for d in sorted(selected))
    if context.user_data.get("multi_dosage"):
        context.user_data["freq_a"] = {"type": "weekdays", "weekdays": weekdays}
        return await _go_to_freq_type_b(query, context)
    user = update.effective_user
    user_id = context.user_data.get("_add_user_id") or get_or_create_user(user.id, user.username)
    dep_id = context.user_data.get("dependent_id")
    if count_active_medications(user_id, dep_id) >= MAX_MEDICATIONS_PER_USER:
        await query.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств.")
        context.user_data.clear()
        return ConversationHandler.END
    collected = context.user_data["collected_times"]
    total = len(collected)
    med_id = add_medication(user_id, context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"], total,
                            dependent_id=dep_id)
    for t in collected:
        add_schedule_rule(med_id, t, "weekdays", weekdays=weekdays)
    await query.edit_message_text(
        _med_saved_text("добавлено", context.user_data["name"], context.user_data["dosage"],
                        context.user_data["meal"], total, collected,
                        freq_suffix=f" — {_freq_label('weekdays', None, weekdays, None)}"),
        reply_markup=_saved_keyboard(med_id)
    )
    context.user_data.clear()
    return ConversationHandler.END


@handle_db_errors
async def add_freq_monthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = _parse_int_range(update.message.text, 1, 31)
    if day is None:
        await update.message.reply_text("Введи число от 1 до 31:", reply_markup=_ADD_FREQ_MONTHDAY_KB)
        return FREQ_MONTHDAY
    if context.user_data.get("multi_dosage"):
        context.user_data["freq_a"] = {"type": "monthly", "month_day": day}
        return await _go_to_freq_type_b(update.message, context, from_message=True)
    user = update.effective_user
    user_id = context.user_data.get("_add_user_id") or get_or_create_user(user.id, user.username)
    dep_id = context.user_data.get("dependent_id")
    if count_active_medications(user_id, dep_id) >= MAX_MEDICATIONS_PER_USER:
        await update.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств.")
        context.user_data.clear()
        return ConversationHandler.END
    collected = context.user_data["collected_times"]
    total = len(collected)
    med_id = add_medication(user_id, context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"], total,
                            dependent_id=dep_id)
    for t in collected:
        add_schedule_rule(med_id, t, "monthly", month_day=day)
    warning = _monthday_warning(day)
    await update.message.reply_text(
        _med_saved_text("добавлено", context.user_data["name"], context.user_data["dosage"],
                        context.user_data["meal"], total, collected,
                        freq_suffix=f" — {_freq_label('monthly', None, None, day)}", warning=warning),
        reply_markup=_saved_keyboard(med_id)
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Add flow: freq type B ──────────────────────────────────────────────────

@handle_db_errors
async def choose_freq_type_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    freq = query.data.split(":")[1]
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)

    if freq == "daily":
        return await _save_multi_medication(
            query, context, user_id,
            freq_b={"type": "daily"}
        )
    if freq == "interval":
        summary = _dosage_a_summary(context.user_data)
        dosage_b = context.user_data.get("dosage_b", "")
        await query.edit_message_text(
            f"{summary}\n\n🔄 <b>Дозировка Б ({escape_html(dosage_b)}) — через сколько дней?</b> (например: 2):",
            parse_mode="HTML",
            reply_markup=_back_cancel_kb("back_multi_to_freq_type_b")
        )
        return FREQ_INTERVAL_B
    if freq == "weekdays":
        context.user_data["freq_b_weekdays"] = set()
        summary = _dosage_a_summary(context.user_data)
        dosage_b = context.user_data.get("dosage_b", "")
        await query.edit_message_text(
            f"{summary}\n\n📆 <b>Дозировка Б ({escape_html(dosage_b)}) — дни недели:</b>",
            parse_mode="HTML",
            reply_markup=_weekdays_b_keyboard(set())
        )
        return FREQ_WEEKDAYS_B
    if freq == "monthly":
        summary = _dosage_a_summary(context.user_data)
        dosage_b = context.user_data.get("dosage_b", "")
        await query.edit_message_text(
            f"{summary}\n\n🗓 <b>Дозировка Б ({escape_html(dosage_b)}) — какого числа каждого месяца?</b> (1–31):",
            parse_mode="HTML",
            reply_markup=_back_cancel_kb("back_multi_to_freq_type_b")
        )
        return FREQ_MONTHDAY_B
    return FREQ_TYPE_B


@handle_db_errors
async def add_freq_interval_b_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = _parse_int_range(update.message.text, 2, 90)
    if n is None:
        await update.message.reply_text(
            "Введи число от 2 до 90:",
            reply_markup=_back_cancel_kb("back_multi_to_freq_type_b")
        )
        return FREQ_INTERVAL_B
    context.user_data["freq_b_interval_days"] = n
    freq_a = context.user_data.get("freq_a", {})
    same_interval = freq_a.get("type") == "interval" and freq_a.get("interval_days") == n
    hint = (
        "\n\n_Дозировка А — с сегодня. Чтобы они чередовались каждый день — выбери «Завтра»._"
        if same_interval else ""
    )
    await update.message.reply_text(
        f"🔄 Каждые {n} дн. — с какого дня начинать дозировку Б?{hint}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Сегодня (те же дни что А)", callback_data="freqb_anchor:0"),
            InlineKeyboardButton("📅 Завтра (чередование)", callback_data="freqb_anchor:1"),
        ]])
    )
    return FREQ_INTERVAL_B


@handle_db_errors
async def add_freq_interval_b_anchor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    offset = int(query.data.split(":")[1])
    anchor = (date.today() + timedelta(days=offset)).isoformat()
    n = context.user_data["freq_b_interval_days"]
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    return await _save_multi_medication(
        query, context, user_id,
        freq_b={"type": "interval", "interval_days": n, "anchor_date": anchor}
    )


async def toggle_weekday_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = int(query.data.split(":")[1])
    selected = context.user_data.setdefault("freq_b_weekdays", set())
    selected.discard(day) if day in selected else selected.add(day)
    await query.edit_message_reply_markup(reply_markup=_weekdays_b_keyboard(selected))
    return FREQ_WEEKDAYS_B


@handle_db_errors
async def confirm_weekdays_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("freq_b_weekdays", set())
    if not selected:
        await query.answer("Выбери хотя бы один день", show_alert=True)
        return FREQ_WEEKDAYS_B
    await query.answer()
    weekdays = ",".join(str(d) for d in sorted(selected))
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    return await _save_multi_medication(
        query, context, user_id,
        freq_b={"type": "weekdays", "weekdays": weekdays}
    )


@handle_db_errors
async def add_freq_monthday_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = _parse_int_range(update.message.text, 1, 31)
    if day is None:
        await update.message.reply_text(
            "Введи число от 1 до 31:",
            reply_markup=_back_cancel_kb("back_multi_to_freq_type_b")
        )
        return FREQ_MONTHDAY_B
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    warning = _monthday_warning(day)
    return await _save_multi_medication(
        update.message, context, user_id,
        freq_b={"type": "monthly", "month_day": day},
        from_message=True,
        warning=warning
    )


# ── Save multi-dosage medication (shared with edit flow) ───────────────────

async def _save_multi_medication(edit_target, context, user_id: int,
                                 freq_b: dict, from_message: bool = False, warning: str = ""):
    ud = context.user_data
    is_edit_mode = "edit_id" in ud
    dep_id = ud.get("dependent_id")
    if not is_edit_mode and count_active_medications(user_id, dep_id) >= MAX_MEDICATIONS_PER_USER:
        text = f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств."
        if from_message:
            await edit_target.reply_text(text)
        else:
            await edit_target.message.reply_text(text)
        context.user_data.clear()
        return ConversationHandler.END

    name = ud["name"]
    dosage_a = ud["dosage"]
    dosage_b = ud["dosage_b"]
    meal = ud["meal"]
    times_a = ud["collected_times"]
    times_b = ud["collected_times_b"]
    freq_a = ud["freq_a"]
    total = len(times_a) + len(times_b)

    anchor_a = freq_a.get("anchor_date", date.today().isoformat())
    rules_for_db = []
    for t in times_a:
        rules_for_db.append({
            "reminder_time": t, "frequency": freq_a["type"],
            "interval_days": freq_a.get("interval_days"), "weekdays": freq_a.get("weekdays"),
            "month_day": freq_a.get("month_day"), "anchor_date": anchor_a, "dosage": None,
        })
    for t in times_b:
        rules_for_db.append({
            "reminder_time": t, "frequency": freq_b["type"],
            "interval_days": freq_b.get("interval_days"), "weekdays": freq_b.get("weekdays"),
            "month_day": freq_b.get("month_day"), "anchor_date": freq_b.get("anchor_date"),
            "dosage": dosage_b,
        })

    if is_edit_mode:
        clear_pending_for_medication(ud["edit_id"])
        update_medication(ud["edit_id"], user_id, name, dosage_a, meal, total, rules_for_db)
        saved_id = ud["edit_id"]
    else:
        med_id = add_medication(user_id, name, dosage_a, meal, total, dependent_id=dep_id)
        for r in rules_for_db:
            add_schedule_rule(
                med_id, r["reminder_time"], r["frequency"],
                interval_days=r.get("interval_days"), weekdays=r.get("weekdays"),
                month_day=r.get("month_day"), anchor_date=r.get("anchor_date"),
                dosage=r.get("dosage")
            )
        saved_id = med_id

    freq_a_label = _freq_label(freq_a["type"], freq_a.get("interval_days"),
                                freq_a.get("weekdays"), freq_a.get("month_day"))
    freq_b_label = _freq_label(freq_b["type"], freq_b.get("interval_days"),
                                freq_b.get("weekdays"), freq_b.get("month_day"))

    text = (
        f"✅ Лекарство {'обновлено' if is_edit_mode else 'добавлено'}!\n\n"
        f"💊 <b>{escape_html(name)}</b>\n"
        f"🍽 {MEAL_LABELS[meal]}\n\n"
        f"Дозировка А: <b>{escape_html(dosage_a)}</b>\n"
        f"⏰ {', '.join(times_a)} — {freq_a_label}\n\n"
        f"Дозировка Б: <b>{escape_html(dosage_b)}</b>\n"
        f"⏰ {', '.join(times_b)} — {freq_b_label}"
        f"{warning}"
    )

    if from_message:
        await edit_target.reply_text(text, parse_mode="HTML", reply_markup=_saved_keyboard(saved_id))
    else:
        await edit_target.edit_message_text(text, parse_mode="HTML", reply_markup=_saved_keyboard(saved_id))
    context.user_data.clear()
    return ConversationHandler.END


# ── Add flow: back handlers ────────────────────────────────────────────────

async def back_add_to_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("multi_dosage", None)
    await query.edit_message_text("Как называется лекарство?", reply_markup=_CANCEL_BTN)
    return NAME


async def back_add_to_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Укажи дозировку (например: 500мг, 1 таблетка):",
        reply_markup=_ADD_DOSAGE_KB
    )
    return DOSAGE


async def back_multi_to_dosage_a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("dosage", None)
    await query.edit_message_text(
        "Введи <b>дозировку А</b> (например: 25 мкг):",
        parse_mode="HTML",
        reply_markup=_back_cancel_kb("back_add_to_name")
    )
    return DOSAGE


async def back_multi_to_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dosage_a = context.user_data.get("dosage", "")
    context.user_data.pop("dosage_b", None)
    await query.edit_message_text(
        f"Введи <b>дозировку Б</b> (например: 50 мкг):\n<i>Дозировка А: {escape_html(dosage_a)}</i>",
        parse_mode="HTML",
        reply_markup=_back_cancel_kb("back_multi_to_dosage_a")
    )
    return DOSAGE_B


async def back_add_to_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    presets = get_user_time_presets(update.effective_user.id)
    if context.user_data.get("multi_dosage"):
        selected_b = context.user_data.get("selected_slots_b", set())
        summary_a = _dosage_a_summary(context.user_data)
        dosage_b = context.user_data.get("dosage_b", "")
        await query.edit_message_text(
            f"{summary_a}\n\n⏰ <b>Когда принимать дозировку Б ({escape_html(dosage_b)})?</b>\nВыбери один или несколько:",
            parse_mode="HTML",
            reply_markup=_timeslots_b_keyboard(selected_b, presets)
        )
        return TIMES_B
    selected = context.user_data.get("selected_slots", set())
    await query.edit_message_text(
        "⏰ <b>Когда принимать?</b> — выбери один или несколько:\n\n<i>Время слотов меняется в ⚙️ Настройки → ⏰ Время приёмов.</i>",
        parse_mode="HTML",
        reply_markup=_timeslots_keyboard(selected, presets)
    )
    return TIMES


async def back_multi_to_times_a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = context.user_data.get("selected_slots", set())
    presets = get_user_time_presets(update.effective_user.id)
    dosage_a = context.user_data.get("dosage", "")
    await query.edit_message_text(
        f"⏰ <b>Когда принимать дозировку А ({escape_html(dosage_a)})?</b>\nВыбери один или несколько:",
        parse_mode="HTML",
        reply_markup=_timeslots_keyboard(selected, presets, back_cb="back_multi_to_dosage_b")
    )
    return TIMES


async def back_add_to_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if context.user_data.get("edit_id"):
        presets = get_user_time_presets(update.effective_user.id)
        if context.user_data.get("freq_a"):
            dosage_a = context.user_data.get("dosage", "")
            await query.edit_message_text(
                f"📅 <b>Расписание для дозировки А ({escape_html(dosage_a)})</b> — выбери:",
                parse_mode="HTML", reply_markup=_freq_type_keyboard()
            )
            return FREQ_TYPE
        else:
            selected_b = context.user_data.get("selected_slots_b", set())
            dosage_b = context.user_data.get("dosage_b", "")
            summary_a = _dosage_a_summary(context.user_data)
            await query.edit_message_text(
                f"{summary_a}\n\n⏰ <b>Когда принимать дозировку Б ({escape_html(dosage_b)})?</b>\nВыбери один или несколько:",
                parse_mode="HTML",
                reply_markup=_timeslots_b_keyboard(selected_b, presets)
            )
            return TIMES_B
    keyboard = [
        [InlineKeyboardButton(label, callback_data=key)]
        for key, label in MEAL_LABELS.items()
    ]
    keyboard.append([
        InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_times"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_add"),
    ])
    await query.edit_message_text(
        "🍽 <b>Как принимать с пищей?</b>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MEAL


async def back_add_to_freq_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if context.user_data.get("multi_dosage"):
        dosage_a = context.user_data.get("dosage", "")
        await query.edit_message_text(
            f"📅 <b>Расписание для дозировки А ({escape_html(dosage_a)})</b> — выбери:",
            parse_mode="HTML", reply_markup=_freq_type_keyboard()
        )
    else:
        await query.edit_message_text(
            "📅 <b>Тип расписания</b> — выбери:",
            parse_mode="HTML", reply_markup=_freq_type_keyboard()
        )
    return FREQ_TYPE


async def back_multi_to_freq_type_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await _go_to_freq_type_b(query, context)
