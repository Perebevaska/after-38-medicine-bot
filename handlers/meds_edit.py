import logging
from datetime import date, datetime
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from database import (get_or_create_user, deactivate_medication, get_medication_by_id,
                      get_schedules_by_medication, update_medication, get_user_medications,
                      get_user_time_presets, get_rules_grouped_for_user, set_medication_paused)
from scheduler import clear_pending_for_medication
from constants import (EDIT_NAME, EDIT_DOSAGE, EDIT_DOSAGE_B, EDIT_FREQ_TYPE, EDIT_TIMES,
                       EDIT_MEAL, EDIT_FREQ_INTERVAL, EDIT_FREQ_WEEKDAYS, EDIT_FREQ_MONTHDAY,
                       TIMES, FREQ_TYPE, MEAL_LABELS, SLOT_ORDER)
from utils import handle_db_errors, get_tz_for_user, escape_html, NAME_MAX_LEN, DOSAGE_MAX_LEN
from handlers.meds_common import (
    _EDIT_NAME_KB, _EDIT_DOSAGE_KB, _EDIT_DOSAGE_B_KB,
    _EDIT_FREQ_INTERVAL_KB, _EDIT_FREQ_MONTHDAY_KB,
    _edit_freq_type_keyboard, _edit_freq_type_keyboard_multi,
    _edit_meal_keyboard, _edit_meal_keyboard_multi,
    _edit_timeslots_keyboard, _edit_weekdays_keyboard,
    _timeslots_keyboard,
    _format_schedule_rule, _current_schedule_summary,
    _med_saved_text, _parse_int_range, _freq_label,
    _med_card_text, _med_card_keyboard,
)
from handlers.meds_add import _save_multi_medication

logger = logging.getLogger(__name__)


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
async def handle_pause_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, mid_str = query.data.split(":")
    medication_id = int(mid_str)
    paused = (action == "med_pause")
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    set_medication_paused(medication_id, user_id, paused)
    if paused:
        clear_pending_for_medication(medication_id)

    med = next((m for m in get_user_medications(user_id) if m["id"] == medication_id), None)
    if med is None:
        await query.edit_message_text("Лекарство не найдено.")
        return
    user_tz = get_tz_for_user(user.id)
    today_local = datetime.now(user_tz).date()
    rules = get_rules_grouped_for_user(user_id).get(medication_id, [])
    await query.edit_message_text(
        _med_card_text(med, rules, today_local),
        parse_mode="HTML",
        reply_markup=_med_card_keyboard(medication_id, bool(med["paused"]), with_menu=True),
    )


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
    is_multi_dosage = any(r.get("dosage") for r in schedule_rules)
    context.user_data["edit_id"] = medication_id
    context.user_data["edit_user_id"] = user_id
    context.user_data["edit_is_multi_dosage"] = is_multi_dosage
    context.user_data["edit_med"] = {
        "name": med["name"],
        "dosage": med["dosage"],
        "meal_relation": med["meal_relation"],
        "times_per_day": med["times_per_day"],
        "schedule_rules": schedule_rules,
    }
    if is_multi_dosage:
        b_dosages = list(dict.fromkeys(r["dosage"] for r in schedule_rules if r.get("dosage")))
        dosage_display = med["dosage"] + " / " + " / ".join(b_dosages)
        rule_lines = [f"⏰ {_format_schedule_rule(r)} — {r.get('dosage') or med['dosage']}" for r in schedule_rules]
        schedule_block = "\n".join(rule_lines) or "не указано"
    else:
        dosage_display = med["dosage"]
        has_adv = any(r["frequency"] != "daily" for r in schedule_rules)
        if not has_adv:
            times_str = ", ".join(r["reminder_time"] for r in schedule_rules) or "не указано"
            schedule_block = f"⏰ {times_str}"
        else:
            schedule_block = "⏰ " + " | ".join(_format_schedule_rule(r) for r in schedule_rules)
    await query.edit_message_text(
        f"✏️ <b>Редактируем: {escape_html(med['name'])}</b>\n"
        f"💊 {dosage_display}  🍽 {MEAL_LABELS[med['meal_relation']]}\n"
        f"{schedule_block}\n"
        f"──────────────────\n"
        f"📝 <b>Название</b> — введи новое:",
        parse_mode="HTML",
        reply_markup=_EDIT_NAME_KB
    )
    return EDIT_NAME


async def keep_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    med = context.user_data["edit_med"]
    context.user_data["edit_name"] = med["name"]
    label = "Дозировка А" if context.user_data.get("edit_is_multi_dosage") else "Дозировка"
    await query.edit_message_text(
        f"📏 <b>{label}</b> — введи новую\n(текущая: {escape_html(med['dosage'])}):",
        parse_mode="HTML",
        reply_markup=_EDIT_DOSAGE_KB
    )
    return EDIT_DOSAGE


async def edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) > NAME_MAX_LEN:
        await update.message.reply_text(f"Название не может быть длиннее {NAME_MAX_LEN} символов. Попробуй ещё раз:")
        return EDIT_NAME
    context.user_data["edit_name"] = name
    med = context.user_data["edit_med"]
    label = "Дозировка А" if context.user_data.get("edit_is_multi_dosage") else "Дозировка"
    await update.message.reply_text(
        f"📏 <b>{label}</b> — введи новую\n(текущая: {escape_html(med['dosage'])}):",
        parse_mode="HTML",
        reply_markup=_EDIT_DOSAGE_KB
    )
    return EDIT_DOSAGE


async def keep_edit_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_dosage"] = context.user_data["edit_med"]["dosage"]
    if context.user_data.get("edit_is_multi_dosage"):
        return await _show_edit_dosage_b_step(context, query)
    return await _show_edit_freq_type_step(context, query)


async def edit_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dosage = update.message.text.strip()
    if len(dosage) > DOSAGE_MAX_LEN:
        await update.message.reply_text(f"Дозировка не может быть длиннее {DOSAGE_MAX_LEN} символов. Попробуй ещё раз:")
        return EDIT_DOSAGE
    context.user_data["edit_dosage"] = dosage
    if context.user_data.get("edit_is_multi_dosage"):
        return await _show_edit_dosage_b_step(context, update.message, from_message=True)
    return await _show_edit_freq_type_step(context, update.message, from_message=True)


async def _show_edit_dosage_b_step(context, target, from_message: bool = False):
    rules = context.user_data["edit_med"]["schedule_rules"]
    current_b = next((r["dosage"] for r in rules if r.get("dosage")), "")
    text = f"📏 <b>Дозировка Б</b> — введи новую\n(текущая: {escape_html(current_b)}):"
    if from_message:
        await target.reply_text(text, parse_mode="HTML", reply_markup=_EDIT_DOSAGE_B_KB)
    else:
        await target.edit_message_text(text, parse_mode="HTML", reply_markup=_EDIT_DOSAGE_B_KB)
    return EDIT_DOSAGE_B


async def keep_edit_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rules = context.user_data["edit_med"]["schedule_rules"]
    context.user_data["edit_dosage_b"] = next((r["dosage"] for r in rules if r.get("dosage")), "")
    return await _show_edit_meal_multi_step(context, query)


async def edit_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dosage_b = update.message.text.strip()
    if len(dosage_b) > DOSAGE_MAX_LEN:
        await update.message.reply_text(f"Дозировка не может быть длиннее {DOSAGE_MAX_LEN} символов. Попробуй ещё раз:")
        return EDIT_DOSAGE_B
    context.user_data["edit_dosage_b"] = dosage_b
    return await _show_edit_meal_multi_step(context, update.message, from_message=True)


async def _show_edit_meal_multi_step(context, target, from_message: bool = False):
    edit_med = context.user_data["edit_med"]
    current_label = MEAL_LABELS.get(edit_med["meal_relation"], edit_med["meal_relation"])
    kb = _edit_meal_keyboard_multi(current_label)
    if from_message:
        await target.reply_text("🍽 <b>Приём с пищей</b> — выбери:", parse_mode="HTML", reply_markup=kb)
    else:
        await target.edit_message_text("🍽 <b>Приём с пищей</b> — выбери:", parse_mode="HTML", reply_markup=kb)
    return EDIT_MEAL


def _get_edit_rules_with_dosage(context) -> list:
    rules = context.user_data["edit_med"]["schedule_rules"]
    new_dosage_b = context.user_data.get("edit_dosage_b")
    if not new_dosage_b:
        return rules
    result = []
    for r in rules:
        r = dict(r)
        if r.get("dosage"):
            r["dosage"] = new_dosage_b
        result.append(r)
    return result


async def _show_edit_freq_type_step(context, target, from_message: bool = False):
    edit_med = context.user_data["edit_med"]
    rules = edit_med["schedule_rules"]
    is_multi = context.user_data.get("edit_is_multi_dosage")
    if is_multi:
        rule_lines = [
            f"{_format_schedule_rule(r)} — {escape_html(r.get('dosage') or edit_med['dosage'])}"
            for r in rules
        ]
        text = "📅 <b>Расписание</b> (разная дозировка):\n" + "\n".join(rule_lines)
        kb = _edit_freq_type_keyboard_multi()
    else:
        text = f"📅 <b>Расписание</b> — выбери тип:\nТекущее: {_current_schedule_summary(rules)}"
        kb = _edit_freq_type_keyboard()
    if from_message:
        await target.reply_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    return EDIT_FREQ_TYPE


# ── Edit flow: freq type ───────────────────────────────────────────────────

@handle_db_errors
async def keep_edit_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    edit_med = context.user_data["edit_med"]
    user_id = context.user_data["edit_user_id"]
    rules = _get_edit_rules_with_dosage(context)
    meal = context.user_data.get("edit_meal") or edit_med["meal_relation"]
    update_medication(
        context.user_data["edit_id"], user_id,
        context.user_data["edit_name"], context.user_data["edit_dosage"],
        meal, edit_med["times_per_day"],
        rules
    )
    dosage_a = context.user_data["edit_dosage"]
    if context.user_data.get("edit_is_multi_dosage"):
        rule_lines = [f"⏰ {_format_schedule_rule(r)} — {r.get('dosage') or dosage_a}" for r in rules]
        body = "\n".join(rule_lines)
        b_dosages = list(dict.fromkeys(r["dosage"] for r in rules if r.get("dosage")))
        dosage_display = dosage_a + " / " + " / ".join(b_dosages)
        await query.edit_message_text(
            f"✅ Лекарство обновлено!\n\n"
            f"💊 {context.user_data['edit_name']} — {dosage_display}\n"
            f"🍽 {MEAL_LABELS[meal]}\n"
            f"{body}"
        )
    else:
        has_adv = any(r["frequency"] != "daily" for r in rules)
        if not has_adv:
            schedule_str = ", ".join(r["reminder_time"] for r in rules)
        else:
            schedule_str = " | ".join(_format_schedule_rule(r) for r in rules)
        await query.edit_message_text(
            f"✅ Лекарство обновлено!\n\n"
            f"💊 {context.user_data['edit_name']} — {dosage_a}\n"
            f"🍽 {MEAL_LABELS[meal]}\n"
            f"🔢 {edit_med['times_per_day']} раз в день\n"
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
    presets = get_user_time_presets(update.effective_user.id)
    current_times = {r["reminder_time"] for r in edit_med["schedule_rules"]}
    preselected = {s for s in SLOT_ORDER if presets[s] in current_times}
    context.user_data["edit_selected_slots"] = preselected
    await query.edit_message_text(
        "⏰ <b>Когда принимать?</b> — выбери один или несколько:\n\n<i>Время слотов меняется в ⚙️ Настройки → ⏰ Время приёмов.</i>",
        parse_mode="HTML",
        reply_markup=_edit_timeslots_keyboard(preselected, presets)
    )
    return EDIT_TIMES


# ── Edit flow: meal → route by freq type ──────────────────────────────────

@handle_db_errors
async def keep_edit_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_meal"] = context.user_data["edit_med"]["meal_relation"]
    return await _route_after_edit_meal(query, context)


@handle_db_errors
async def edit_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_meal"] = query.data.split(":")[1]
    return await _route_after_edit_meal(query, context)


async def _route_after_edit_meal(query, context):
    if context.user_data.get("edit_is_multi_dosage"):
        return await _show_edit_freq_type_step(context, query)

    freq = context.user_data.get("edit_freq_type", "daily")

    if freq == "daily":
        collected = context.user_data["edit_collected"]
        total = len(collected)
        user_id = context.user_data["edit_user_id"]
        rules = [{"reminder_time": t, "frequency": "daily"} for t in collected]
        update_medication(context.user_data["edit_id"], user_id,
                          context.user_data["edit_name"], context.user_data["edit_dosage"],
                          context.user_data["edit_meal"], total, rules)
        await query.edit_message_text(
            _med_saved_text("обновлено", context.user_data["edit_name"],
                            context.user_data["edit_dosage"], context.user_data["edit_meal"],
                            total, collected)
        )
        context.user_data.clear()
        return ConversationHandler.END

    if freq == "interval":
        await query.edit_message_text("🔄 <b>Через сколько дней?</b> (например: 2):",
                                      parse_mode="HTML", reply_markup=_EDIT_FREQ_INTERVAL_KB)
        return EDIT_FREQ_INTERVAL

    if freq == "weekdays":
        context.user_data["edit_freq_weekdays"] = set()
        await query.edit_message_text(
            "📆 <b>Дни недели</b> — выбери и нажми Готово:",
            parse_mode="HTML",
            reply_markup=_edit_weekdays_keyboard(set())
        )
        return EDIT_FREQ_WEEKDAYS

    if freq == "monthly":
        await query.edit_message_text("🗓 <b>Какого числа каждого месяца?</b> (1–31):",
                                      parse_mode="HTML", reply_markup=_EDIT_FREQ_MONTHDAY_KB)
        return EDIT_FREQ_MONTHDAY

    return ConversationHandler.END


# ── Edit flow: slot toggle → meal ─────────────────────────────────────────

async def edit_timeslot_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    slot = query.data.split(":")[1]
    selected = context.user_data.setdefault("edit_selected_slots", set())
    selected.discard(slot) if slot in selected else selected.add(slot)
    presets = get_user_time_presets(update.effective_user.id)
    await query.edit_message_reply_markup(reply_markup=_edit_timeslots_keyboard(selected, presets))
    return EDIT_TIMES


async def edit_timeslots_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("edit_selected_slots", set())
    if not selected:
        await query.answer("Выбери хотя бы один приём", show_alert=True)
        return EDIT_TIMES
    await query.answer()
    presets = get_user_time_presets(update.effective_user.id)
    context.user_data["edit_collected"] = [presets[s] for s in SLOT_ORDER if s in selected]
    edit_med = context.user_data["edit_med"]
    current_label = MEAL_LABELS.get(edit_med["meal_relation"], edit_med["meal_relation"])
    await query.edit_message_text(
        "🍽 <b>Приём с пищей</b> — выбери:",
        parse_mode="HTML",
        reply_markup=_edit_meal_keyboard(current_label)
    )
    return EDIT_MEAL


# ── Edit flow: advanced paths ──────────────────────────────────────────────

@handle_db_errors
async def edit_freq_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = _parse_int_range(update.message.text, 2, 90)
    if n is None:
        await update.message.reply_text("Введи число от 2 до 90:", reply_markup=_EDIT_FREQ_INTERVAL_KB)
        return EDIT_FREQ_INTERVAL
    user_id = context.user_data["edit_user_id"]
    collected = context.user_data["edit_collected"]
    total = len(collected)
    anchor_date = date.today().isoformat()
    rules = [{"reminder_time": t, "frequency": "interval", "interval_days": n, "anchor_date": anchor_date}
             for t in collected]
    update_medication(context.user_data["edit_id"], user_id,
                      context.user_data["edit_name"], context.user_data["edit_dosage"],
                      context.user_data["edit_meal"], total, rules)
    await update.message.reply_text(
        _med_saved_text("обновлено", context.user_data["edit_name"], context.user_data["edit_dosage"],
                        context.user_data["edit_meal"], total, collected,
                        freq_suffix=f" — {_freq_label('interval', n, None, None)}")
    )
    context.user_data.clear()
    return ConversationHandler.END


async def toggle_edit_weekday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = int(query.data.split(":")[1])
    selected = context.user_data.setdefault("edit_freq_weekdays", set())
    selected.discard(day) if day in selected else selected.add(day)
    await query.edit_message_reply_markup(reply_markup=_edit_weekdays_keyboard(selected))
    return EDIT_FREQ_WEEKDAYS


@handle_db_errors
async def confirm_edit_weekdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("edit_freq_weekdays", set())
    if not selected:
        await query.answer("Выбери хотя бы один день", show_alert=True)
        return EDIT_FREQ_WEEKDAYS
    await query.answer()
    user_id = context.user_data["edit_user_id"]
    collected = context.user_data["edit_collected"]
    total = len(collected)
    weekdays = ",".join(str(d) for d in sorted(selected))
    rules = [{"reminder_time": t, "frequency": "weekdays", "weekdays": weekdays}
             for t in collected]
    update_medication(context.user_data["edit_id"], user_id,
                      context.user_data["edit_name"], context.user_data["edit_dosage"],
                      context.user_data["edit_meal"], total, rules)
    await query.edit_message_text(
        _med_saved_text("обновлено", context.user_data["edit_name"], context.user_data["edit_dosage"],
                        context.user_data["edit_meal"], total, collected,
                        freq_suffix=f" — {_freq_label('weekdays', None, weekdays, None)}")
    )
    context.user_data.clear()
    return ConversationHandler.END


@handle_db_errors
async def edit_freq_monthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = _parse_int_range(update.message.text, 1, 31)
    if day is None:
        await update.message.reply_text("Введи число от 1 до 31:", reply_markup=_EDIT_FREQ_MONTHDAY_KB)
        return EDIT_FREQ_MONTHDAY
    user_id = context.user_data["edit_user_id"]
    collected = context.user_data["edit_collected"]
    total = len(collected)
    rules = [{"reminder_time": t, "frequency": "monthly", "month_day": day}
             for t in collected]
    update_medication(context.user_data["edit_id"], user_id,
                      context.user_data["edit_name"], context.user_data["edit_dosage"],
                      context.user_data["edit_meal"], total, rules)
    from handlers.meds_common import _monthday_warning
    warning = _monthday_warning(day)
    await update.message.reply_text(
        _med_saved_text("обновлено", context.user_data["edit_name"], context.user_data["edit_dosage"],
                        context.user_data["edit_meal"], total, collected,
                        freq_suffix=f" — {_freq_label('monthly', None, None, day)}", warning=warning)
    )
    context.user_data.clear()
    return ConversationHandler.END


async def handle_multi_edit_change_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rules = context.user_data["edit_med"]["schedule_rules"]
    dosage_b = context.user_data.get("edit_dosage_b") or next(
        (r["dosage"] for r in rules if r.get("dosage")), ""
    )
    context.user_data["multi_dosage"] = True
    context.user_data["name"] = context.user_data["edit_name"]
    context.user_data["dosage"] = context.user_data["edit_dosage"]
    context.user_data["dosage_b"] = dosage_b
    context.user_data["meal"] = context.user_data.get("edit_meal") or context.user_data["edit_med"]["meal_relation"]
    presets = get_user_time_presets(update.effective_user.id)
    dosage_a = context.user_data["dosage"]
    await query.edit_message_text(
        f"⏰ <b>Когда принимать дозировку А ({escape_html(dosage_a)})?</b>\nВыбери один или несколько:",
        parse_mode="HTML",
        reply_markup=_timeslots_keyboard(set(), presets, back_cb="back_edit_to_freq_type")
    )
    return TIMES


# ── Edit flow: back handlers ───────────────────────────────────────────────

async def back_edit_to_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    med = context.user_data["edit_med"]
    await query.edit_message_text(
        f"✏️ <b>{escape_html(med['name'])}</b>\n──────────────────\n📝 <b>Название</b> — введи новое:",
        parse_mode="HTML",
        reply_markup=_EDIT_NAME_KB
    )
    return EDIT_NAME


async def back_edit_to_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    med = context.user_data["edit_med"]
    label = "Дозировка А" if context.user_data.get("edit_is_multi_dosage") else "Дозировка"
    await query.edit_message_text(
        f"📏 <b>{label}</b> — введи новую\n(текущая: {escape_html(med['dosage'])}):",
        parse_mode="HTML",
        reply_markup=_EDIT_DOSAGE_KB
    )
    return EDIT_DOSAGE


async def back_edit_to_freq_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await _show_edit_freq_type_step(context, query)


async def back_edit_to_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = context.user_data.get("edit_selected_slots", set())
    presets = get_user_time_presets(update.effective_user.id)
    await query.edit_message_text(
        "⏰ <b>Когда принимать?</b> — выбери один или несколько:\n\n<i>Время слотов меняется в ⚙️ Настройки → ⏰ Время приёмов.</i>",
        parse_mode="HTML",
        reply_markup=_edit_timeslots_keyboard(selected, presets)
    )
    return EDIT_TIMES


async def back_edit_to_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await _show_edit_dosage_b_step(context, query)


async def back_edit_to_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    edit_med = context.user_data["edit_med"]
    current_label = MEAL_LABELS.get(edit_med["meal_relation"], edit_med["meal_relation"])
    if context.user_data.get("edit_is_multi_dosage"):
        kb = _edit_meal_keyboard_multi(current_label)
    else:
        kb = _edit_meal_keyboard(current_label)
    await query.edit_message_text("🍽 <b>Приём с пищей</b> — выбери:", parse_mode="HTML", reply_markup=kb)
    return EDIT_MEAL
