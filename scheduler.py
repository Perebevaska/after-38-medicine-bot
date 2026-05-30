import logging
from datetime import datetime
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import get_all_schedules, log_intake

logger = logging.getLogger(__name__)

# (telegram_id, medication_id, reminder_time) -> datetime (UTC) последней отправки
_pending: dict = {}


async def send_reminders(app):
    """Проверяет расписание и отправляет напоминания с учётом TZ каждого пользователя."""
    now_utc = datetime.now(pytz.utc)
    schedules = get_all_schedules()

    for row in schedules:
        try:
            user_tz = pytz.timezone(row["timezone"] or "UTC")
        except Exception:
            user_tz = pytz.utc

        now_local = datetime.now(user_tz)
        now_str = now_local.strftime("%H:%M")
        key = (row["telegram_id"], row["medication_id"], row["reminder_time"])

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

        meal_labels = {
            "before": "натощак (до еды)",
            "after": "после еды",
            "with": "во время еды",
            "any": "независимо от еды",
        }
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

        try:
            await app.bot.send_message(
                chat_id=row["telegram_id"],
                text=(
                    f"💊 Время принять лекарство!\n\n"
                    f"*{row['name']}* — {row['dosage']}\n"
                    f"🍽 Принимать {meal_labels.get(row['meal_relation'], row['meal_relation'])}"
                ),
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            _pending[key] = now_utc
            logger.info("Напоминание отправлено: %s → %s", row["name"], row["telegram_id"])
        except Exception as e:
            logger.error("Ошибка отправки напоминания: %s", e)


async def handle_intake_callback(update, context):
    """Обрабатывает нажатие кнопки Принял/Пропустил."""
    query = update.callback_query
    await query.answer()

    try:
        parts = query.data.split(":")
        status = parts[0]
        medication_id = int(parts[1])
        scheduled_time = parts[2]
    except (ValueError, IndexError):
        logger.error("Некорректный callback: %s", query.data)
        return

    log_intake(medication_id, scheduled_time, status)

    key = (update.effective_user.id, medication_id, scheduled_time)
    _pending.pop(key, None)

    if status == "taken":
        await query.edit_message_text("✅ Отлично! Приём записан.")
    else:
        await query.edit_message_text("❌ Пропуск записан.")
