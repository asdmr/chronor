"""
Main entry point for the Time & Activity Tracker Telegram Bot.

Initializes the database, sets up logging, creates the Telegram bot application,
registers handlers, schedules jobs, and starts the bot.
"""
import logging
import os
from datetime import time, timezone  # Keep timezone for UTC schedule
# Remove unused datetime, zoneinfo imports if not needed elsewhere
# import zoneinfo
# from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Third-party imports
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

# Load environment variables BEFORE importing local modules that might use them
load_dotenv()

# Local application imports
import database
import handlers  # This now reads OWNER_ID at import time

# --- Logging Setup ---
LOG_FORMAT = "%(asctime)s - %(name)-25s - %(levelname)-8s - %(message)s"
# Use DEBUG for development, INFO for production
LOG_LEVEL = logging.DEBUG if os.getenv("DEBUG") == "1" else logging.INFO
logging.basicConfig(format=LOG_FORMAT, level=LOG_LEVEL)

# Reduce verbosity of libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
logging.getLogger("telegram.bot").setLevel(logging.INFO)

# Logger for this module
logger = logging.getLogger(__name__)

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("Bot token not found in .env file. Exiting.")
    exit("Bot token not found!")

# OWNER_ID is loaded inside handlers.py now, no need to load here unless used elsewhere


# --- Main Application Setup ---

def main() -> None:
    """Initializes DB, creates PTB application, registers handlers/jobs, runs bot."""
    logger.info("Starting bot initialization...")

    # 1. Initialize Database
    try:
        database.initialize_database()
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}", exc_info=True)
        return  # Cannot run without DB

    # 2. Create the Application
    # Consider adding persistence=PicklePersistence(filepath='./bot_data_persist') for bot_data/user_data
    application = Application.builder().token(BOT_TOKEN).build()

    # 3. Register Handlers
    # Commands
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("report", handlers.report_handler))
    application.add_handler(CommandHandler(
        "hide_keyboard", handlers.hide_keyboard_handler))
    application.add_handler(CommandHandler("asknow", handlers.ask_now_handler))
    application.add_handler(CommandHandler(
        "set_timezone", handlers.set_timezone_handler))
    application.add_handler(CommandHandler(
        "set_poll_window", handlers.set_poll_window_handler))
    application.add_handler(CommandHandler(
        "set_report_time", handlers.set_report_time_handler))

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
        filters.Text(["⏰ Set Poll Window"]
                     ), handlers.set_poll_window_button_handler
    ))
    application.add_handler(MessageHandler(
        filters.Text(["🗓️ Set Report Time"]
                     ), handlers.set_report_time_button_handler
    ))
    application.add_handler(MessageHandler(
        filters.Text(["⌨️ Hide Keyboard"]
                     ), handlers.hide_keyboard_button_handler
    ))

    # Handler for activity replies and edits
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handlers.handle_message
    ))

    # Handler for inline keyboard button presses
    application.add_handler(CallbackQueryHandler(
        handlers.button_callback_handler))
    logger.info("Command and message handlers registered.")

    # 4. Schedule Jobs
    job_queue = application.job_queue
    if not job_queue:
        logger.warning("JobQueue is not available. Scheduling disabled.")
        # Handle case where JobQueue might not be initialized (e.g., missing dependency)
    else:
        # Activity polling job
        try:
            # Polls HH:00 and HH:30 server time
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

        # Daily report check job
        try:
            # Runs hourly at 5 mins past hour
            trigger_report_check = CronTrigger(minute='5')
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

    # 5. Start Bot
    logger.info("Starting bot polling...")
    # Run the bot until the user presses Ctrl-C
    application.run_polling()
    logger.info("Bot polling stopped.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Catch unexpected errors during startup or runtime if they reach here
        logger.critical(
            f"Bot terminated due to critical error: {e}", exc_info=True)
