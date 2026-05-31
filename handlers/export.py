import asyncio
import io
import pytz
from collections import OrderedDict
from datetime import datetime, timedelta
from fpdf import FPDF
from telegram.ext import CallbackQueryHandler

from database import get_schedules_for_user, get_history_detailed, get_or_create_user
from utils import get_tz_for_user, handle_db_errors
from constants import MONTHS_SHORT
from scheduler import _rule_fires_today, _MEAL_LABELS  # _MEAL_LABELS: строчные варианты для текста

_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _build_pdf(title: str, subtitle: str, sections: list[tuple[str, list[str]]]) -> io.BytesIO:
    """Генерирует PDF с кириллическим шрифтом DejaVuSans.

    sections: список (heading, [строка, ...]) — каждая группа выводится
    как выделенный заголовок на сером фоне + отступленные строки под ним.
    Возвращает BytesIO с готовым PDF.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", _FONT)
    pdf.add_font("DejaVu", "B", _FONT_BOLD)

    pdf.set_font("DejaVu", "B", 15)
    pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, subtitle, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    for heading, lines in sections:
        pdf.set_font("DejaVu", "B", 11)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(0, 7, heading, new_x="LMARGIN", new_y="NEXT", fill=True)
        pdf.set_font("DejaVu", "", 10)
        for line in lines:
            pdf.cell(6)  # indent
            pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


@handle_db_errors
async def export_week_plan(update, context):
    """Генерирует PDF-файл с планом лекарств на 7 дней и отправляет пользователю."""
    query = update.callback_query
    await query.answer("Генерирую PDF...")
    user = update.effective_user
    user_tz = get_tz_for_user(user.id)
    today = datetime.now(user_tz).date()
    rows = get_schedules_for_user(user.id)

    sections = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        day_label = f"{day.day} {MONTHS_SHORT[day.month - 1]} ({_WEEKDAY_NAMES[day.weekday()]})"
        meds: dict = {}
        for row in rows:
            if not _rule_fires_today(row, day):
                continue
            mid = row["medication_id"]
            if mid not in meds:
                meds[mid] = {"name": row["name"], "meal_relation": row["meal_relation"], "times": []}
            dosage = row["rule_dosage"] or row["med_dosage"]
            meds[mid]["times"].append((row["reminder_time"], dosage))
        if not meds:
            continue
        lines = []
        for med in meds.values():
            meal = _MEAL_LABELS.get(med["meal_relation"], "")
            for t, d in sorted(med["times"]):
                lines.append(f"{t}  {med['name']} — {d}  ({meal})")
        sections.append((day_label, lines))

    if not sections:
        await query.message.reply_text("Нет данных для экспорта.")
        return

    title = "План лекарств на 7 дней"
    subtitle = f"с {today.strftime('%d.%m.%Y')} по {(today + timedelta(days=6)).strftime('%d.%m.%Y')}"
    buf = await asyncio.to_thread(_build_pdf, title, subtitle, sections)
    filename = f"plan_{today.strftime('%Y%m%d')}.pdf"
    await query.message.reply_document(document=buf, filename=filename, caption="📆 План лекарств на 7 дней")


@handle_db_errors
async def export_week_stats(update, context):
    """Генерирует PDF-файл с историей приёмов за 7 дней и отправляет пользователю."""
    query = update.callback_query
    await query.answer("Генерирую PDF...")
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    user_tz = get_tz_for_user(user.id)
    now = datetime.now(user_tz)
    week_start = now - timedelta(days=7)
    since_day = user_tz.localize(datetime(week_start.year, week_start.month, week_start.day))
    since_utc = since_day.astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = get_history_detailed(user_id, since_utc)

    if not rows:
        await query.message.reply_text("Нет данных за последние 7 дней.")
        return

    days: OrderedDict = OrderedDict()
    total_taken = total_all = 0
    for r in rows:
        utc_dt = datetime.strptime(r["taken_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.utc)
        local_dt = utc_dt.astimezone(user_tz)
        day_str = f"{local_dt.day} {MONTHS_SHORT[local_dt.month - 1]} ({_WEEKDAY_NAMES[local_dt.weekday()]})"
        time_str = local_dt.strftime("%H:%M")
        status_str = "Принято" if r["status"] == "taken" else "Пропущено"
        if day_str not in days:
            days[day_str] = []
        days[day_str].append(f"{time_str}  {r['name']} {r['dosage']} — {status_str}")
        total_all += 1
        if r["status"] == "taken":
            total_taken += 1

    sections = [(day, lines) for day, lines in days.items()]
    pct = int(total_taken / total_all * 100) if total_all else 0
    sections.append((f"Итого: {total_taken}/{total_all} ({pct}%)", []))

    title = "История приёмов за 7 дней"
    subtitle = f"до {now.strftime('%d.%m.%Y')}"
    buf = await asyncio.to_thread(_build_pdf, title, subtitle, sections)
    filename = f"history_{now.strftime('%Y%m%d')}.pdf"
    await query.message.reply_document(document=buf, filename=filename, caption="📈 История приёмов за 7 дней")


def get_handlers():
    """Возвращает handlers для экспорта в PDF (план и история)."""
    return [
        CallbackQueryHandler(export_week_plan, pattern="^export:plan$"),
        CallbackQueryHandler(export_week_stats, pattern="^export:week$"),
    ]
