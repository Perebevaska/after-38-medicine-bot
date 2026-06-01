import logging
from datetime import datetime, timedelta
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import get_active_schedule_rows, log_intake
from utils import escape_md, get_tz_for_user, local_day_bounds_utc
# _rule_fires_today живёт в schedule_utils (чистая логика, без telegram/db);
# реэкспорт для обратной совместимости: stats/export/timezone импортируют его отсюда.
from schedule_utils import _rule_fires_today

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
    schedules = get_active_schedule_rows()

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
        dep_suffix = f" _({escape_md(row['dependent_name'])})_" if row["dependent_name"] else ""
        try:
            await app.bot.send_message(
                chat_id=row["telegram_id"],
                text=(
                    f"💊 Время принять лекарство!\n\n"
                    f"*{escape_md(row['name'])}*{dep_suffix} — {escape_md(dosage)}\n"
                    f"🍽 Принимать {_MEAL_LABELS.get(row['meal_relation'], row['meal_relation'])}"
                ),
                parse_mode="Markdown",
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

        lines = ["🌅 *Доброе утро!*\n", "📋 *Сегодня нужно принять:*\n"]
        for med in data["meds"].values():
            meal = _MEAL_LABELS.get(med["meal_relation"], "")
            dep_label = f" _({escape_md(med['dep_name'])})_" if med["dep_name"] else ""
            lines.append(f"💊 *{escape_md(med['name'])}*{dep_label}")
            for reminder_time, dosage in sorted(med["times"]):
                lines.append(f"   ⏰ {reminder_time} — {escape_md(dosage)} — {meal}")
        lines.append("\nНе забудь взять лекарства с собой! 🎒")
        lines.append("Продуктивного дня! 🚀")

        try:
            await app.bot.send_message(
                chat_id=tid,
                text="\n".join(lines),
                parse_mode="Markdown"
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
        user_tz = get_tz_for_user(update.effective_user.id)
        start_utc, end_utc = local_day_bounds_utc(user_tz)
        log_intake(medication_id, scheduled_time, status, start_utc, end_utc)
    except Exception as e:
        logger.error("Ошибка записи приёма: %s", e)
        await query.edit_message_text("⚠️ Не удалось записать приём. Попробуй ещё раз.")
        return

    key = (update.effective_user.id, medication_id, scheduled_time)
    _pending.pop(key, None)

    if status == "taken":
        await query.edit_message_text("✅ Отлично! Приём записан.")
    else:
        await query.edit_message_text("❌ Пропуск записан.")
