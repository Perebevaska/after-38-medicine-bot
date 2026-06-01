from collections import OrderedDict
from datetime import datetime, timedelta, date
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from database import (get_or_create_user, get_today_stats, get_history_detailed,
                      get_schedules_for_user, get_adherence_rules, get_taken_counts,
                      get_streak_rows, get_intake_statuses_window)
from constants import MONTHS_GEN, MONTHS_SHORT
from utils import handle_db_errors, get_tz_for_user, escape_html
from scheduler import _rule_fires_today
from schedule_utils import count_due_by_medication
from streak import streak_window, streaks_by_subject

_WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_ADHERENCE_DAYS = 30


def _pct_color(pct: int) -> str:
    """Цветовой индикатор соблюдения: 🟢 ≥80% / 🟡 ≥50% / 🔴 иначе."""
    return "🟢" if pct >= 80 else ("🟡" if pct >= 50 else "🔴")


def _stats_period_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора периода статистики с возвратом в меню."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 За 7 дней", callback_data="stats:week")],
        [InlineKeyboardButton("📆 План на 7 дней", callback_data="stats:plan")],
        [InlineKeyboardButton("🔥 Серия", callback_data="stats:streak")],
        [InlineKeyboardButton("📊 Соблюдение за 30 дней", callback_data="stats:adherence")],
        [InlineKeyboardButton("◀️ В меню", callback_data="menu:main")],
    ])


def _plural_days(n: int) -> str:
    """Русское склонение слова «день» для числа n."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "день"
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return "дня"
    return "дней"


def _streak_phrase(n: int) -> str:
    """Мотивирующая фраза о серии: 🔥 N дней подряд + майлстоун-значок (7→⭐, 30→🏆)."""
    if n <= 0:
        return "пока нет серии — начни сегодня!"
    phrase = f"🔥 {n} {_plural_days(n)} подряд"
    if n >= 30:
        phrase += " 🏆"
    elif n >= 7:
        phrase += " ⭐"
    return phrase


def _report_keyboard(export_cb: str) -> InlineKeyboardMarkup:
    """Клавиатура под отчётом: скачать PDF + назад к выбору периода + в меню."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Скачать PDF", callback_data=export_cb)],
        [InlineKeyboardButton("◀️ Период", callback_data="menu:stats"),
         InlineKeyboardButton("🏠 В меню", callback_data="menu:main")],
    ])


def _adherence_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура под экраном соблюдения: PDF-отчёт для врача (календарь) + навигация."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🩺 Отчёт для врача (PDF)", callback_data="export:doctor")],
        [InlineKeyboardButton("◀️ Период", callback_data="menu:stats"),
         InlineKeyboardButton("🏠 В меню", callback_data="menu:main")],
    ])


def _nav_keyboard() -> InlineKeyboardMarkup:
    """Навигация под пустым отчётом: к выбору периода + в меню."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Период", callback_data="menu:stats"),
        InlineKeyboardButton("🏠 В меню", callback_data="menu:main"),
    ]])


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /stats: показывает выбор периода статистики."""
    await update.message.reply_text("Выбери период:", reply_markup=_stats_period_keyboard())


@handle_db_errors
async def show_stats_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику приёмов за сегодня с процентом выполнения."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    user_tz = get_tz_for_user(user.id)
    now = datetime.now(user_tz)
    day_start = user_tz.localize(datetime(now.year, now.month, now.day))
    day_start_utc = day_start.astimezone(pytz.utc)
    day_end_utc = day_start_utc + timedelta(days=1)
    rows = get_today_stats(
        user_id,
        day_start_utc.strftime("%Y-%m-%d %H:%M:%S"),
        day_end_utc.strftime("%Y-%m-%d %H:%M:%S"),
    )

    if not rows:
        await query.edit_message_text("За сегодня нет записей о приёмах.")
        return
    today_str = f"{now.day} {MONTHS_GEN[now.month]}"

    meds = OrderedDict()
    total_taken = 0
    total_all = 0

    for r in rows:
        key = f"{escape_html(r['name'])} {escape_html(r['dosage'])}"
        t = r["taken_at"] or r["scheduled_time"]
        if len(t) > 10:
            utc_dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.utc)
            time_str = utc_dt.astimezone(user_tz).strftime("%H:%M")
        else:
            time_str = t if ":" in t else t + ":00"

        icon = "✅" if r["status"] == "taken" else "❌"
        if key not in meds:
            meds[key] = {"intakes": [], "taken": 0, "total": 0}
        meds[key]["intakes"].append(f"{time_str} {icon}")
        meds[key]["total"] += 1
        if r["status"] == "taken":
            meds[key]["taken"] += 1
            total_taken += 1
        total_all += 1

    blocks = [f"📊 <b>Сегодня, {today_str}</b>\n"]
    for med_name, data in meds.items():
        pct = int(data["taken"] / data["total"] * 100) if data["total"] else 0
        color = "🟢" if pct >= 80 else ("🟡" if pct >= 50 else "🔴")
        intakes_str = "  ".join(data["intakes"])
        blocks.append(f"💊 <b>{med_name}</b> — {pct}% {color}")
        blocks.append(f"{intakes_str}\n")

    day_pct = int(total_taken / total_all * 100) if total_all else 0
    day_color = "🟢" if day_pct >= 80 else ("🟡" if day_pct >= 50 else "🔴")
    blocks.append("──────────────────")
    blocks.append(f"<b>Итог дня: {total_taken}/{total_all} ({day_pct}%) {day_color}</b>")

    await query.edit_message_text("\n".join(blocks), parse_mode="HTML")


@handle_db_errors
async def show_stats_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную историю приёмов за последние 7 дней с кнопкой PDF."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    user_tz = get_tz_for_user(user.id)
    now = datetime.now(user_tz)
    week_start = now - timedelta(days=7)
    since_day = user_tz.localize(datetime(week_start.year, week_start.month, week_start.day))
    since_utc = since_day.astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = get_history_detailed(user_id, since_utc)

    if not rows:
        await query.edit_message_text("За последние 7 дней нет данных.", reply_markup=_nav_keyboard())
        return

    # day_str → {med_name → [intake_str, ...]}
    days: OrderedDict = OrderedDict()
    total_taken = 0
    total_all = 0

    for r in rows:
        dep_suffix = f" ({escape_html(r['dependent_name'])})" if r["dependent_name"] else ""
        med_key = f"{escape_html(r['name'])}{dep_suffix} {escape_html(r['dosage'])}"
        utc_dt = datetime.strptime(r["taken_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.utc)
        local_dt = utc_dt.astimezone(user_tz)
        day_str = f"{local_dt.day} {MONTHS_SHORT[local_dt.month - 1]}"
        time_str = local_dt.strftime("%H:%M")
        icon = "✅" if r["status"] == "taken" else "❌"

        if day_str not in days:
            days[day_str] = OrderedDict()
        if med_key not in days[day_str]:
            days[day_str][med_key] = []
        days[day_str][med_key].append(f"{time_str} {icon}")

        total_all += 1
        if r["status"] == "taken":
            total_taken += 1

    blocks = ["📈 <b>История за 7 дней</b>\n"]
    for day_str, meds_dict in days.items():
        blocks.append(f"📅 <b>{day_str}</b>")
        for med_name, intakes in meds_dict.items():
            blocks.append(f"  {med_name}:  {'  '.join(intakes)}")
        blocks.append("")

    pct = int(total_taken / total_all * 100) if total_all else 0
    color = "🟢" if pct >= 80 else ("🟡" if pct >= 50 else "🔴")
    blocks.append("──────────────────")
    blocks.append(f"<b>Итог за 7 дней: {total_taken}/{total_all} ({pct}%) {color}</b>")

    text = "\n".join(blocks)
    if len(text) > 4000:
        text = text[:3900] + "\n\n⚠️ <i>Показаны не все данные — слишком большая история.</i>"
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=_report_keyboard("export:week"))


def adherence_window(user_tz):
    """Окно расчёта adherence: (today_local, start_day_local, start_utc, end_utc) за _ADHERENCE_DAYS дней."""
    today = datetime.now(user_tz).date()
    start_day = today - timedelta(days=_ADHERENCE_DAYS - 1)
    start_local = user_tz.localize(datetime(start_day.year, start_day.month, start_day.day))
    end_local = user_tz.localize(datetime(today.year, today.month, today.day)) + timedelta(days=1)
    start_utc = start_local.astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_utc = end_local.astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")
    return today, start_day, start_utc, end_utc


def compute_adherence(rules, taken: dict, start_day, today, user_tz):
    """Считает соблюдение по лекарствам. Возвращает (items, total_taken, total_planned).

    items — список dict {pct, taken, due, name, dep, mid}, отсортирован «худшие сверху».
    name/dep — сырые (без экранирования): рендер сам экранирует под HTML/PDF.
    Знаменатель — положенные приёмы по расписанию с клампом по created_at каждого лекарства.
    """
    meta: dict = {}
    created_dates: dict = {}
    for r in rules:
        mid = r["medication_id"]
        if mid in meta:
            continue
        try:
            cd = (datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
                  .replace(tzinfo=pytz.utc).astimezone(user_tz).date())
        except (ValueError, TypeError):
            cd = start_day
        created_dates[mid] = cd
        meta[mid] = {"name": r["name"], "dep": r["dependent_name"]}

    planned = count_due_by_medication(rules, start_day, today, created_dates)
    items = []
    total_taken = 0
    total_planned = 0
    for mid, due in planned.items():
        if due <= 0:
            continue
        tk = taken.get(mid, 0)
        pct = min(100, round(tk / due * 100))
        total_taken += min(tk, due)
        total_planned += due
        items.append({"pct": pct, "taken": tk, "due": due,
                      "name": meta[mid]["name"], "dep": meta[mid]["dep"], "mid": mid})
    items.sort(key=lambda x: (x["pct"], x["mid"]))  # худшие сверху
    return items, total_taken, total_planned


@handle_db_errors
async def show_adherence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает процент соблюдения режима за 30 дней (F3): принято / положено по расписанию."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    user_tz = get_tz_for_user(user.id)

    rules = get_adherence_rules(user_id)
    if not rules:
        await query.edit_message_text(
            "💊 Нет активных лекарств для расчёта соблюдения.", reply_markup=_nav_keyboard()
        )
        return

    today, start_day, start_utc, end_utc = adherence_window(user_tz)
    taken = get_taken_counts(user_id, start_utc, end_utc)
    items, total_taken, total_planned = compute_adherence(rules, taken, start_day, today, user_tz)

    if not total_planned:
        await query.edit_message_text(
            "💊 За последние 30 дней не было запланированных приёмов.", reply_markup=_nav_keyboard()
        )
        return

    blocks = ["📊 <b>Соблюдение за 30 дней</b>\n"]
    for it in items:
        dep = f" ({escape_html(it['dep'])})" if it["dep"] else ""
        blocks.append(
            f"{_pct_color(it['pct'])} <b>{escape_html(it['name'])}</b>{dep} "
            f"— {it['pct']}% ({it['taken']}/{it['due']})"
        )

    overall = round(total_taken / total_planned * 100)
    blocks.append("\n──────────────────")
    blocks.append(f"<b>Итог: {total_taken}/{total_planned} ({overall}%) {_pct_color(overall)}</b>")

    await query.edit_message_text(
        "\n".join(blocks), parse_mode="HTML", reply_markup=_adherence_keyboard()
    )


@handle_db_errors
async def show_streak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает серию идеальных дней (F2) — отдельно для владельца и каждого подопечного."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    user_tz = get_tz_for_user(user.id)

    rows = get_streak_rows(user_id)
    if not rows:
        await query.edit_message_text(
            "🔥 Нет активных лекарств для подсчёта серии.", reply_markup=_nav_keyboard()
        )
        return

    today, start_utc, end_utc = streak_window(user_tz)
    intakes = get_intake_statuses_window(user_id, start_utc, end_utc)
    subjects = streaks_by_subject(rows, intakes, user_tz, today)

    blocks = ["🔥 <b>Серия идеальных дней</b>",
              "<i>Идеальный день — все приёмы за день отмечены ✅</i>\n"]
    for s in subjects:
        label = escape_html(s["name"]) if s["name"] else "Ты"
        blocks.append(f"💪 <b>{label}</b>: {_streak_phrase(s['streak'])}")

    await query.edit_message_text(
        "\n".join(blocks), parse_mode="HTML", reply_markup=_nav_keyboard()
    )


@handle_db_errors
async def show_week_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает план лекарств на ближайшие 7 дней с учётом frequency, с кнопкой PDF."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_tz = get_tz_for_user(user.id)
    today = datetime.now(user_tz).date()

    rows = get_schedules_for_user(user.id)
    if not rows:
        await query.edit_message_text("💊 Нет активных лекарств.", reply_markup=_nav_keyboard())
        return

    blocks = ["📆 <b>План на 7 дней</b>\n"]
    for offset in range(7):
        day = today + timedelta(days=offset)
        day_label = f"{day.day} {MONTHS_SHORT[day.month - 1]} ({_WEEKDAY_NAMES[day.weekday()]})"

        meds: dict = {}
        for row in rows:
            if not _rule_fires_today(row, day):
                continue
            mid = row["medication_id"]
            if mid not in meds:
                meds[mid] = {"name": row["name"], "dep_name": row["dependent_name"], "times": []}
            dosage = row["rule_dosage"] or row["med_dosage"]
            meds[mid]["times"].append((row["reminder_time"], dosage))

        if not meds:
            continue

        blocks.append(f"📅 <b>{day_label}</b>")
        for med in meds.values():
            times_str = "  ".join(
                f"{t} — {escape_html(d)}" for t, d in sorted(med["times"])
            )
            dep_label = f" <i>({escape_html(med['dep_name'])})</i>" if med["dep_name"] else ""
            blocks.append(f"  💊 {escape_html(med['name'])}{dep_label}: {times_str}")
        blocks.append("")

    if len(blocks) == 2:
        await query.edit_message_text(
            "💊 В ближайшие 7 дней нет запланированных лекарств.", reply_markup=_nav_keyboard()
        )
        return

    text = "\n".join(blocks).rstrip()
    if len(text) > 4000:
        text = text[:3900] + "\n\n⚠️ <i>Показаны не все данные.</i>"
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=_report_keyboard("export:plan"))


def get_handlers():
    """Возвращает список handlers для страниц статистики."""
    return [
        CallbackQueryHandler(show_stats_week, pattern="^stats:week$"),
        CallbackQueryHandler(show_adherence, pattern="^stats:adherence$"),
        CallbackQueryHandler(show_streak, pattern="^stats:streak$"),
        CallbackQueryHandler(show_week_plan, pattern="^stats:plan$"),
    ]
