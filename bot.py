import logging
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (Application, CommandHandler,
                          ContextTypes, JobQueue, MessageHandler, filters)

import database
import handlers

load_dotenv()  # loads .env file in root directory

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logging.getLogger("httpx").setLevel(logging.WARNING)  # hides http logs
logger = logging.getLogger(__name__)


BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("Bot token is not found. Check .env file")
    exit("Bot token is not found")

#ASK_INTERVAL_SECONDS = 3600
ASK_INTERVAL_SECONDS = 60
   
def main() -> None:
    """ main function that boots the bot """

    try:
        database.initialize_database()
    except Exception as e:
        logger.critical(f"Critical error in database initialization: {e}")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("addtag", handlers.add_tag_handler))
    application.add_handler(CommandHandler("listtags", handlers.list_tags_handler))
    application.add_handler(CommandHandler("deltag", handlers.delete_tag_handler))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))

    job_queue = application.job_queue

    # --- important: task is added only after user sends /start ---
    # --- job_queue itself processes user_id inside ask_activity ---
    job_queue.run_repeating(
        callback=handlers.ask_activity,
        interval=timedelta(seconds=ASK_INTERVAL_SECONDS),
        # first=10, # time delay before first run in seconds
        name="ask_activity_job"
    )

    logger.info(
        f"Task ask_activity is planned with time interval of {ASK_INTERVAL_SECONDS} seconds")

    logger.info("Bot is running")
    application.run_polling()  # checks any input
    logger.info("Bot is stopped")


if __name__ == "__main__":
    main()
