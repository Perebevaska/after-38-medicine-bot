from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from database import get_or_create_user, get_today_stats, get_history_detailed
from constants import MONTHS_GEN, MONTHS_SHORT
from utils import handle_db_errors, get_tz_for_user


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 За сегодня", callback_data="stats:today"),
        InlineKeyboardButton("📈 За 7 дней", callback_data="stats:week"),
    ]])
    await update.message.reply_text("Выбери период:", reply_markup=keyboard)


@handle_db_errors
async def show_stats_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        key = f"{r['name']} {r['dosage']}"
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
        await query.edit_message_text("За последние 7 дней нет данных.")
        return

    meds = OrderedDict()
    meds_totals = defaultdict(lambda: {"taken": 0, "total": 0})

    for r in rows:
        key = f"{r['name']} {r['dosage']}"
        utc_dt = datetime.strptime(r["taken_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.utc)
        local_dt = utc_dt.astimezone(user_tz)
        day_str = f"{local_dt.day} {MONTHS_SHORT[local_dt.month-1]}"
        time_str = local_dt.strftime("%H:%M")

        icon = "✅" if r["status"] == "taken" else "❌"

        if key not in meds:
            meds[key] = OrderedDict()
        if day_str not in meds[key]:
            meds[key][day_str] = []
        meds[key][day_str].append(f"{time_str} {icon}")

        meds_totals[key]["total"] += 1
        if r["status"] == "taken":
            meds_totals[key]["taken"] += 1

    blocks = ["📈 <b>История за 7 дней</b>\n"]
    for med_name, days_dict in meds.items():
        taken = meds_totals[med_name]["taken"]
        total = meds_totals[med_name]["total"]
        pct = int(taken / total * 100) if total else 0
        color = "🟢" if pct >= 80 else ("🟡" if pct >= 50 else "🔴")

        blocks.append(f"💊 <b>{med_name}</b> — {pct}% {color}\n")
        for day_str, intakes in days_dict.items():
            intakes_str = "  ".join(intakes)
            blocks.append(f"{day_str}  {intakes_str}")
        blocks.append(f"\n<i>Итого: {taken}/{total} ({pct}%)</i>")
        blocks.append("──────────────────")

    await query.edit_message_text("\n".join(blocks), parse_mode="HTML")


def get_handlers():
    return [
        CallbackQueryHandler(show_stats_today, pattern="^stats:today$"),
        CallbackQueryHandler(show_stats_week, pattern="^stats:week$"),
    ]
