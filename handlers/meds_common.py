import logging
from datetime import date, timedelta, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_or_create_user, get_user_medications, get_rules_grouped_for_user
from schedule_utils import days_of_stock_left
from constants import MEAL_LABELS, MAX_MEDICATIONS_PER_USER, SLOT_ORDER, SLOT_LABELS, MONTHS_SHORT
from utils import handle_db_errors, get_tz_for_user, escape_html, NAME_MAX_LEN, DOSAGE_MAX_LEN

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
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data=back_cb),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_add"),
    ]])


def _freq_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Каждый день", callback_data="freq:daily")],
        [InlineKeyboardButton("🔄 Каждый N день", callback_data="freq:interval")],
        [InlineKeyboardButton("📆 По дням недели", callback_data="freq:weekdays")],
        [InlineKeyboardButton("🗓 Раз в месяц", callback_data="freq:monthly")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_meal"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _freq_type_b_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Каждый день", callback_data="freqb:daily")],
        [InlineKeyboardButton("🔄 Каждый N день", callback_data="freqb:interval")],
        [InlineKeyboardButton("📆 По дням недели", callback_data="freqb:weekdays")],
        [InlineKeyboardButton("🗓 Раз в месяц", callback_data="freqb:monthly")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_meal"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _edit_freq_type_keyboard() -> InlineKeyboardMarkup:
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Сохранить без изменений", callback_data="keep_edit_schedule")],
        [InlineKeyboardButton("🔄 Изменить расписание", callback_data="multi_edit_change_schedule")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_meal"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
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
        [InlineKeyboardButton("◀️ Назад", callback_data="back_add_to_freq_type"),
         InlineKeyboardButton("✔️ Готово", callback_data="weekdays_confirm"),
         InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")],
    ])


def _weekdays_b_keyboard(selected: set) -> InlineKeyboardMarkup:
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
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"➡️ Оставить ({current_label})", callback_data="keep_edit_meal")]]
        + [[InlineKeyboardButton(label, callback_data=f"editmeal:{key}")] for key, label in MEAL_LABELS.items()]
        + [[InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_times"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]]
    )


def _edit_meal_keyboard_multi(current_label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"➡️ Оставить ({current_label})", callback_data="keep_edit_meal")]]
        + [[InlineKeyboardButton(label, callback_data=f"editmeal:{key}")] for key, label in MEAL_LABELS.items()]
        + [[InlineKeyboardButton("◀️ Назад", callback_data="back_edit_to_dosage_b"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]]
    )


def _timeslots_keyboard(selected: set, presets: dict, back_cb: str = "back_add_to_dosage") -> InlineKeyboardMarkup:
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


# ── Formatters ─────────────────────────────────────────────────────────────

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


def _current_schedule_summary(rules: list) -> str:
    if not rules:
        return "не указано"
    has_adv = any(r["frequency"] != "daily" for r in rules)
    if not has_adv:
        times = ", ".join(r["reminder_time"] for r in rules)
        return f"{times} (каждый день)"
    return " | ".join(_format_schedule_rule(r) for r in rules)


def _monthday_warning(day: int) -> str:
    if day == 29:
        return "\n\n⚠️ В феврале невисокосного года напоминание не сработает."
    if day == 30:
        return "\n\n⚠️ В феврале напоминание не сработает."
    if day == 31:
        return "\n\n⚠️ В феврале, апреле, июне, сентябре и ноябре напоминание не сработает."
    return ""


def _med_saved_text(action: str, name: str, dosage: str, meal: str,
                    total: int, times: list, freq_suffix: str = "", warning: str = "") -> str:
    return (
        f"✅ Лекарство {action}!\n\n"
        f"💊 {name} — {dosage}\n"
        f"🍽 {MEAL_LABELS[meal]}\n"
        f"🔢 {total} раз в день\n"
        f"⏰ {', '.join(times)}{freq_suffix}{warning}"
    )


def _parse_int_range(text: str, lo: int, hi: int):
    try:
        n = int(text.strip())
    except (ValueError, TypeError, AttributeError):
        return None
    return n if lo <= n <= hi else None


def _saved_keyboard(med_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Указать запас", callback_data=f"stock:{med_id}")],
        [InlineKeyboardButton("◀️ В меню", callback_data="menu:main")],
    ])


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


def _dosage_a_summary(ud: dict) -> str:
    dosage_a = ud.get("dosage", "")
    times_a = ud.get("collected_times", [])
    freq_a = ud.get("freq_a", {})
    times_str = ", ".join(times_a) if times_a else "—"
    summary = f"📋 Дозировка А: <b>{escape_html(dosage_a)}</b> — {times_str}"
    if freq_a:
        freq_str = _freq_label(
            freq_a.get("type", "daily"),
            freq_a.get("interval_days"),
            freq_a.get("weekdays"),
            freq_a.get("month_day"),
        )
        summary += f" ({freq_str})"
    return summary


# ── Next-fire helpers ──────────────────────────────────────────────────────

def _compute_next_fire(rule, today: date):
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

def _med_card_text(med, rules, today_local) -> str:
    has_advanced = any(r["frequency"] != "daily" for r in rules)
    is_multi_dosage = any(r["dosage"] for r in rules)

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
            rule_strs.append(f"⏰ {_format_schedule_rule(r)} — {escape_html(effective)}{label}")
        schedule_str = "\n".join(rule_strs) or "не указано"
    elif not has_advanced:
        schedule_str = ", ".join(r["reminder_time"] for r in rules) or "не указано"
    else:
        schedule_str = "\n".join(_format_schedule_rule(r) for r in rules) or "не указано"

    meal = MEAL_LABELS.get(med["meal_relation"], med["meal_relation"])
    dep_label = f" <i>({escape_html(med['dependent_name'])})</i>" if med["dependent_name"] else ""
    paused_mark = "  ⏸ <i>на паузе</i>" if med["paused"] else ""
    text = (
        f"<b>{escape_html(med['name'])}</b>{dep_label} — {escape_html(dosage_display)}{paused_mark}\n"
        f"🍽 {meal}\n"
    )
    if not has_advanced and not is_multi_dosage:
        text += f"🔢 {med['times_per_day']} раз в день\n"
    if is_multi_dosage:
        text += schedule_str
    else:
        text += f"⏰ {schedule_str}"
    if med["stock_qty"] is not None:
        dleft = days_of_stock_left(rules, med["stock_qty"], med["units_per_dose"], today_local)
        low = dleft is not None and dleft <= (med["low_stock_days"] or 5)
        line = f"\n{'⚠️' if low else '📦'} Запас: {med['stock_qty']:g} шт."
        if dleft is not None:
            line += f" (~{dleft} дн.)"
        text += line
    return text


def _med_card_keyboard(med_id: int, paused: bool, *, is_last: bool = False,
                       with_menu: bool = False) -> InlineKeyboardMarkup:
    pause_btn = (InlineKeyboardButton("▶️ Возобновить", callback_data=f"med_resume:{med_id}")
                 if paused else
                 InlineKeyboardButton("⏸ Пауза", callback_data=f"med_pause:{med_id}"))
    rows = [
        [InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{med_id}"),
         InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{med_id}")],
        [InlineKeyboardButton("📦 Запас", callback_data=f"stock:{med_id}"), pause_btn],
    ]
    if is_last:
        rows.append([InlineKeyboardButton("➕ Добавить лекарство", callback_data="add_med")])
        rows.append([InlineKeyboardButton("◀️ В меню", callback_data="menu:main")])
    elif with_menu:
        rows.append([InlineKeyboardButton("◀️ В меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


async def show_meds_list(message, user):
    user_id = get_or_create_user(user.id, user.username)
    meds = get_user_medications(user_id)
    user_tz = get_tz_for_user(user.id)
    today_local = datetime.now(user_tz).date()

    if not meds:
        await message.reply_text(
            "У тебя пока нет лекарств.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить лекарство", callback_data="add_med")],
                [InlineKeyboardButton("◀️ В меню", callback_data="menu:main")],
            ])
        )
        return

    rules_by_med = get_rules_grouped_for_user(user_id)
    await message.reply_text("💊 Твои лекарства:")
    last_idx = len(meds) - 1
    for i, med in enumerate(meds):
        rules = rules_by_med.get(med["id"], [])
        text = _med_card_text(med, rules, today_local)
        keyboard = _med_card_keyboard(med["id"], bool(med["paused"]), is_last=(i == last_idx))
        await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


@handle_db_errors
async def meds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_meds_list(update.message, update.effective_user)


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Отменено.")
    from telegram.ext import ConversationHandler
    return ConversationHandler.END
