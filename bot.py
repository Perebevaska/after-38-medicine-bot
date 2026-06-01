import os
from dotenv import load_dotenv
load_dotenv()

import logging
import warnings
from telegram.error import TimedOut, NetworkError
from telegram.warnings import PTBUserWarning
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from database import init_db, migrate
from scheduler import send_reminders, handle_intake_callback
from handlers import meds
from handlers import timezone as tz_handler
from handlers import stats, settings, admin, export, caregiver
from utils import cancel
from constants import SETUP_TZ, SETUP_CITY

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=PTBUserWarning)
logger = logging.getLogger(__name__)


async def post_init(app):
    """Регистрирует команды бота в меню Telegram после запуска."""
    await app.bot.set_my_commands([
        BotCommand("start",    "🏠 Главное меню"),
        BotCommand("meds",     "💊 Мои лекарства"),
        BotCommand("stats",    "📊 Статистика"),
        BotCommand("settings", "⚙️ Настройки"),
        BotCommand("about",    "ℹ️ О проекте"),
        BotCommand("cancel",   "❌ Отменить действие"),
    ])


async def error_handler(update, context):
    """Глобальный обработчик ошибок: игнорирует транзиентные сетевые ошибки Telegram."""
    if isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning("Telegram network error (transient): %s", context.error)
        return
    logger.error("Unhandled error", exc_info=context.error)


def main():
    """Точка входа: инициализирует БД, регистрирует все handlers, запускает бота."""
    init_db()
    migrate()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    cancel_handler = CommandHandler("cancel", cancel)

    setup_tz_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", tz_handler.start),
            CommandHandler("timezone", tz_handler.timezone_command),
            CallbackQueryHandler(tz_handler.handle_settings_timezone, pattern="^settings:timezone$"),
        ],
        states={
            SETUP_TZ: [
                MessageHandler(filters.LOCATION, tz_handler.handle_location),
                MessageHandler(filters.TEXT & ~filters.COMMAND, tz_handler.handle_tz_text),
            ],
            SETUP_CITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, tz_handler.handle_city_input),
            ],
        },
        fallbacks=[cancel_handler],
    )

    app.add_handler(setup_tz_handler)
    app.add_handler(meds.get_add_handler(cancel_handler))
    app.add_handler(CommandHandler("meds", meds.meds_command))
    app.add_handler(meds.get_edit_handler(cancel_handler))
    app.add_handler(CallbackQueryHandler(meds.handle_delete_callback, pattern="^delete:"))
    app.add_handler(CommandHandler("stats", stats.stats_command))
    app.add_handler(CommandHandler("settings", settings.settings_command))
    app.add_handler(CommandHandler("about", settings.about_command))
    for h in stats.get_handlers():
        app.add_handler(h)
    for h in export.get_handlers():
        app.add_handler(h)
    app.add_handler(settings.get_handler())
    app.add_handler(settings.get_preset_handler(cancel_handler))
    app.add_handler(settings.get_daily_plan_time_handler(cancel_handler))
    app.add_handler(CallbackQueryHandler(settings.handle_show_presets, pattern="^settings:presets$"))
    app.add_handler(CallbackQueryHandler(settings.handle_settings_back, pattern="^settings:back$"))
    app.add_handler(CallbackQueryHandler(settings.handle_daily_plan_settings, pattern="^settings:daily_plan$"))
    app.add_handler(CallbackQueryHandler(settings.handle_daily_plan_toggle, pattern="^daily_plan:toggle$"))
    app.add_handler(CallbackQueryHandler(settings.handle_daily_plan_back, pattern="^daily_plan:back$"))
    app.add_handler(CallbackQueryHandler(settings.handle_delete_request, pattern="^settings:delete$"))
    app.add_handler(CallbackQueryHandler(settings.handle_delete_confirm, pattern="^delete_data_confirm$"))
    app.add_handler(CallbackQueryHandler(settings.handle_delete_cancel, pattern="^delete_data_cancel$"))
    for h in caregiver.get_handlers(cancel_handler):
        app.add_handler(h)
    app.add_handler(CallbackQueryHandler(admin.handle_admin_panel, pattern="^admin:panel$"))
    app.add_handler(CallbackQueryHandler(admin.handle_admin_back, pattern="^admin:back$"))
    app.add_handler(CallbackQueryHandler(tz_handler.handle_menu_callback, pattern="^menu:"))
    app.add_handler(CallbackQueryHandler(handle_intake_callback, pattern="^(taken|skipped):"))
    app.add_error_handler(error_handler)

    job_queue = app.job_queue
    job_queue.run_repeating(
        lambda ctx: send_reminders(app),
        interval=60,
        first=0
    )

    logger.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
