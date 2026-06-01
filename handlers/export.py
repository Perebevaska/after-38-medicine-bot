import asyncio
import io
import pytz
from collections import OrderedDict
from datetime import datetime, timedelta
from fpdf import FPDF
from telegram.ext import CallbackQueryHandler

from database import (get_schedules_for_user, get_history_detailed, get_or_create_user,
                      get_adherence_rules, get_taken_counts, get_taken_intakes)
from utils import get_tz_for_user, handle_db_errors
from constants import MONTHS_SHORT
from scheduler import _rule_fires_today, _MEAL_LABELS  # _MEAL_LABELS: строчные варианты для текста
from schedule_utils import due_by_med_day
from handlers.stats import adherence_window, compute_adherence

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
                meds[mid] = {"name": row["name"], "meal_relation": row["meal_relation"],
                             "dep_name": row["dependent_name"], "times": []}
            dosage = row["rule_dosage"] or row["med_dosage"]
            meds[mid]["times"].append((row["reminder_time"], dosage))
        if not meds:
            continue
        lines = []
        for med in meds.values():
            meal = _MEAL_LABELS.get(med["meal_relation"], "")
            dep_label = f" ({med['dep_name']})" if med["dep_name"] else ""
            for t, d in sorted(med["times"]):
                lines.append(f"{t}  {med['name']}{dep_label} — {d}  ({meal})")
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
        dep_suffix = f" ({r['dependent_name']})" if r["dependent_name"] else ""
        days[day_str].append(f"{time_str}  {r['name']}{dep_suffix} {r['dosage']} — {status_str}")
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


@handle_db_errors
async def export_adherence(update, context):
    """Генерирует PDF-отчёт о соблюдении режима за 30 дней (F3) и отправляет пользователю."""
    query = update.callback_query
    await query.answer("Генерирую PDF...")
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    user_tz = get_tz_for_user(user.id)

    rules = get_adherence_rules(user_id)
    if not rules:
        await query.message.reply_text("Нет активных лекарств для отчёта.")
        return

    today, start_day, start_utc, end_utc = adherence_window(user_tz)
    taken = get_taken_counts(user_id, start_utc, end_utc)
    items, total_taken, total_planned = compute_adherence(rules, taken, start_day, today, user_tz)

    if not total_planned:
        await query.message.reply_text("За последние 30 дней нет запланированных приёмов.")
        return

    lines = []
    for it in items:
        dep = f" ({it['dep']})" if it["dep"] else ""
        lines.append(f"{it['name']}{dep} — {it['pct']}%  ({it['taken']}/{it['due']})")

    overall = round(total_taken / total_planned * 100)
    sections = [
        ("Соблюдение по лекарствам", lines),
        (f"Итого: {total_taken}/{total_planned} ({overall}%)", []),
    ]
    title = "Соблюдение режима за 30 дней"
    subtitle = f"с {start_day.strftime('%d.%m.%Y')} по {today.strftime('%d.%m.%Y')}"
    buf = await asyncio.to_thread(_build_pdf, title, subtitle, sections)
    filename = f"adherence_{today.strftime('%Y%m%d')}.pdf"
    await query.message.reply_document(
        document=buf, filename=filename, caption="📊 Соблюдение режима за 30 дней"
    )


# ── Отчёт для врача: календарь приверженности за 30 дней (F1) ────────────────

_CAL_WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _day_bg(pct):
    """Пастельный фон ячейки дня по приверженности: ≥90 зелёный / ≥50 жёлтый / <50 красный / None серый."""
    if pct is None:
        return (236, 236, 236)
    if pct >= 90:
        return (206, 238, 206)
    if pct >= 50:
        return (250, 242, 198)
    return (250, 212, 212)


def _dot_color(taken: int, sched: int):
    """Цвет кружка лекарства в дне: всё принято — зелёный, ничего — красный, частично — оранжевый."""
    if taken >= sched:
        return (40, 170, 80)
    if taken <= 0:
        return (210, 60, 60)
    return (230, 160, 40)


def _prepare_doctor_model(rules, taken_rows, user_tz, start_day, today, user_label):
    """Готовит данные отчёта врача: по одному «субъекту» (пациент + каждый подопечный).

    Возвращает (subjects, days). subject: {label, mids, names, due, taken, day_pct, summary, overall}.
    due/taken — {(mid, date): count}; day_pct — {date: %|None}.
    """
    meta, created = {}, {}
    groups = OrderedDict()  # dependent_name | None -> [rules]
    for r in rules:
        mid = r["medication_id"]
        if mid not in meta:
            try:
                cd = (datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
                      .replace(tzinfo=pytz.utc).astimezone(user_tz).date())
            except (ValueError, TypeError):
                cd = start_day
            created[mid] = cd
            meta[mid] = r["name"]
        groups.setdefault(r["dependent_name"], []).append(r)

    taken = {}
    for row in taken_rows:
        try:
            ld = (datetime.strptime(row["taken_at"], "%Y-%m-%d %H:%M:%S")
                  .replace(tzinfo=pytz.utc).astimezone(user_tz).date())
        except (ValueError, TypeError):
            continue
        taken[(row["mid"], ld)] = taken.get((row["mid"], ld), 0) + 1

    days = []
    d = start_day
    while d <= today:
        days.append(d)
        d += timedelta(days=1)

    subjects = []
    for dep_name, grp_rules in groups.items():
        due = due_by_med_day(grp_rules, start_day, today, created)
        mids = sorted({r["medication_id"] for r in grp_rules})
        day_pct = {}
        for day in days:
            sched = sum(due.get((mid, day), 0) for mid in mids)
            tk = sum(min(taken.get((mid, day), 0), due.get((mid, day), 0)) for mid in mids)
            day_pct[day] = round(tk / sched * 100) if sched else None

        summary, tot_t, tot_s = [], 0, 0
        for mid in mids:
            s = sum(due.get((mid, day), 0) for day in days)
            if s == 0:
                continue
            t = sum(min(taken.get((mid, day), 0), due.get((mid, day), 0)) for day in days)
            summary.append((meta[mid], round(t / s * 100)))
            tot_t += t
            tot_s += s
        if tot_s == 0:
            continue  # у субъекта нет положенных приёмов за период — страницу не рисуем
        subjects.append({
            "label": f"Пациент: {user_label}" if dep_name is None else f"Подопечный: {dep_name}",
            "mids": mids, "names": meta, "due": due, "taken": taken,
            "day_pct": day_pct, "summary": summary, "overall": round(tot_t / tot_s * 100),
        })
    return subjects, days


def _render_subject_page(pdf, subj, days, start_day, today, period_str, gen_str):
    """Рисует одну альбомную страницу-календарь для субъекта (пациента/подопечного)."""
    M = 10.0
    pdf.add_page()

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DejaVu", "B", 16)
    pdf.set_xy(M, 8)
    pdf.cell(0, 8, "Отчёт для врача — приверженность лечению")

    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.set_xy(M, 17)
    pdf.cell(0, 5, f"{subj['label']}  ·  период {period_str}  ·  сформирован {gen_str}")

    pdf.set_text_color(40, 40, 40)
    pdf.set_font("DejaVu", "", 9)
    parts = [f"{name} {pct}%" for name, pct in subj["summary"]]
    summary_line = "   ".join(parts) + f"     ИТОГ: {subj['overall']}%"
    pdf.set_xy(M, 23)
    pdf.cell(0, 5, summary_line[:170])

    # легенда порогов — цветные квадраты
    lx, ly = M, 29.5
    for color, label in [((206, 238, 206), "≥90%"), ((250, 242, 198), "50–90%"),
                         ((250, 212, 212), "<50%")]:
        pdf.set_fill_color(*color)
        pdf.set_draw_color(180, 180, 180)
        pdf.rect(lx, ly, 4, 4, style="DF")
        pdf.set_xy(lx + 5, ly - 0.5)
        pdf.set_font("DejaVu", "", 8)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(16, 5, label)
        lx += 24
    pdf.set_xy(lx + 4, ly - 0.5)
    pdf.cell(0, 5, "кружок: зелёный — принято, красный — пропущено, оранжевый — частично")

    # сетка календаря
    PAGE_W = 297.0
    col_w = (PAGE_W - 2 * M) / 7
    grid_top = 38.0
    hdr_h = 6.0

    first_monday = start_day - timedelta(days=start_day.isoweekday() - 1)
    last_sunday = today + timedelta(days=7 - today.isoweekday())
    n_weeks = ((last_sunday - first_monday).days + 1) // 7
    grid_avail = 210.0 - grid_top - hdr_h - M
    row_h = min(27.0, grid_avail / max(n_weeks, 1))

    # шапка дней недели
    pdf.set_font("DejaVu", "B", 8)
    pdf.set_text_color(255, 255, 255)
    pdf.set_fill_color(90, 110, 140)
    for col, wd in enumerate(_CAL_WEEKDAYS):
        pdf.set_xy(M + col * col_w, grid_top)
        pdf.cell(col_w, hdr_h, wd, align="C", fill=True)

    max_lines = max(1, int((row_h - 5.5) // 3.4))
    for week in range(n_weeks):
        for col in range(7):
            day = first_monday + timedelta(days=week * 7 + col)
            x = M + col * col_w
            y = grid_top + hdr_h + week * row_h
            in_range = start_day <= day <= today
            pct = subj["day_pct"].get(day) if in_range else None

            pdf.set_fill_color(*(_day_bg(pct) if in_range else (247, 247, 247)))
            pdf.set_draw_color(185, 185, 185)
            pdf.rect(x, y, col_w, row_h, style="DF")

            pdf.set_xy(x + 1.2, y + 1)
            pdf.set_font("DejaVu", "B", 8)
            pdf.set_text_color(70, 70, 70) if in_range else pdf.set_text_color(180, 180, 180)
            pdf.cell(12, 4, str(day.day))
            if pct is not None:
                pdf.set_xy(x + col_w - 15, y + 1)
                pdf.set_font("DejaVu", "", 7)
                pdf.set_text_color(70, 70, 70)
                pdf.cell(14, 4, f"{pct}%", align="R")

            if not in_range:
                continue
            yy = y + 5.5
            shown = 0
            for mid in subj["mids"]:
                sched = subj["due"].get((mid, day), 0)
                if sched == 0:
                    continue
                if shown >= max_lines:
                    pdf.set_xy(x + 1.5, yy)
                    pdf.set_font("DejaVu", "", 6)
                    pdf.set_text_color(90, 90, 90)
                    pdf.cell(col_w - 3, 3, "…")
                    break
                tk = min(subj["taken"].get((mid, day), 0), sched)
                pdf.set_fill_color(*_dot_color(tk, sched))
                pdf.ellipse(x + 1.6, yy + 0.5, 2.2, 2.2, style="F")
                name = subj["names"][mid]
                name = (name[:11] + "…") if len(name) > 12 else name
                pdf.set_xy(x + 4.6, yy)
                pdf.set_font("DejaVu", "", 6)
                pdf.set_text_color(35, 35, 35)
                pdf.cell(col_w - 5, 3.2, name)
                yy += 3.4
                shown += 1


def _build_doctor_pdf(subjects, days, start_day, today, period_str, gen_str) -> io.BytesIO:
    """Собирает альбомный PDF-отчёт для врача (страница-календарь на каждого субъекта)."""
    pdf = FPDF(orientation="L", format="A4")
    pdf.add_font("DejaVu", "", _FONT)
    pdf.add_font("DejaVu", "B", _FONT_BOLD)
    pdf.set_auto_page_break(False)
    for subj in subjects:
        _render_subject_page(pdf, subj, days, start_day, today, period_str, gen_str)
    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


@handle_db_errors
async def export_doctor_report(update, context):
    """Генерирует PDF «Отчёт для врача» — календарь приверженности за 30 дней (F1)."""
    query = update.callback_query
    await query.answer("Генерирую отчёт...")
    user = update.effective_user
    user_id = get_or_create_user(user.id, user.username)
    user_tz = get_tz_for_user(user.id)

    rules = get_adherence_rules(user_id)
    if not rules:
        await query.message.reply_text("Нет активных лекарств для отчёта.")
        return

    today, start_day, start_utc, end_utc = adherence_window(user_tz)
    taken_rows = get_taken_intakes(user_id, start_utc, end_utc)
    user_label = f"@{user.username}" if user.username else (user.first_name or str(user.id))
    subjects, days = _prepare_doctor_model(rules, taken_rows, user_tz, start_day, today, user_label)

    if not subjects:
        await query.message.reply_text("За последние 30 дней нет запланированных приёмов.")
        return

    period_str = f"{start_day.strftime('%d.%m.%Y')}–{today.strftime('%d.%m.%Y')}"
    gen_str = datetime.now(user_tz).strftime("%d.%m.%Y")
    buf = await asyncio.to_thread(_build_doctor_pdf, subjects, days, start_day, today, period_str, gen_str)
    filename = f"doctor_report_{today.strftime('%Y%m%d')}.pdf"
    await query.message.reply_document(
        document=buf, filename=filename, caption="🩺 Отчёт для врача — приверженность за 30 дней"
    )


def get_handlers():
    """Возвращает handlers для экспорта в PDF (план, история, соблюдение, отчёт врача)."""
    return [
        CallbackQueryHandler(export_week_plan, pattern="^export:plan$"),
        CallbackQueryHandler(export_week_stats, pattern="^export:week$"),
        CallbackQueryHandler(export_adherence, pattern="^export:adherence$"),
        CallbackQueryHandler(export_doctor_report, pattern="^export:doctor$"),
    ]
