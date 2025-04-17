import logging
import os
from datetime import timedelta
from dotenv import load_dotenv
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
                          CallbackQueryHandler)
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

import database
import handlers


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("Bot token not found! Check .env file.")
    exit("Bot token not found!")

def main() -> None:
    try:
        database.initialize_database()
    except Exception as e:
        logger.critical(f"Failed to initialize database. Bot cannot start. Error: {e}", exc_info=True)
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("report", handlers.report_handler))
    application.add_handler(CommandHandler("hide_keyboard", handlers.hide_keyboard_handler))
    application.add_handler(CommandHandler("asknow", handlers.ask_now_handler))

    application.add_handler(MessageHandler(filters.Text(["📊 Activity Report"]), handlers.report_button_handler))
    application.add_handler(MessageHandler(filters.Text(["❓ Help / Show Menu"]), handlers.help_button_handler))
    application.add_handler(MessageHandler(filters.Text(["⌨️ Hide Keyboard"]), handlers.hide_keyboard_button_handler))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))

    application.add_handler(CallbackQueryHandler(handlers.button_callback_handler))

    job_queue = application.job_queue
    trigger = CronTrigger(minute='0,30', hour='6-23')
    job_queue.run_custom(
        callback=handlers.ask_activity,
        job_kwargs={'trigger': trigger, 'misfire_grace_time': 30},
        name="ask_activity_cron_job"
    )
    logger.info(f"Scheduled 'ask_activity' job with trigger: {trigger}")

    logger.info("Starting bot...")
    application.run_polling()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    main()