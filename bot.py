"""
Main entry point for the Time & Activity Tracker Telegram Bot.

Initializes the database, sets up logging, creates the Telegram bot application,
registers handlers, schedules jobs, and starts the bot.
"""

import logging
import os

# Added datetime for default time object
from datetime import time, timezone, timedelta, datetime
import zoneinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Third-party imports
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

# Load environment variables BEFORE importing local modules
load_dotenv()

# Local application imports
import handlers
import database

# --- Logging Setup ---
# Define format with padding for better alignment
LOG_FORMAT = "%(asctime)s - %(name)-25s - %(levelname)-8s - %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)

# Reduce verbosity of libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
logging.getLogger("telegram.bot").setLevel(
    logging.INFO)  # Maybe INFO for bot connection status

# Logger for this module
logger = logging.getLogger(__name__)

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("Bot token not found in .env file. Exiting.")
    exit("Bot token not found!")

# Load Owner ID (used for /asknow command)
try:
    # Also ensure handlers.OWNER_ID is updated if loaded here only
    owner_id_str = os.getenv("OWNER_ID", "0")
    OWNER_ID = int(owner_id_str)
    handlers.OWNER_ID = OWNER_ID  # Pass it to handlers module if needed there
    if OWNER_ID == 0:
        logger.warning("OWNER_ID not set in .env. Owner commands unavailable.")
except ValueError:
    logger.error("Invalid OWNER_ID in .env. Must be integer.")
    OWNER_ID = 0
    handlers.OWNER_ID = 0


# --- Main Application Setup ---

def main() -> None:
    """Initializes DB, creates PTB application, registers handlers/jobs, runs bot."""

    # Initialize Database
    try:
        database.initialize_database()
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}", exc_info=True)
        return  # Cannot run without DB

    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Register Handlers ---
    # Commands
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("report", handlers.report_handler))
    application.add_handler(CommandHandler("hide_keyboard", handlers.hide_keyboard_handler))
    application.add_handler(CommandHandler("asknow", handlers.ask_now_handler))
    application.add_handler(CommandHandler("set_timezone", handlers.set_timezone_handler))
    application.add_handler(CommandHandler("set_poll_window", handlers.set_poll_window_handler))
    application.add_handler(CommandHandler("set_report_time", handlers.set_report_time_handler))

    # Messages matching ReplyKeyboard buttons
    application.add_handler(MessageHandler(
        filters.Text(["📊 Activity Report"]), handlers.report_button_handler
    ))
    application.add_handler(MessageHandler(
        filters.Text(["❓ Help / Show Menu"]), handlers.help_button_handler
    ))
    application.add_handler(MessageHandler(
        filters.Text(["🌐 Set Timezone"]), handlers.set_timezone_button_handler
    ))
    application.add_handler(MessageHandler(
        filters.Text(["⏰ Set Poll Window"]), handlers.set_poll_window_button_handler
    ))
    application.add_handler(MessageHandler(
        filters.Text(["🗓️ Set Report Time"]), handlers.set_report_time_button_handler
    ))
    application.add_handler(MessageHandler(
        filters.Text(["⌨️ Hide Keyboard"]), handlers.hide_keyboard_button_handler
    ))

    # Handler for activity replies and edits (must be after specific text/command handlers)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handlers.handle_message
    ))

    # Handler for inline keyboard button presses
    application.add_handler(CallbackQueryHandler(
        handlers.button_callback_handler))
    # ------------------------

    # --- Schedule Jobs ---
    job_queue = application.job_queue

    # Activity polling job (runs every 30 mins, checks time window inside)
    try:
        trigger_ask = CronTrigger(minute='0,30')
        job_queue.run_custom(
            callback=handlers.ask_activity,
            job_kwargs={'trigger': trigger_ask, 'misfire_grace_time': 30},
            name="ask_activity_cron_job"
        )
        logger.info(
            f"Scheduled 'ask_activity' job with trigger: {trigger_ask}")
    except Exception as e:
        logger.error(
            f"Failed to schedule ask_activity job: {e}", exc_info=True)

    # Daily report check job (runs hourly, checks local time inside)
    try:
        trigger_report_check = CronTrigger(minute='5')  # Hourly at xx:05
        job_queue.run_custom(
            callback=handlers.check_and_send_daily_reports_job,
            job_kwargs={'trigger': trigger_report_check,
                        'misfire_grace_time': 60},
            name="check_daily_reports_job"
        )
        logger.info(
            f"Scheduled daily report check job hourly (trigger: {trigger_report_check}).")
    except Exception as e:
        logger.error(
            f"Failed to schedule report check job: {e}", exc_info=True)
    # ---------------------

    # --- Start Bot ---
    logger.info("Starting bot polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")


if __name__ == "__main__":
    main()
