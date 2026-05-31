import logging
from datetime import date, timedelta, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler,
                          CallbackQueryHandler, MessageHandler, filters)
from database import (get_or_create_user, add_medication, add_schedule_rule,
                      get_user_medications, deactivate_medication,
                      get_medication_by_id, get_schedules_by_medication, update_medication,
                      count_active_medications, get_user_time_presets)
from scheduler import clear_pending_for_medication
from constants import (NAME, DOSAGE, MEAL, TIMES, SCHEDULE,
                       EDIT_NAME, EDIT_DOSAGE, EDIT_MEAL, EDIT_TIMES, EDIT_SCHEDULE,
                       FREQ_TYPE, FREQ_INTERVAL, FREQ_WEEKDAYS, FREQ_MONTHDAY,
                       EDIT_FREQ_TYPE, EDIT_FREQ_INTERVAL, EDIT_FREQ_WEEKDAYS, EDIT_FREQ_MONTHDAY,
                       DOSAGE_B, TIMES_B, FREQ_TYPE_B, FREQ_INTERVAL_B, FREQ_WEEKDAYS_B, FREQ_MONTHDAY_B,
                       EDIT_DOSAGE_B,
                       MEAL_LABELS, MAX_MEDICATIONS_PER_USER, SLOT_ORDER, SLOT_LABELS, MONTHS_SHORT)
from utils import handle_db_errors, get_tz_for_user, escape_md, NAME_MAX_LEN, DOSAGE_MAX_LEN

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}

_CANCEL_BTN = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]])

_EDIT_NAME_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("➡️ Оставить текущее", callback_data="keep_edit_name")],
    [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
])
_EDIT_DOSAGE_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("➡️ Оставить текущее", callback_data="keep_edit_dosage")],
    [InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_name"),
     InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
])
_EDIT_DOSAGE_B_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("➡️ Оставить текущее", callback_data="keep_edit_dosage_b")],
    [InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_dosage"),
     InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
])

_ADD_DOSAGE_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("📊 Разная дозировка", callback_data="multi_dosage")],
    [InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_name"),
     InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
])

_ADD_FREQ_INTERVAL_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_freq_type"),
    InlineKeyboardButton("❌ Отмена", callback_data="cancel_add"),
]])
_ADD_FREQ_MONTHDAY_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_freq_type"),
    InlineKeyboardButton("❌ Отмена", callback_data="cancel_add"),
]])
_EDIT_FREQ_INTERVAL_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_meal"),
    InlineKeyboardButton("❌ Отмена", callback_data="cancel_add"),
]])
_EDIT_FREQ_MONTHDAY_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_meal"),
    InlineKeyboardButton("❌ Отмена", callback_data="cancel_add"),
]])


def _back_cancel_kb(back_cb: str) -> InlineKeyboardMarkup:
    """Универсальная клавиатура «◀️ Назад / ❌ Отмена» с произвольным back_cb."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data=back_cb),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_add"),
    ]])


def _freq_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа расписания А (добавление/редактирование лекарства)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Каждый день", callback_data="freq:daily")],
        [InlineKeyboardButton("🔄 Каждый N день", callback_data="freq:interval")],
        [InlineKeyboardButton("📆 По дням недели", callback_data="freq:weekdays")],
        [InlineKeyboardButton("🗓 Раз в месяц", callback_data="freq:monthly")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_meal"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _freq_type_b_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа расписания для дозировки Б (multi-dosage флоу)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Каждый день", callback_data="freqb:daily")],
        [InlineKeyboardButton("🔄 Каждый N день", callback_data="freqb:interval")],
        [InlineKeyboardButton("📆 По дням недели", callback_data="freqb:weekdays")],
        [InlineKeyboardButton("🗓 Раз в месяц", callback_data="freqb:monthly")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_meal"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _edit_freq_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора расписания при редактировании обычного лекарства."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Оставить расписание", callback_data="keep_edit_schedule")],
        [InlineKeyboardButton("📅 Каждый день", callback_data="editfreq:daily")],
        [InlineKeyboardButton("🔄 Каждый N день", callback_data="editfreq:interval")],
        [InlineKeyboardButton("📆 По дням недели", callback_data="editfreq:weekdays")],
        [InlineKeyboardButton("🗓 Раз в месяц", callback_data="editfreq:monthly")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_dosage"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _edit_freq_type_keyboard_multi() -> InlineKeyboardMarkup:
    """Клавиатура выбора расписания при редактировании лекарства с разной дозировкой."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Сохранить без изменений", callback_data="keep_edit_schedule")],
        [InlineKeyboardButton("🔄 Изменить расписание", callback_data="multi_edit_change_schedule")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_meal"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _weekdays_keyboard(selected: set) -> InlineKeyboardMarkup:
    """Клавиатура выбора дней недели для расписания А; отмечает уже выбранные."""
    row = [
        InlineKeyboardButton(
            f"✅ {name}" if d in selected else name,
            callback_data=f"weekday:{d}"
        )
        for d, name in WEEKDAY_NAMES.items()
    ]
    return InlineKeyboardMarkup([
        row[:4], row[4:],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_freq_type"),
         InlineKeyboardButton("✔️ Готово", callback_data="weekdays_confirm"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _weekdays_b_keyboard(selected: set) -> InlineKeyboardMarkup:
    """Клавиатура выбора дней недели для расписания Б (multi-dosage флоу)."""
    row = [
        InlineKeyboardButton(
            f"✅ {name}" if d in selected else name,
            callback_data=f"weekdayb:{d}"
        )
        for d, name in WEEKDAY_NAMES.items()
    ]
    return InlineKeyboardMarkup([
        row[:4], row[4:],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_multi_to_freq_type_b"),
         InlineKeyboardButton("✔️ Готово", callback_data="weekdaysb_confirm"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _edit_weekdays_keyboard(selected: set) -> InlineKeyboardMarkup:
    """Клавиатура выбора дней недели при редактировании расписания."""
    row = [
        InlineKeyboardButton(
            f"✅ {name}" if d in selected else name,
            callback_data=f"editweekday:{d}"
        )
        for d, name in WEEKDAY_NAMES.items()
    ]
    return InlineKeyboardMarkup([
        row[:4], row[4:],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_meal"),
         InlineKeyboardButton("✔️ Готово", callback_data="edit_weekdays_confirm"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _edit_meal_keyboard(current_label: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора способа приёма с пищей при редактировании (кнопка «Оставить» + 4 варианта)."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"➡️ Оставить ({current_label})", callback_data="keep_edit_meal")]]
        + [[InlineKeyboardButton(label, callback_data=f"editmeal:{key}")] for key, label in MEAL_LABELS.items()]
        + [[InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_times"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]]
    )


def _edit_meal_keyboard_multi(current_label: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора приёма с пищей при редактировании multi-dosage (назад → dosage_b)."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"➡️ Оставить ({current_label})", callback_data="keep_edit_meal")]]
        + [[InlineKeyboardButton(label, callback_data=f"editmeal:{key}")] for key, label in MEAL_LABELS.items()]
        + [[InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_dosage_b"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]]
    )


def _timeslots_keyboard(selected: set, presets: dict, back_cb: str = "back_add_to_dosage") -> InlineKeyboardMarkup:
    """Клавиатура multi-select временных слотов (Утро/Обед/Вечер/Ночь) с текущими пресетами."""
    btns = [
        InlineKeyboardButton(
            f"{'✅ ' if s in selected else ''}{SLOT_LABELS[s]} ({presets[s]})",
            callback_data=f"timeslot:{s}"
        )
        for s in SLOT_ORDER
    ]
    return InlineKeyboardMarkup([
        [btns[0], btns[1]],
        [btns[2], btns[3]],
        [InlineKeyboardButton("◀️ Назад", callback_data=back_cb),
         InlineKeyboardButton("✔️ Готово", callback_data="timeslots_confirm"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _timeslots_b_keyboard(selected: set, presets: dict) -> InlineKeyboardMarkup:
    """Клавиатура multi-select слотов для дозировки Б."""
    btns = [
        InlineKeyboardButton(
            f"{'✅ ' if s in selected else ''}{SLOT_LABELS[s]} ({presets[s]})",
            callback_data=f"timeslotb:{s}"
        )
        for s in SLOT_ORDER
    ]
    return InlineKeyboardMarkup([
        [btns[0], btns[1]],
        [btns[2], btns[3]],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_multi_to_times_a"),
         InlineKeyboardButton("✔️ Готово", callback_data="timeslotsb_confirm"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _edit_timeslots_keyboard(selected: set, presets: dict) -> InlineKeyboardMarkup:
    """Клавиатура multi-select слотов при редактировании расписания."""
    btns = [
        InlineKeyboardButton(
            f"{'✅ ' if s in selected else ''}{SLOT_LABELS[s]} ({presets[s]})",
            callback_data=f"edittimeslot:{s}"
        )
        for s in SLOT_ORDER
    ]
    return InlineKeyboardMarkup([
        [btns[0], btns[1]],
        [btns[2], btns[3]],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_freq_type"),
         InlineKeyboardButton("✔️ Готово", callback_data="edit_timeslots_confirm"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _format_schedule_rule(rule) -> str:
    """Возвращает читаемое описание одного правила расписания (время + частота)."""
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


def _current_schedule_summary(rules: list) -> str:
    """Возвращает краткое описание расписания для отображения в шаге выбора типа."""
    if not rules:
        return "не указано"
    has_adv = any(r["frequency"] != "daily" for r in rules)
    if not has_adv:
        times = ", ".join(r["reminder_time"] for r in rules)
        return f"{times} (каждый день)"
    return " | ".join(_format_schedule_rule(r) for r in rules)


def _monthday_warning(day: int) -> str:
    """Возвращает предупреждение о месяцах с меньшим числом дней (29–31)."""
    if day == 29:
        return "\n\n⚠️ В феврале невисокосного года напоминание не сработает."
    if day == 30:
        return "\n\n⚠️ В феврале напоминание не сработает."
    if day == 31:
        return "\n\n⚠️ В феврале, апреле, июне, сентябре и ноябре напоминание не сработает."
    return ""


def _freq_label(freq: str, interval_days, weekdays_str, month_day) -> str:
    """Возвращает короткое человекочитаемое описание частоты (каждый день / каждые N дн. и т.д.)."""
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


def _dosage_a_summary(ud: dict) -> str:
    """Сводка дозировки А для отображения при настройке Б."""
    dosage_a = ud.get("dosage", "")
    times_a = ud.get("collected_times", [])
    freq_a = ud.get("freq_a", {})
    times_str = ", ".join(times_a) if times_a else "—"
    summary = f"📋 Дозировка А: *{escape_md(dosage_a)}* — {times_str}"
    if freq_a:
        freq_str = _freq_label(
            freq_a.get("type", "daily"),
            freq_a.get("interval_days"),
            freq_a.get("weekdays"),
            freq_a.get("month_day"),
        )
        summary += f" ({freq_str})"
    return summary


# ── Next-fire helpers ─────────────────────────────────────────────────────

def _compute_next_fire(rule, today: date):
    """Вычисляет ближайшую дату срабатывания правила начиная с today; None если не определить."""
    freq = rule["frequency"]
    if freq == "daily":
        return today
    if freq == "interval":
        anchor_str = rule["anchor_date"]
        if not anchor_str:
            return None
        anchor = date.fromisoformat(anchor_str)
        interval = rule["interval_days"] or 1
        remainder = (today - anchor).days % interval
        return today if remainder == 0 else today + timedelta(days=interval - remainder)
    if freq == "weekdays":
        days = [int(d) for d in (rule["weekdays"] or "").split(",") if d]
        for offset in range(7):
            candidate = today + timedelta(days=offset)
            if candidate.isoweekday() in days:
                return candidate
        return None
    if freq == "monthly":
        month_day = rule["month_day"]
        if not month_day:
            return None
        for offset in range(3):
            year = today.year + (today.month + offset - 1) // 12
            month = (today.month + offset - 1) % 12 + 1
            try:
                candidate = date(year, month, month_day)
                if candidate >= today:
                    return candidate
            except ValueError:
                continue
        return None
    return None


def _next_fire_label(rule, today: date) -> str:
    """Возвращает подпись «(сегодня)», «(завтра)», «(пн)», «(3 янв)» для правила с нестандартной частотой."""
    if rule["frequency"] == "daily":
        return ""
    fire = _compute_next_fire(rule, today)
    if fire is None:
        return ""
    delta = (fire - today).days
    if delta == 0:
        return " (сегодня)"
    if delta == 1:
        return " (завтра)"
    if delta == 2:
        return " (послезавтра)"
    if delta <= 6:
        names = {1: "пн", 2: "вт", 3: "ср", 4: "чт", 5: "пт", 6: "сб", 7: "вс"}
        return f" ({names[fire.isoweekday()]})"
    return f" ({fire.day} {MONTHS_SHORT[fire.month - 1]})"


# ── Display ────────────────────────────────────────────────────────────────

async def show_meds_list(message, user):
    """Отображает список активных лекарств пользователя с расписанием и кнопками Изменить/Удалить."""
    user_id = get_or_create_user(user.id, user.username)
    meds = get_user_medications(user_id)
    user_tz = get_tz_for_user(user.id)
    today_local = datetime.now(user_tz).date()

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

        is_multi_dosage = any(r["dosage"] for r in rules)

        # Собираем уникальные дозировки для заголовка
        dosages = [med["dosage"]]
        for r in rules:
            if r["dosage"] and r["dosage"] not in dosages:
                dosages.append(r["dosage"])
        dosage_display = " / ".join(dosages)

        if is_multi_dosage:
            rule_strs = []
            for r in rules:
                effective = r["dosage"] if r["dosage"] else med["dosage"]
                label = _next_fire_label(r, today_local)
                rule_strs.append(f"⏰ {_format_schedule_rule(r)} — {escape_md(effective)}{label}")
            schedule_str = "\n".join(rule_strs) or "не указано"
        elif not has_advanced:
            schedule_str = ", ".join(r["reminder_time"] for r in rules) or "не указано"
        else:
            schedule_str = "\n".join(_format_schedule_rule(r) for r in rules) or "не указано"

        meal = MEAL_LABELS.get(med["meal_relation"], med["meal_relation"])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{med['id']}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{med['id']}"),
        ]])
        text = (
            f"*{escape_md(med['name'])}* — {escape_md(dosage_display)}\n"
            f"🍽 {meal}\n"
        )
        if not has_advanced and not is_multi_dosage:
            text += f"🔢 {med['times_per_day']} раз в день\n"
        if is_multi_dosage:
            text += schedule_str
        else:
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
    """Обработчик /meds: показывает список лекарств пользователя."""
    await show_meds_list(update.message, update.effective_user)


# ── Common ─────────────────────────────────────────────────────────────────

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет активный диалог добавления/редактирования лекарства."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Отменено.")
    return ConversationHandler.END


# ── Add flow: entry ────────────────────────────────────────────────────────

async def handle_add_med_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point добавления лекарства через кнопку «➕ Добавить»; проверяет лимит."""
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
    """Entry point добавления лекарства через команду /add; проверяет лимит."""
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
    """Принимает название лекарства, валидирует длину и переходит к шагу дозировки."""
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
    """Активирует режим разных дозировок и переходит к вводу дозировки А."""
    query = update.callback_query
    await query.answer()
    context.user_data["multi_dosage"] = True
    await query.edit_message_text(
        "Введи *дозировку А* (например: 25 мкг):",
        parse_mode="Markdown",
        reply_markup=_back_cancel_kb("back_add_to_name")
    )
    return DOSAGE


async def add_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает дозировку А, в multi-режиме переходит к дозировке Б, иначе к выбору слотов."""
    dosage = update.message.text.strip()
    if len(dosage) > DOSAGE_MAX_LEN:
        await update.message.reply_text(f"Дозировка не может быть длиннее {DOSAGE_MAX_LEN} символов. Попробуй ещё раз:")
        return DOSAGE
    context.user_data["dosage"] = dosage
    if context.user_data.get("multi_dosage"):
        dosage_a = context.user_data["dosage"]
        await update.message.reply_text(
            f"Введи *дозировку Б* (например: 50 мкг):\n_Дозировка А: {escape_md(dosage_a)}_",
            parse_mode="Markdown",
            reply_markup=_back_cancel_kb("back_multi_to_dosage_a")
        )
        return DOSAGE_B
    context.user_data.setdefault("selected_slots", set())
    selected = context.user_data["selected_slots"]
    presets = get_user_time_presets(update.effective_user.id)
    await update.message.reply_text(
        "⏰ *Когда принимать?* — выбери один или несколько:",
        parse_mode="Markdown",
        reply_markup=_timeslots_keyboard(selected, presets)
    )
    return TIMES


async def add_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает дозировку Б и переходит к выбору временных слотов для дозировки А."""
    dosage_b = update.message.text.strip()
    if len(dosage_b) > DOSAGE_MAX_LEN:
        await update.message.reply_text(f"Дозировка не может быть длиннее {DOSAGE_MAX_LEN} символов. Попробуй ещё раз:")
        return DOSAGE_B
    context.user_data["dosage_b"] = dosage_b
    dosage_a = context.user_data["dosage"]
    context.user_data.setdefault("selected_slots", set())
    presets = get_user_time_presets(update.effective_user.id)
    await update.message.reply_text(
        f"⏰ *Когда принимать дозировку А ({escape_md(dosage_a)})?*\nВыбери один или несколько:",
        parse_mode="Markdown",
        reply_markup=_timeslots_keyboard(set(), presets, back_cb="back_multi_to_dosage_b")
    )
    return TIMES


# ── Add flow: slot toggle A → meal ─────────────────────────────────────────

async def add_timeslot_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает выбор временного слота А и обновляет клавиатуру."""
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
    """Подтверждает выбор слотов А; в multi-режиме переходит к слотам Б, иначе к выбору питания."""
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
            f"{summary_a}\n\n⏰ *Когда принимать дозировку Б ({escape_md(dosage_b)})?*\nВыбери один или несколько:",
            parse_mode="Markdown",
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
        "🍽 *Как принимать с пищей?*",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MEAL


# ── Add flow: slot toggle B ────────────────────────────────────────────────

async def add_timeslot_b_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает выбор временного слота Б и обновляет клавиатуру."""
    query = update.callback_query
    await query.answer()
    slot = query.data.split(":")[1]
    selected = context.user_data.setdefault("selected_slots_b", set())
    selected.discard(slot) if slot in selected else selected.add(slot)
    presets = get_user_time_presets(update.effective_user.id)
    await query.edit_message_reply_markup(reply_markup=_timeslots_b_keyboard(selected, presets))
    return TIMES_B


async def add_timeslots_b_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает слоты Б; в edit-режиме переходит к расписанию А, иначе к выбору питания."""
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
            f"📅 *Расписание для дозировки А ({escape_md(dosage_a)})* — выбери:",
            parse_mode="Markdown", reply_markup=_freq_type_keyboard()
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
        "🍽 *Как принимать с пищей?* (для обеих дозировок)",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MEAL


# ── Add flow: meal ─────────────────────────────────────────────────────────

async def add_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет выбранный способ приёма с пищей и переходит к выбору расписания."""
    query = update.callback_query
    await query.answer()
    context.user_data["meal"] = query.data
    if context.user_data.get("multi_dosage"):
        dosage_a = context.user_data["dosage"]
        await query.edit_message_text(
            f"📅 *Расписание для дозировки А ({escape_md(dosage_a)})* — выбери:",
            parse_mode="Markdown", reply_markup=_freq_type_keyboard()
        )
    else:
        await query.edit_message_text(
            "📅 *Тип расписания* — выбери:",
            parse_mode="Markdown", reply_markup=_freq_type_keyboard()
        )
    return FREQ_TYPE


# ── Add flow: freq type A ──────────────────────────────────────────────────

async def _go_to_freq_type_b(edit_target, context, from_message: bool = False):
    """Переход к выбору расписания для дозировки Б."""
    summary = _dosage_a_summary(context.user_data)
    dosage_b = context.user_data.get("dosage_b", "")
    text = f"{summary}\n\n📅 *Расписание для дозировки Б ({escape_md(dosage_b)})* — выбери:"
    if from_message:
        await edit_target.reply_text(text, parse_mode="Markdown", reply_markup=_freq_type_b_keyboard())
    else:
        await edit_target.edit_message_text(text, parse_mode="Markdown", reply_markup=_freq_type_b_keyboard())
    return FREQ_TYPE_B


@handle_db_errors
async def choose_freq_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор типа расписания А; при daily сразу сохраняет, иначе запрашивает параметры."""
    query = update.callback_query
    await query.answer()
    freq = query.data.split(":")[1]
    multi = context.user_data.get("multi_dosage")

    if freq == "daily":
        if multi:
            context.user_data["freq_a"] = {"type": "daily"}
            return await _go_to_freq_type_b(query, context)
        user = update.effective_user
        user_id = get_or_create_user(user.id, user.username)
        if count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
            await query.message.reply_text(
                f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств.")
            context.user_data.clear()
            return ConversationHandler.END
        collected = context.user_data["collected_times"]
        total = len(collected)
        med_id = add_medication(user_id, context.user_data["name"],
                                context.user_data["dosage"], context.user_data["meal"], total)
        for t in collected:
            add_schedule_rule(med_id, t, "daily")
        await query.edit_message_text(
            f"✅ Лекарство добавлено!\n\n"
            f"💊 {context.user_data['name']} — {context.user_data['dosage']}\n"
            f"🍽 {MEAL_LABELS[context.user_data['meal']]}\n"
            f"🔢 {total} раз в день\n"
            f"⏰ {', '.join(collected)}"
        )
        context.user_data.clear()
        return ConversationHandler.END

    if freq == "interval":
        await query.edit_message_text("🔄 *Через сколько дней?* (например: 2):",
                                      parse_mode="Markdown", reply_markup=_ADD_FREQ_INTERVAL_KB)
        return FREQ_INTERVAL

    if freq == "weekdays":
        context.user_data["freq_weekdays"] = set()
        await query.edit_message_text(
            "📆 *По дням недели* — выбери и нажми Готово:",
            parse_mode="Markdown", reply_markup=_weekdays_keyboard(set())
        )
        return FREQ_WEEKDAYS

    if freq == "monthly":
        await query.edit_message_text("🗓 *Какого числа каждого месяца?* (1–31):",
                                      parse_mode="Markdown", reply_markup=_ADD_FREQ_MONTHDAY_KB)
        return FREQ_MONTHDAY

    return FREQ_TYPE


@handle_db_errors
async def add_freq_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает интервал N дней (2–90), сохраняет лекарство или переходит к расписанию Б."""
    try:
        n = int(update.message.text.strip())
        assert 2 <= n <= 90
    except (ValueError, AssertionError):
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
    user_id = get_or_create_user(user.id, user.username)
    if count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
        await update.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств.")
        context.user_data.clear()
        return ConversationHandler.END
    collected = context.user_data["collected_times"]
    total = len(collected)
    anchor_date = date.today().isoformat()
    med_id = add_medication(user_id, context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"], total)
    for t in collected:
        add_schedule_rule(med_id, t, "interval", interval_days=n, anchor_date=anchor_date)
    await update.message.reply_text(
        f"✅ Лекарство добавлено!\n\n"
        f"💊 {context.user_data['name']} — {context.user_data['dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(collected)} — {_freq_label('interval', n, None, None)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def toggle_weekday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает выбор дня недели для расписания А."""
    query = update.callback_query
    await query.answer()
    day = int(query.data.split(":")[1])
    selected = context.user_data.setdefault("freq_weekdays", set())
    selected.discard(day) if day in selected else selected.add(day)
    await query.edit_message_reply_markup(reply_markup=_weekdays_keyboard(selected))
    return FREQ_WEEKDAYS


@handle_db_errors
async def confirm_weekdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает выбор дней недели для расписания А и сохраняет лекарство или переходит к Б."""
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
    user_id = get_or_create_user(user.id, user.username)
    if count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
        await query.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств.")
        context.user_data.clear()
        return ConversationHandler.END
    collected = context.user_data["collected_times"]
    total = len(collected)
    med_id = add_medication(user_id, context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"], total)
    for t in collected:
        add_schedule_rule(med_id, t, "weekdays", weekdays=weekdays)
    await query.edit_message_text(
        f"✅ Лекарство добавлено!\n\n"
        f"💊 {context.user_data['name']} — {context.user_data['dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(collected)} — {_freq_label('weekdays', None, weekdays, None)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


@handle_db_errors
async def add_freq_monthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает число месяца (1–31) для ежемесячного расписания А."""
    try:
        day = int(update.message.text.strip())
        assert 1 <= day <= 31
    except (ValueError, AssertionError):
        await update.message.reply_text("Введи число от 1 до 31:", reply_markup=_ADD_FREQ_MONTHDAY_KB)
        return FREQ_MONTHDAY
    if context.user_data.get("multi_dosage"):
        context.user_data["freq_a"] = {"type": "monthly", "month_day": day}
        return await _go_to_freq_type_b(update.message, context, from_message=True)
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    if count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
        await update.message.reply_text(
            f"⚠️ Достигнут лимит: максимум {MAX_MEDICATIONS_PER_USER} лекарств.")
        context.user_data.clear()
        return ConversationHandler.END
    collected = context.user_data["collected_times"]
    total = len(collected)
    med_id = add_medication(user_id, context.user_data["name"],
                            context.user_data["dosage"], context.user_data["meal"], total)
    for t in collected:
        add_schedule_rule(med_id, t, "monthly", month_day=day)
    warning = _monthday_warning(day)
    await update.message.reply_text(
        f"✅ Лекарство добавлено!\n\n"
        f"💊 {context.user_data['name']} — {context.user_data['dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(collected)} — {_freq_label('monthly', None, None, day)}"
        f"{warning}"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Add flow: freq type B ──────────────────────────────────────────────────

@handle_db_errors
async def choose_freq_type_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор типа расписания Б; при daily сразу сохраняет multi-dosage лекарство."""
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
            f"{summary}\n\n🔄 *Дозировка Б ({escape_md(dosage_b)}) — через сколько дней?* (например: 2):",
            parse_mode="Markdown",
            reply_markup=_back_cancel_kb("back_multi_to_freq_type_b")
        )
        return FREQ_INTERVAL_B
    if freq == "weekdays":
        context.user_data["freq_b_weekdays"] = set()
        summary = _dosage_a_summary(context.user_data)
        dosage_b = context.user_data.get("dosage_b", "")
        await query.edit_message_text(
            f"{summary}\n\n📆 *Дозировка Б ({escape_md(dosage_b)}) — дни недели:*",
            parse_mode="Markdown",
            reply_markup=_weekdays_b_keyboard(set())
        )
        return FREQ_WEEKDAYS_B
    if freq == "monthly":
        summary = _dosage_a_summary(context.user_data)
        dosage_b = context.user_data.get("dosage_b", "")
        await query.edit_message_text(
            f"{summary}\n\n🗓 *Дозировка Б ({escape_md(dosage_b)}) — какого числа каждого месяца?* (1–31):",
            parse_mode="Markdown",
            reply_markup=_back_cancel_kb("back_multi_to_freq_type_b")
        )
        return FREQ_MONTHDAY_B
    return FREQ_TYPE_B


@handle_db_errors
async def add_freq_interval_b_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает интервал N дней для расписания Б и запрашивает дату начала (anchor_date)."""
    try:
        n = int(update.message.text.strip())
        assert 2 <= n <= 90
    except (ValueError, AssertionError):
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
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Сегодня (те же дни что А)", callback_data="freqb_anchor:0"),
            InlineKeyboardButton("📅 Завтра (чередование)", callback_data="freqb_anchor:1"),
        ]])
    )
    return FREQ_INTERVAL_B


@handle_db_errors
async def add_freq_interval_b_anchor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает выбор «Сегодня»/«Завтра» как anchor_date расписания Б и сохраняет лекарство."""
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
    """Переключает выбор дня недели для расписания Б."""
    query = update.callback_query
    await query.answer()
    day = int(query.data.split(":")[1])
    selected = context.user_data.setdefault("freq_b_weekdays", set())
    selected.discard(day) if day in selected else selected.add(day)
    await query.edit_message_reply_markup(reply_markup=_weekdays_b_keyboard(selected))
    return FREQ_WEEKDAYS_B


@handle_db_errors
async def confirm_weekdays_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает выбор дней недели для расписания Б и сохраняет multi-dosage лекарство."""
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
    """Принимает число месяца для расписания Б и сохраняет multi-dosage лекарство."""
    try:
        day = int(update.message.text.strip())
        assert 1 <= day <= 31
    except (ValueError, AssertionError):
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


# ── Add flow: save multi-dosage medication ─────────────────────────────────

async def _save_multi_medication(edit_target, context, user_id: int,
                                 freq_b: dict, from_message: bool = False, warning: str = ""):
    """Сохраняет multi-dosage лекарство (создаёт или обновляет).

    Работает как в add-флоу, так и в edit-флоу (определяется по наличию edit_id в user_data).
    Правила А хранят dosage=NULL (наследуют из medications), правила Б — явный dosage.
    """
    ud = context.user_data
    is_edit_mode = "edit_id" in ud
    if not is_edit_mode and count_active_medications(user_id) >= MAX_MEDICATIONS_PER_USER:
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
        from database import update_medication as _update_med
        clear_pending_for_medication(ud["edit_id"])
        _update_med(ud["edit_id"], user_id, name, dosage_a, meal, total, rules_for_db)
    else:
        med_id = add_medication(user_id, name, dosage_a, meal, total)
        for r in rules_for_db:
            add_schedule_rule(
                med_id, r["reminder_time"], r["frequency"],
                interval_days=r.get("interval_days"), weekdays=r.get("weekdays"),
                month_day=r.get("month_day"), anchor_date=r.get("anchor_date"),
                dosage=r.get("dosage")
            )

    freq_a_label = _freq_label(freq_a["type"], freq_a.get("interval_days"),
                                freq_a.get("weekdays"), freq_a.get("month_day"))
    freq_b_label = _freq_label(freq_b["type"], freq_b.get("interval_days"),
                                freq_b.get("weekdays"), freq_b.get("month_day"))

    text = (
        f"✅ Лекарство добавлено!\n\n"
        f"💊 *{escape_md(name)}*\n"
        f"🍽 {MEAL_LABELS[meal]}\n\n"
        f"Дозировка А: *{escape_md(dosage_a)}*\n"
        f"⏰ {', '.join(times_a)} — {freq_a_label}\n\n"
        f"Дозировка Б: *{escape_md(dosage_b)}*\n"
        f"⏰ {', '.join(times_b)} — {freq_b_label}"
        f"{warning}"
    )

    if from_message:
        await edit_target.reply_text(text, parse_mode="Markdown")
    else:
        await edit_target.edit_message_text(text, parse_mode="Markdown")
    context.user_data.clear()
    return ConversationHandler.END


# ── Add flow: back handlers ────────────────────────────────────────────────

async def back_add_to_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу ввода названия лекарства."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("multi_dosage", None)
    await query.edit_message_text("Как называется лекарство?", reply_markup=_CANCEL_BTN)
    return NAME


async def back_add_to_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу ввода дозировки."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Укажи дозировку (например: 500мг, 1 таблетка):",
        reply_markup=_ADD_DOSAGE_KB
    )
    return DOSAGE


async def back_multi_to_dosage_a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Назад к вводу дозировки А (в multi-режиме)."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("dosage", None)
    await query.edit_message_text(
        "Введи *дозировку А* (например: 25 мкг):",
        parse_mode="Markdown",
        reply_markup=_back_cancel_kb("back_add_to_name")
    )
    return DOSAGE


async def back_multi_to_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Назад к вводу дозировки Б (в multi-режиме)."""
    query = update.callback_query
    await query.answer()
    dosage_a = context.user_data.get("dosage", "")
    context.user_data.pop("dosage_b", None)
    await query.edit_message_text(
        f"Введи *дозировку Б* (например: 50 мкг):\n_Дозировка А: {escape_md(dosage_a)}_",
        parse_mode="Markdown",
        reply_markup=_back_cancel_kb("back_multi_to_dosage_a")
    )
    return DOSAGE_B


async def back_add_to_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу выбора слотов; в multi-режиме — к слотам Б."""
    query = update.callback_query
    await query.answer()
    presets = get_user_time_presets(update.effective_user.id)
    if context.user_data.get("multi_dosage"):
        selected_b = context.user_data.get("selected_slots_b", set())
        summary_a = _dosage_a_summary(context.user_data)
        dosage_b = context.user_data.get("dosage_b", "")
        await query.edit_message_text(
            f"{summary_a}\n\n⏰ *Когда принимать дозировку Б ({escape_md(dosage_b)})?*\nВыбери один или несколько:",
            parse_mode="Markdown",
            reply_markup=_timeslots_b_keyboard(selected_b, presets)
        )
        return TIMES_B
    selected = context.user_data.get("selected_slots", set())
    await query.edit_message_text(
        "⏰ *Когда принимать?* — выбери один или несколько:",
        parse_mode="Markdown",
        reply_markup=_timeslots_keyboard(selected, presets)
    )
    return TIMES


async def back_multi_to_times_a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Назад к слотам дозировки А из TIMES_B."""
    query = update.callback_query
    await query.answer()
    selected = context.user_data.get("selected_slots", set())
    presets = get_user_time_presets(update.effective_user.id)
    dosage_a = context.user_data.get("dosage", "")
    await query.edit_message_text(
        f"⏰ *Когда принимать дозировку А ({escape_md(dosage_a)})?*\nВыбери один или несколько:",
        parse_mode="Markdown",
        reply_markup=_timeslots_keyboard(selected, presets, back_cb="back_multi_to_dosage_b")
    )
    return TIMES


async def back_add_to_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу выбора питания; в edit multi-режиме маршрутизирует по состоянию freq_a."""
    query = update.callback_query
    await query.answer()
    if context.user_data.get("edit_id"):
        presets = get_user_time_presets(update.effective_user.id)
        if context.user_data.get("freq_a"):
            # Coming from FREQ_TYPE_B → back to FREQ_TYPE A
            dosage_a = context.user_data.get("dosage", "")
            await query.edit_message_text(
                f"📅 *Расписание для дозировки А ({escape_md(dosage_a)})* — выбери:",
                parse_mode="Markdown", reply_markup=_freq_type_keyboard()
            )
            return FREQ_TYPE
        else:
            # Coming from FREQ_TYPE A → back to TIMES_B
            selected_b = context.user_data.get("selected_slots_b", set())
            dosage_b = context.user_data.get("dosage_b", "")
            summary_a = _dosage_a_summary(context.user_data)
            await query.edit_message_text(
                f"{summary_a}\n\n⏰ *Когда принимать дозировку Б ({escape_md(dosage_b)})?*\nВыбери один или несколько:",
                parse_mode="Markdown",
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
        "🍽 *Как принимать с пищей?*",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MEAL


async def back_add_to_freq_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу выбора типа расписания А."""
    query = update.callback_query
    await query.answer()
    if context.user_data.get("multi_dosage"):
        dosage_a = context.user_data.get("dosage", "")
        await query.edit_message_text(
            f"📅 *Расписание для дозировки А ({escape_md(dosage_a)})* — выбери:",
            parse_mode="Markdown", reply_markup=_freq_type_keyboard()
        )
    else:
        await query.edit_message_text(
            "📅 *Тип расписания* — выбери:",
            parse_mode="Markdown", reply_markup=_freq_type_keyboard()
        )
    return FREQ_TYPE


async def back_multi_to_freq_type_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Назад к выбору расписания Б."""
    query = update.callback_query
    await query.answer()
    return await _go_to_freq_type_b(query, context)


# ── Edit flow: entry & name/dosage ─────────────────────────────────────────

@handle_db_errors
async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Деактивирует лекарство и очищает его pending-напоминания."""
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
    """Инициализирует edit_id/edit_med в user_data и показывает первый шаг редактирования."""
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
        f"✏️ *Редактируем: {escape_md(med['name'])}*\n"
        f"💊 {dosage_display}  🍽 {MEAL_LABELS[med['meal_relation']]}\n"
        f"{schedule_block}\n"
        f"──────────────────\n"
        f"📝 *Название* — введи новое:",
        parse_mode="Markdown",
        reply_markup=_EDIT_NAME_KB
    )
    return EDIT_NAME


async def keep_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оставляет текущее название без изменений и переходит к шагу дозировки."""
    query = update.callback_query
    await query.answer()
    med = context.user_data["edit_med"]
    context.user_data["edit_name"] = med["name"]
    label = "Дозировка А" if context.user_data.get("edit_is_multi_dosage") else "Дозировка"
    await query.edit_message_text(
        f"📏 *{label}* — введи новую\n(текущая: {escape_md(med['dosage'])}):",
        parse_mode="Markdown",
        reply_markup=_EDIT_DOSAGE_KB
    )
    return EDIT_DOSAGE


async def edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает новое название лекарства и переходит к шагу дозировки."""
    name = update.message.text.strip()
    if len(name) > NAME_MAX_LEN:
        await update.message.reply_text(f"Название не может быть длиннее {NAME_MAX_LEN} символов. Попробуй ещё раз:")
        return EDIT_NAME
    context.user_data["edit_name"] = name
    med = context.user_data["edit_med"]
    label = "Дозировка А" if context.user_data.get("edit_is_multi_dosage") else "Дозировка"
    await update.message.reply_text(
        f"📏 *{label}* — введи новую\n(текущая: {escape_md(med['dosage'])}):",
        parse_mode="Markdown",
        reply_markup=_EDIT_DOSAGE_KB
    )
    return EDIT_DOSAGE


async def keep_edit_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оставляет дозировку А без изменений; в multi-режиме переходит к дозировке Б."""
    query = update.callback_query
    await query.answer()
    context.user_data["edit_dosage"] = context.user_data["edit_med"]["dosage"]
    if context.user_data.get("edit_is_multi_dosage"):
        return await _show_edit_dosage_b_step(context, query)
    return await _show_edit_freq_type_step(context, query)


async def edit_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает новую дозировку А; в multi-режиме переходит к дозировке Б."""
    dosage = update.message.text.strip()
    if len(dosage) > DOSAGE_MAX_LEN:
        await update.message.reply_text(f"Дозировка не может быть длиннее {DOSAGE_MAX_LEN} символов. Попробуй ещё раз:")
        return EDIT_DOSAGE
    context.user_data["edit_dosage"] = dosage
    if context.user_data.get("edit_is_multi_dosage"):
        return await _show_edit_dosage_b_step(context, update.message, from_message=True)
    return await _show_edit_freq_type_step(context, update.message, from_message=True)


async def _show_edit_dosage_b_step(context, target, from_message: bool = False):
    """Отображает шаг редактирования дозировки Б с текущим значением из schedule_rules."""
    rules = context.user_data["edit_med"]["schedule_rules"]
    current_b = next((r["dosage"] for r in rules if r.get("dosage")), "")
    text = f"📏 *Дозировка Б* — введи новую\n(текущая: {escape_md(current_b)}):"
    if from_message:
        await target.reply_text(text, parse_mode="Markdown", reply_markup=_EDIT_DOSAGE_B_KB)
    else:
        await target.edit_message_text(text, parse_mode="Markdown", reply_markup=_EDIT_DOSAGE_B_KB)
    return EDIT_DOSAGE_B


async def keep_edit_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оставляет дозировку Б без изменений и переходит к шагу приёма с пищей."""
    query = update.callback_query
    await query.answer()
    rules = context.user_data["edit_med"]["schedule_rules"]
    context.user_data["edit_dosage_b"] = next((r["dosage"] for r in rules if r.get("dosage")), "")
    return await _show_edit_meal_multi_step(context, query)


async def edit_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает новую дозировку Б и переходит к шагу приёма с пищей."""
    dosage_b = update.message.text.strip()
    if len(dosage_b) > DOSAGE_MAX_LEN:
        await update.message.reply_text(f"Дозировка не может быть длиннее {DOSAGE_MAX_LEN} символов. Попробуй ещё раз:")
        return EDIT_DOSAGE_B
    context.user_data["edit_dosage_b"] = dosage_b
    return await _show_edit_meal_multi_step(context, update.message, from_message=True)


async def _show_edit_meal_multi_step(context, target, from_message: bool = False):
    """Показывает шаг выбора приёма с пищей для multi-dosage редактирования."""
    edit_med = context.user_data["edit_med"]
    current_label = MEAL_LABELS.get(edit_med["meal_relation"], edit_med["meal_relation"])
    kb = _edit_meal_keyboard_multi(current_label)
    if from_message:
        await target.reply_text("🍽 *Приём с пищей* — выбери:", parse_mode="Markdown", reply_markup=kb)
    else:
        await target.edit_message_text("🍽 *Приём с пищей* — выбери:", parse_mode="Markdown", reply_markup=kb)
    return EDIT_MEAL


def _get_edit_rules_with_dosage(context) -> list:
    """Возвращает правила расписания с обновлённой дозировкой Б (если изменена)."""
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
    """Показывает шаг выбора расписания с учётом multi-dosage."""
    edit_med = context.user_data["edit_med"]
    rules = edit_med["schedule_rules"]
    is_multi = context.user_data.get("edit_is_multi_dosage")
    if is_multi:
        rule_lines = [
            f"{_format_schedule_rule(r)} — {escape_md(r.get('dosage') or edit_med['dosage'])}"
            for r in rules
        ]
        text = "📅 *Расписание* (разная дозировка):\n" + "\n".join(rule_lines)
        kb = _edit_freq_type_keyboard_multi()
    else:
        text = f"📅 *Расписание* — выбери тип:\nТекущее: {_current_schedule_summary(rules)}"
        kb = _edit_freq_type_keyboard()
    if from_message:
        await target.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await target.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    return EDIT_FREQ_TYPE


# ── Edit flow: freq type ───────────────────────────────────────────────────

@handle_db_errors
async def keep_edit_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет лекарство с текущим расписанием (без изменений в schedule_rules)."""
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
    """Сохраняет тип расписания и переходит к выбору временных слотов."""
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
        "⏰ *Когда принимать?* — выбери один или несколько:",
        parse_mode="Markdown",
        reply_markup=_edit_timeslots_keyboard(preselected, presets)
    )
    return EDIT_TIMES


# ── Edit flow: meal → route by freq type ──────────────────────────────────

@handle_db_errors
async def keep_edit_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оставляет текущий способ приёма с пищей и переходит к расписанию."""
    query = update.callback_query
    await query.answer()
    context.user_data["edit_meal"] = context.user_data["edit_med"]["meal_relation"]
    return await _route_after_edit_meal(query, context)


@handle_db_errors
async def edit_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет выбранный способ приёма и переходит к расписанию."""
    query = update.callback_query
    await query.answer()
    context.user_data["edit_meal"] = query.data.split(":")[1]
    return await _route_after_edit_meal(query, context)


async def _route_after_edit_meal(query, context):
    """После выбора питания маршрутизирует к расписанию (daily → сохранение, иначе → ввод параметров)."""
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
            f"✅ Лекарство обновлено!\n\n"
            f"💊 {context.user_data['edit_name']} — {context.user_data['edit_dosage']}\n"
            f"🍽 {MEAL_LABELS[context.user_data['edit_meal']]}\n"
            f"🔢 {total} раз в день\n"
            f"⏰ {', '.join(collected)}"
        )
        context.user_data.clear()
        return ConversationHandler.END

    if freq == "interval":
        await query.edit_message_text("🔄 *Через сколько дней?* (например: 2):",
                                      parse_mode="Markdown", reply_markup=_EDIT_FREQ_INTERVAL_KB)
        return EDIT_FREQ_INTERVAL

    if freq == "weekdays":
        context.user_data["edit_freq_weekdays"] = set()
        await query.edit_message_text(
            "📆 *Дни недели* — выбери и нажми Готово:",
            parse_mode="Markdown",
            reply_markup=_edit_weekdays_keyboard(set())
        )
        return EDIT_FREQ_WEEKDAYS

    if freq == "monthly":
        await query.edit_message_text("🗓 *Какого числа каждого месяца?* (1–31):",
                                      parse_mode="Markdown", reply_markup=_EDIT_FREQ_MONTHDAY_KB)
        return EDIT_FREQ_MONTHDAY

    return ConversationHandler.END


# ── Edit flow: slot toggle → meal ─────────────────────────────────────────

async def edit_timeslot_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает выбор слота при редактировании расписания."""
    query = update.callback_query
    await query.answer()
    slot = query.data.split(":")[1]
    selected = context.user_data.setdefault("edit_selected_slots", set())
    selected.discard(slot) if slot in selected else selected.add(slot)
    presets = get_user_time_presets(update.effective_user.id)
    await query.edit_message_reply_markup(reply_markup=_edit_timeslots_keyboard(selected, presets))
    return EDIT_TIMES


async def edit_timeslots_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает выбор слотов при редактировании и переходит к шагу приёма с пищей."""
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
        "🍽 *Приём с пищей* — выбери:",
        parse_mode="Markdown",
        reply_markup=_edit_meal_keyboard(current_label)
    )
    return EDIT_MEAL


# ── Edit flow: advanced paths ──────────────────────────────────────────────

@handle_db_errors
async def edit_freq_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает интервал N дней при редактировании и сохраняет обновлённое расписание."""
    try:
        n = int(update.message.text.strip())
        assert 2 <= n <= 90
    except (ValueError, AssertionError):
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
        f"✅ Лекарство обновлено!\n\n"
        f"💊 {context.user_data['edit_name']} — {context.user_data['edit_dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['edit_meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(collected)} — {_freq_label('interval', n, None, None)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def toggle_edit_weekday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает выбор дня недели при редактировании расписания."""
    query = update.callback_query
    await query.answer()
    day = int(query.data.split(":")[1])
    selected = context.user_data.setdefault("edit_freq_weekdays", set())
    selected.discard(day) if day in selected else selected.add(day)
    await query.edit_message_reply_markup(reply_markup=_edit_weekdays_keyboard(selected))
    return EDIT_FREQ_WEEKDAYS


@handle_db_errors
async def confirm_edit_weekdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает дни недели при редактировании и сохраняет расписание."""
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
        f"✅ Лекарство обновлено!\n\n"
        f"💊 {context.user_data['edit_name']} — {context.user_data['edit_dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['edit_meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(collected)} — {_freq_label('weekdays', None, weekdays, None)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


@handle_db_errors
async def edit_freq_monthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает число месяца при редактировании и сохраняет обновлённое расписание."""
    try:
        day = int(update.message.text.strip())
        assert 1 <= day <= 31
    except (ValueError, AssertionError):
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
    warning = _monthday_warning(day)
    await update.message.reply_text(
        f"✅ Лекарство обновлено!\n\n"
        f"💊 {context.user_data['edit_name']} — {context.user_data['edit_dosage']}\n"
        f"🍽 {MEAL_LABELS[context.user_data['edit_meal']]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(collected)} — {_freq_label('monthly', None, None, day)}"
        f"{warning}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def handle_multi_edit_change_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к изменению расписания multi-dosage: вход в add-флоу с edit_id."""
    query = update.callback_query
    await query.answer()
    rules = context.user_data["edit_med"]["schedule_rules"]
    # dosage_b из edit_dosage_b (если менялась) или из правил
    dosage_b = context.user_data.get("edit_dosage_b") or next(
        (r["dosage"] for r in rules if r.get("dosage")), ""
    )
    # Сохраняем edit-контекст и добавляем add-флоу данные
    context.user_data["multi_dosage"] = True
    context.user_data["name"] = context.user_data["edit_name"]
    context.user_data["dosage"] = context.user_data["edit_dosage"]
    context.user_data["dosage_b"] = dosage_b
    context.user_data["meal"] = context.user_data.get("edit_meal") or context.user_data["edit_med"]["meal_relation"]
    presets = get_user_time_presets(update.effective_user.id)
    dosage_a = context.user_data["dosage"]
    await query.edit_message_text(
        f"⏰ *Когда принимать дозировку А ({escape_md(dosage_a)})?*\nВыбери один или несколько:",
        parse_mode="Markdown",
        reply_markup=_timeslots_keyboard(set(), presets, back_cb="back_edit_to_freq_type")
    )
    return TIMES



# ── Edit flow: back handlers ───────────────────────────────────────────────

async def back_edit_to_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу ввода названия при редактировании."""
    query = update.callback_query
    await query.answer()
    med = context.user_data["edit_med"]
    await query.edit_message_text(
        f"✏️ *{escape_md(med['name'])}*\n──────────────────\n📝 *Название* — введи новое:",
        parse_mode="Markdown",
        reply_markup=_EDIT_NAME_KB
    )
    return EDIT_NAME


async def back_edit_to_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу дозировки А при редактировании."""
    query = update.callback_query
    await query.answer()
    med = context.user_data["edit_med"]
    label = "Дозировка А" if context.user_data.get("edit_is_multi_dosage") else "Дозировка"
    await query.edit_message_text(
        f"📏 *{label}* — введи новую\n(текущая: {escape_md(med['dosage'])}):",
        parse_mode="Markdown",
        reply_markup=_EDIT_DOSAGE_KB
    )
    return EDIT_DOSAGE


async def back_edit_to_freq_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу выбора расписания при редактировании."""
    query = update.callback_query
    await query.answer()
    return await _show_edit_freq_type_step(context, query)


async def back_edit_to_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу выбора слотов при редактировании."""
    query = update.callback_query
    await query.answer()
    selected = context.user_data.get("edit_selected_slots", set())
    presets = get_user_time_presets(update.effective_user.id)
    await query.edit_message_text(
        "⏰ *Когда принимать?* — выбери один или несколько:",
        parse_mode="Markdown",
        reply_markup=_edit_timeslots_keyboard(selected, presets)
    )
    return EDIT_TIMES


async def back_edit_to_dosage_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу дозировки Б при редактировании multi-dosage лекарства."""
    query = update.callback_query
    await query.answer()
    return await _show_edit_dosage_b_step(context, query)


async def back_edit_to_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к шагу приёма с пищей при редактировании (обычный или multi режим)."""
    query = update.callback_query
    await query.answer()
    edit_med = context.user_data["edit_med"]
    current_label = MEAL_LABELS.get(edit_med["meal_relation"], edit_med["meal_relation"])
    if context.user_data.get("edit_is_multi_dosage"):
        kb = _edit_meal_keyboard_multi(current_label)
    else:
        kb = _edit_meal_keyboard(current_label)
    await query.edit_message_text("🍽 *Приём с пищей* — выбери:", parse_mode="Markdown", reply_markup=kb)
    return EDIT_MEAL


# ── ConversationHandler factories ──────────────────────────────────────────

def get_add_handler(cancel_handler):
    """Возвращает ConversationHandler для добавления лекарства (включая multi-dosage флоу)."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            CallbackQueryHandler(handle_add_med_callback, pattern="^add_med$"),
        ],
        states={
            NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_name),
            ],
            DOSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_dosage),
                CallbackQueryHandler(enter_multi_dosage_mode, pattern="^multi_dosage$"),
                CallbackQueryHandler(back_add_to_name, pattern="^back_add_to_name$"),
            ],
            DOSAGE_B: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_dosage_b),
                CallbackQueryHandler(back_multi_to_dosage_a, pattern="^back_multi_to_dosage_a$"),
            ],
            TIMES: [
                CallbackQueryHandler(add_timeslot_toggle, pattern="^timeslot:"),
                CallbackQueryHandler(add_timeslots_confirm, pattern="^timeslots_confirm$"),
                CallbackQueryHandler(back_add_to_dosage, pattern="^back_add_to_dosage$"),
                CallbackQueryHandler(back_multi_to_dosage_b, pattern="^back_multi_to_dosage_b$"),
            ],
            TIMES_B: [
                CallbackQueryHandler(add_timeslot_b_toggle, pattern="^timeslotb:"),
                CallbackQueryHandler(add_timeslots_b_confirm, pattern="^timeslotsb_confirm$"),
                CallbackQueryHandler(back_multi_to_times_a, pattern="^back_multi_to_times_a$"),
            ],
            MEAL: [
                CallbackQueryHandler(add_meal, pattern="^(before|after|with|any)$"),
                CallbackQueryHandler(back_add_to_times, pattern="^back_add_to_times$"),
            ],
            FREQ_TYPE: [
                CallbackQueryHandler(choose_freq_type, pattern="^freq:"),
                CallbackQueryHandler(back_add_to_meal, pattern="^back_add_to_meal$"),
            ],
            FREQ_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_interval),
                CallbackQueryHandler(back_add_to_freq_type, pattern="^back_add_to_freq_type$"),
            ],
            FREQ_WEEKDAYS: [
                CallbackQueryHandler(toggle_weekday, pattern="^weekday:\\d+$"),
                CallbackQueryHandler(confirm_weekdays, pattern="^weekdays_confirm$"),
                CallbackQueryHandler(back_add_to_freq_type, pattern="^back_add_to_freq_type$"),
            ],
            FREQ_MONTHDAY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_monthday),
                CallbackQueryHandler(back_add_to_freq_type, pattern="^back_add_to_freq_type$"),
            ],
            FREQ_TYPE_B: [
                CallbackQueryHandler(choose_freq_type_b, pattern="^freqb:"),
                CallbackQueryHandler(back_add_to_meal, pattern="^back_add_to_meal$"),
            ],
            FREQ_INTERVAL_B: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_interval_b_days),
                CallbackQueryHandler(add_freq_interval_b_anchor, pattern="^freqb_anchor:"),
                CallbackQueryHandler(back_multi_to_freq_type_b, pattern="^back_multi_to_freq_type_b$"),
            ],
            FREQ_WEEKDAYS_B: [
                CallbackQueryHandler(toggle_weekday_b, pattern="^weekdayb:\\d+$"),
                CallbackQueryHandler(confirm_weekdays_b, pattern="^weekdaysb_confirm$"),
                CallbackQueryHandler(back_multi_to_freq_type_b, pattern="^back_multi_to_freq_type_b$"),
            ],
            FREQ_MONTHDAY_B: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_monthday_b),
                CallbackQueryHandler(back_multi_to_freq_type_b, pattern="^back_multi_to_freq_type_b$"),
            ],
        },
        fallbacks=[
            cancel_handler,
            CallbackQueryHandler(cancel_add, pattern="^cancel_add$"),
        ],
    )


def get_edit_handler(cancel_handler):
    """Возвращает ConversationHandler для редактирования лекарства (включая multi-dosage флоу)."""
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_edit_select, pattern="^edit:\\d+$")],
        states={
            EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name),
                CallbackQueryHandler(keep_edit_name, pattern="^keep_edit_name$"),
            ],
            EDIT_DOSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_dosage),
                CallbackQueryHandler(keep_edit_dosage, pattern="^keep_edit_dosage$"),
                CallbackQueryHandler(back_edit_to_name, pattern="^back_edit_to_name$"),
            ],
            EDIT_DOSAGE_B: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_dosage_b),
                CallbackQueryHandler(keep_edit_dosage_b, pattern="^keep_edit_dosage_b$"),
                CallbackQueryHandler(back_edit_to_dosage, pattern="^back_edit_to_dosage$"),
            ],
            EDIT_FREQ_TYPE: [
                CallbackQueryHandler(keep_edit_schedule, pattern="^keep_edit_schedule$"),
                CallbackQueryHandler(choose_edit_freq_type, pattern="^editfreq:"),
                CallbackQueryHandler(handle_multi_edit_change_schedule, pattern="^multi_edit_change_schedule$"),
                CallbackQueryHandler(back_edit_to_dosage, pattern="^back_edit_to_dosage$"),
                CallbackQueryHandler(back_edit_to_meal, pattern="^back_edit_to_meal$"),
            ],
            EDIT_TIMES: [
                CallbackQueryHandler(edit_timeslot_toggle, pattern="^edittimeslot:"),
                CallbackQueryHandler(edit_timeslots_confirm, pattern="^edit_timeslots_confirm$"),
                CallbackQueryHandler(back_edit_to_freq_type, pattern="^back_edit_to_freq_type$"),
            ],
            EDIT_MEAL: [
                CallbackQueryHandler(edit_meal, pattern="^editmeal:"),
                CallbackQueryHandler(keep_edit_meal, pattern="^keep_edit_meal$"),
                CallbackQueryHandler(back_edit_to_times, pattern="^back_edit_to_times$"),
                CallbackQueryHandler(back_edit_to_dosage_b, pattern="^back_edit_to_dosage_b$"),
            ],
            EDIT_FREQ_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_freq_interval),
                CallbackQueryHandler(back_edit_to_meal, pattern="^back_edit_to_meal$"),
            ],
            EDIT_FREQ_WEEKDAYS: [
                CallbackQueryHandler(toggle_edit_weekday, pattern="^editweekday:\\d+$"),
                CallbackQueryHandler(confirm_edit_weekdays, pattern="^edit_weekdays_confirm$"),
                CallbackQueryHandler(back_edit_to_meal, pattern="^back_edit_to_meal$"),
            ],
            EDIT_FREQ_MONTHDAY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_freq_monthday),
                CallbackQueryHandler(back_edit_to_meal, pattern="^back_edit_to_meal$"),
            ],
            # States for multi-dosage schedule change (reuses add-flow handlers)
            TIMES: [
                CallbackQueryHandler(add_timeslot_toggle, pattern="^timeslot:"),
                CallbackQueryHandler(add_timeslots_confirm, pattern="^timeslots_confirm$"),
                CallbackQueryHandler(back_edit_to_freq_type, pattern="^back_edit_to_freq_type$"),
            ],
            TIMES_B: [
                CallbackQueryHandler(add_timeslot_b_toggle, pattern="^timeslotb:"),
                CallbackQueryHandler(add_timeslots_b_confirm, pattern="^timeslotsb_confirm$"),
                CallbackQueryHandler(back_multi_to_times_a, pattern="^back_multi_to_times_a$"),
            ],
            MEAL: [
                CallbackQueryHandler(add_meal, pattern="^(before|after|with|any)$"),
                CallbackQueryHandler(back_add_to_times, pattern="^back_add_to_times$"),
            ],
            FREQ_TYPE: [
                CallbackQueryHandler(choose_freq_type, pattern="^freq:"),
                CallbackQueryHandler(back_add_to_meal, pattern="^back_add_to_meal$"),
            ],
            FREQ_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_interval),
                CallbackQueryHandler(back_add_to_freq_type, pattern="^back_add_to_freq_type$"),
            ],
            FREQ_WEEKDAYS: [
                CallbackQueryHandler(toggle_weekday, pattern="^weekday:\\d+$"),
                CallbackQueryHandler(confirm_weekdays, pattern="^weekdays_confirm$"),
                CallbackQueryHandler(back_add_to_freq_type, pattern="^back_add_to_freq_type$"),
            ],
            FREQ_MONTHDAY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_monthday),
                CallbackQueryHandler(back_add_to_freq_type, pattern="^back_add_to_freq_type$"),
            ],
            FREQ_TYPE_B: [
                CallbackQueryHandler(choose_freq_type_b, pattern="^freqb:"),
                CallbackQueryHandler(back_add_to_meal, pattern="^back_add_to_meal$"),
            ],
            FREQ_INTERVAL_B: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_interval_b_days),
                CallbackQueryHandler(add_freq_interval_b_anchor, pattern="^freqb_anchor:"),
                CallbackQueryHandler(back_multi_to_freq_type_b, pattern="^back_multi_to_freq_type_b$"),
            ],
            FREQ_WEEKDAYS_B: [
                CallbackQueryHandler(toggle_weekday_b, pattern="^weekdayb:\\d+$"),
                CallbackQueryHandler(confirm_weekdays_b, pattern="^weekdaysb_confirm$"),
                CallbackQueryHandler(back_multi_to_freq_type_b, pattern="^back_multi_to_freq_type_b$"),
            ],
            FREQ_MONTHDAY_B: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_freq_monthday_b),
                CallbackQueryHandler(back_multi_to_freq_type_b, pattern="^back_multi_to_freq_type_b$"),
            ],
        },
        fallbacks=[
            cancel_handler,
            CallbackQueryHandler(cancel_add, pattern="^cancel_add$"),
        ],
    )
