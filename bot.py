import logging
import os
from datetime import timedelta, time, timezone, datetime
import zoneinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

import database
import handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)-8s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("Bot token not found! Check .env file.")
    exit("Bot token not found!")

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    if OWNER_ID == 0:
        logger.warning("OWNER_ID not set in .env file. Owner-specific features might not work.")
except ValueError:
    logger.error("Invalid OWNER_ID format in .env file. It should be an integer.")
    OWNER_ID = 0

def main() -> None:
    try: database.initialize_database()
    except Exception as e: logger.critical(f"Failed to initialize database: {e}", exc_info=True); return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("report", handlers.report_handler))
    application.add_handler(CommandHandler("hide_keyboard", handlers.hide_keyboard_handler))
    application.add_handler(CommandHandler("asknow", handlers.ask_now_handler)) # for debugging
    application.add_handler(CommandHandler("set_timezone", handlers.set_timezone_handler))

    application.add_handler(MessageHandler(filters.Text(["📊 Activity Report"]), handlers.report_button_handler))
    application.add_handler(MessageHandler(filters.Text(["❓ Help / Show Menu"]), handlers.help_button_handler))
    application.add_handler(MessageHandler(filters.Text(["⌨️ Hide Keyboard"]), handlers.hide_keyboard_button_handler))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))
    application.add_handler(CallbackQueryHandler(handlers.button_callback_handler))

    job_queue = application.job_queue

    trigger_ask = CronTrigger(minute='0,30')
    job_queue.run_custom(
        callback=handlers.ask_activity,
        job_kwargs={'trigger': trigger_ask, 'misfire_grace_time': 30},
        name="ask_activity_cron_job"
    )
    logger.info(f"Scheduled 'ask_activity' job with trigger: {trigger_ask} (Time check inside handler)")

    trigger_report_check = CronTrigger(minute='5') # Runs hourly at minute 5
    job_queue.run_custom(
        callback=handlers.check_and_send_daily_reports_job,
        job_kwargs={'trigger': trigger_report_check, 'misfire_grace_time': 60},
        name="check_daily_reports_job"
    )
    logger.info(f"Scheduled daily report check job to run hourly (trigger: {trigger_report_check}).")

    logger.info("Starting bot...")
    application.run_polling()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    main()