import asyncio
import logging
from datetime import datetime, timedelta
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import (get_active_schedule_rows, log_intake, apply_intake_stock,
                      get_schedules_by_medication, get_or_create_user, get_medication_by_id)
from utils import escape_html, get_tz_for_user, local_day_bounds_utc
# _rule_fires_today живёт в schedule_utils (чистая логика, без telegram/db);
# реэкспорт для обратной совместимости: stats/export/timezone импортируют его отсюда.
from schedule_utils import _rule_fires_today, days_of_stock_left

logger = logging.getLogger(__name__)

_MEAL_LABELS = {
    "before": "до еды",
    "after": "после еды",
    "with": "во время еды",
    "any": "независимо",
}

# (telegram_id, medication_id, reminder_time) -> datetime (UTC) последней отправки
_pending: dict = {}
# (telegram_id, date_iso) — пользователи, которым план дня уже отправлен сегодня
_daily_plan_sent: set = set()


def clear_pending_for_medication(medication_id: int):
    """Удаляет все pending-записи для указанного лекарства (вызывается при деактивации)."""
    for key in [k for k in _pending if k[1] == medication_id]:
        del _pending[key]


def _prune_pending(now_utc: datetime):
    """Удаляет из _pending записи старше 2 часов (защита от роста в режиме once)."""
    cutoff = now_utc - timedelta(seconds=7200)
    for key in [k for k, ts in _pending.items() if ts < cutoff]:
        del _pending[key]


async def send_reminders(app):
    """Проверяет расписание и отправляет напоминания с учётом TZ каждого пользователя."""
    now_utc = datetime.now(pytz.utc)
    _prune_pending(now_utc)
    # B3: синхронный psycopg-запрос не должен блокировать event loop каждую минуту.
    schedules = await asyncio.to_thread(get_active_schedule_rows)

    for row in schedules:
        try:
            user_tz = pytz.timezone(row["timezone"] or "UTC")
        except Exception:
            user_tz = pytz.utc

        now_local = datetime.now(user_tz)
        now_str = now_local.strftime("%H:%M")
        key = (row["telegram_id"], row["medication_id"], row["reminder_time"])

        if not _rule_fires_today(row, now_local.date()):
            continue

        should_send = False
        if row["reminder_time"] == now_str:
            should_send = True
        elif row["reminder_mode"] == "repeat" and key in _pending:
            elapsed = (now_utc - _pending[key]).total_seconds()
            if 300 <= elapsed < 7200:  # повтор каждые 5 мин, не дольше 2 часов
                should_send = True
            elif elapsed >= 7200:
                _pending.pop(key, None)

        if not should_send:
            continue

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✅ Принял",
                callback_data=f"taken:{row['medication_id']}:{row['reminder_time']}"
            ),
            InlineKeyboardButton(
                "❌ Пропустить",
                callback_data=f"skipped:{row['medication_id']}:{row['reminder_time']}"
            ),
        ]])

        dosage = row["rule_dosage"] or row["med_dosage"]
        dep_suffix = f" <i>({escape_html(row['dependent_name'])})</i>" if row["dependent_name"] else ""
        try:
            await app.bot.send_message(
                chat_id=row["telegram_id"],
                text=(
                    f"💊 Время принять лекарство!\n\n"
                    f"<b>{escape_html(row['name'])}</b>{dep_suffix} — {escape_html(dosage)}\n"
                    f"🍽 Принимать {_MEAL_LABELS.get(row['meal_relation'], row['meal_relation'])}"
                ),
                parse_mode="HTML",
                reply_markup=keyboard
            )
            _pending[key] = now_utc
            logger.info("Напоминание отправлено: %s → %s", row["name"], row["telegram_id"])
        except Exception as e:
            logger.error("Ошибка отправки напоминания: %s", e)

    await _send_daily_plans(app, schedules)


def _prune_daily_plan_sent():
    """Удаляет из _daily_plan_sent записи старше 2 дней (локальная дата ±1 от UTC)."""
    cutoff = (datetime.now(pytz.utc).date() - timedelta(days=2)).isoformat()
    stale = {k for k in _daily_plan_sent if k[1] < cutoff}
    _daily_plan_sent.difference_update(stale)


async def _send_daily_plans(app, schedules):
    """Отправляет утренний план дня пользователям, у которых наступило время plan_time.

    Использует строки из общего прохода планировщика (schedules), фильтруя по
    daily_plan_enabled — без отдельного запроса к БД.
    """
    _prune_daily_plan_sent()
    rows = [r for r in schedules if r["daily_plan_enabled"]]
    if not rows:
        return

    users: dict = {}
    for row in rows:
        tid = row["telegram_id"]
        if tid not in users:
            try:
                tz = pytz.timezone(row["timezone"] or "UTC")
            except Exception:
                tz = pytz.utc
            now_local = datetime.now(tz)
            users[tid] = {
                "tz": tz,
                "now_local": now_local,
                "plan_time": row["daily_plan_time"] or "08:00",
                "meds": {},
            }
        mid = row["medication_id"]
        if not _rule_fires_today(row, users[tid]["now_local"].date()):
            continue
        if mid not in users[tid]["meds"]:
            users[tid]["meds"][mid] = {
                "name": row["name"], "meal_relation": row["meal_relation"],
                "dep_name": row["dependent_name"], "times": [],
            }
        dosage = row["rule_dosage"] or row["med_dosage"]
        users[tid]["meds"][mid]["times"].append((row["reminder_time"], dosage))

    for tid, data in users.items():
        now_local = data["now_local"]
        if now_local.strftime("%H:%M") != data["plan_time"]:
            continue
        plan_key = (tid, now_local.date().isoformat())
        if plan_key in _daily_plan_sent:
            continue
        if not data["meds"]:
            continue

        lines = ["🌅 <b>Доброе утро!</b>\n", "📋 <b>Сегодня нужно принять:</b>\n"]
        for med in data["meds"].values():
            meal = _MEAL_LABELS.get(med["meal_relation"], "")
            dep_label = f" <i>({escape_html(med['dep_name'])})</i>" if med["dep_name"] else ""
            lines.append(f"💊 <b>{escape_html(med['name'])}</b>{dep_label}")
            for reminder_time, dosage in sorted(med["times"]):
                lines.append(f"   ⏰ {reminder_time} — {escape_html(dosage)} — {meal}")
        lines.append("\nНе забудь взять лекарства с собой! 🎒")
        lines.append("Продуктивного дня! 🚀")

        try:
            await app.bot.send_message(
                chat_id=tid,
                text="\n".join(lines),
                parse_mode="HTML"
            )
            _daily_plan_sent.add(plan_key)
            logger.info("План дня отправлен: %s", tid)
        except Exception as e:
            logger.error("Ошибка отправки плана дня: %s", e)


async def handle_intake_callback(update, context):
    """Обрабатывает нажатие кнопок ✅ Принял / ❌ Пропустить в напоминании.

    Парсит callback_data формата «status:medication_id:HH:MM»,
    записывает приём в intake_log и убирает ключ из _pending.
    """
    query = update.callback_query
    await query.answer()

    try:
        parts = query.data.split(":")
        status = parts[0]
        medication_id = int(parts[1])
        scheduled_time = ":".join(parts[2:])
    except (ValueError, IndexError):
        logger.error("Некорректный callback: %s", query.data)
        return

    try:
        telegram_id = update.effective_user.id
        # S1: callback_data контролируется клиентом — проверяем, что лекарство
        # принадлежит нажавшему, иначе можно писать в чужой intake_log / запас.
        # B3: синхронные DB-вызовы — через to_thread, чтобы не блокировать loop.
        user_id = await asyncio.to_thread(get_or_create_user, telegram_id)
        if not await asyncio.to_thread(get_medication_by_id, medication_id, user_id):
            logger.warning(
                "Отклонён callback на чужое/несуществующее лекарство: med=%s от tg=%s",
                medication_id, telegram_id
            )
            return
        user_tz = await asyncio.to_thread(get_tz_for_user, telegram_id)
        start_utc, end_utc = local_day_bounds_utc(user_tz)
        old_status = await asyncio.to_thread(
            log_intake, medication_id, scheduled_time, status, start_utc, end_utc
        )
    except Exception as e:
        logger.error("Ошибка записи приёма: %s", e)
        await query.edit_message_text("⚠️ Не удалось записать приём. Попробуй ещё раз.")
        return

    key = (telegram_id, medication_id, scheduled_time)
    _pending.pop(key, None)

    if status == "taken":
        await query.edit_message_text("✅ Отлично! Приём записан.")
    else:
        await query.edit_message_text("❌ Пропуск записан.")

    # F5: автосписание запаса + предупреждение при пересечении порога
    try:
        await _update_stock_on_intake(
            query.message.reply_text, medication_id, status, old_status, telegram_id, user_tz
        )
    except Exception as e:
        logger.error("Ошибка обновления запаса: %s", e)


async def _update_stock_on_intake(reply_fn, medication_id, new_status, old_status, telegram_id, user_tz):
    """Списывает/возвращает запас при отметке приёма; предупреждает при переходе ниже порога.

    reply_fn — корутина для отправки сообщения (message.reply_text или bot.send_message partial).
    """
    info = await asyncio.to_thread(apply_intake_stock, medication_id, new_status, old_status)
    if not info or not info["changed"] or new_status != "taken":
        return
    rules = await asyncio.to_thread(get_schedules_by_medication, medication_id)
    today = datetime.now(user_tz).date()
    qty, units, thr = info["stock_qty"], info["units_per_dose"], info["low_stock_days"]
    after = days_of_stock_left(rules, qty, units, today)
    before = days_of_stock_left(rules, qty + units, units, today)
    # Предупреждаем один раз — на самом пересечении порога (before выше, after на/ниже).
    if after is not None and after <= thr and (before is None or before > thr):
        user_id = await asyncio.to_thread(get_or_create_user, telegram_id)
        med = await asyncio.to_thread(get_medication_by_id, medication_id, user_id)
        name = escape_html(med["name"]) if med else "Лекарство"
        await reply_fn(
            f"⚠️ <b>{name}</b> скоро закончится: осталось примерно на {after} дн. ({qty:g} шт.).\n"
            f"Не забудь пополнить запас 📦",
            parse_mode="HTML"
        )
