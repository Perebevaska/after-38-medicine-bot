import functools
import pytz
from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update
from database import get_user_timezone, DatabaseError

NAME_MAX_LEN = 50
DOSAGE_MAX_LEN = 30


def escape_md(text: str) -> str:
    """Экранирует спецсимволы Telegram Markdown v1."""
    for ch in ('*', '_', '`', '['):
        text = text.replace(ch, '\\' + ch)
    return text


def parse_time(time_str: str) -> str:
    """Парсит и нормализует время в формат ЧЧ:ММ. Поднимает ValueError при ошибке."""
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError
    return f"{h:02d}:{m:02d}"


def get_tz_for_user(telegram_id: int) -> pytz.timezone:
    """Возвращает timezone объект для пользователя."""
    tz_name = get_user_timezone(telegram_id)
    try:
        return pytz.timezone(tz_name)
    except Exception:
        return pytz.utc


def handle_db_errors(func):
    """Декоратор: перехватывает DatabaseError и отвечает пользователю сообщением об ошибке."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except DatabaseError:
            msg = update.message or (
                update.callback_query and update.callback_query.message
            )
            if msg:
                await msg.reply_text("⚠️ Ошибка базы данных. Попробуй позже.")
    return wrapper


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /cancel — завершает любой активный ConversationHandler."""
    context.user_data.clear()
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END
