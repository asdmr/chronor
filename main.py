import logging
import os
import sqlite3

from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (Application, CommandHandler,
                          ContextTypes, JobQueue, MessageHandler, filters)

from dotenv import load_dotenv

load_dotenv()  # loads .env file in root directory

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logging.getLogger("httpx").setLevel(logging.WARNING)  # hides http logs
logger = logging.getLogger(__name__)


BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("Bot token is not found. Check .env file")
    exit()

#ASK_INTERVAL_SECONDS = 3600
ASK_INTERVAL_SECONDS = 60

DB_NAME = "activities.db"


def init_db():
    try:
        if not os.path.exists('data'):  # creates data folder
            os.makedirs('data')
            logger.info("data folder is created for database")

        db_path = os.path.join('data', DB_NAME)
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        # sql ddl query
        cur.execute("""
            create table if not exists activities (
                timestamp text not null,
                user_id integer not null,
                activity_description text
            )
        """)
        con.commit()
        con.close()
        logger.info(f"{db_path} database is initialized")
    except sqlite3.Error as e:
        logger.error(f"Database initializing failed: {e}")
    except OSError as e:
        logger.error(f"Data folder creation is failed: {e}")


def save_activity_to_db(timestamp: datetime, user_id: int, description: str):
    try:
        db_path = os.path.join('data', DB_NAME)
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        # sql dml query
        cur.execute(
            "insert into activities (timestamp, user_id, activity_description) values (?, ?, ?)",
            (timestamp.isoformat(), user_id, description)
        )
        con.commit()
        con.close()
        logger.info(f"Activity '{description}' for user {user_id} is saved")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error in saving an activity to database: {e}")
        return False


async def ask_activity(context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_data = context.bot_data
    user_id = bot_data.get('user_id')

    # if user is saved:
    if user_id:
        if user_id not in context.application.user_data:
            context.application.user_data[user_id] = {}

        current_user_data = context.application.user_data[user_id]
        try:
            # checks if bot is not waiting for response
            if not current_user_data.get('is_awaiting_activity'):
                await context.bot.send_message(
                    chat_id=user_id,
                    text="What is you doing right now? 🤔"
                )
                # flags that bot is waiting
                current_user_data['is_awaiting_activity'] = True
                logger.info(
                    f"Sent a message for asking activity to {user_id}. Waiting a response...")
            else:
                logging.warning(
                    f"Trying to send another message for asking activity to {user_id}, but waiting a response for previous question")
        except Exception as e:
            logger.error(
                f"Sending a message for asking activity to {user_id} is failed: {e}")
            context.application.user_data[user_id].pop('is_awaiting_activity', None)  # means false
    # if user is not saved:
    else:
        logger.warning(
            "Sending a message is failed: user_id is not found in bot_data. User must send /start first")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message_text = update.message.text

    if context.user_data.get('is_awaiting_activity'):
        logger.info(
            f"Got the response about current activity from {user.id}: {message_text}")

        context.user_data['is_awaiting_activity'] = False

        now = datetime.now()

        if save_activity_to_db(now, user.id, message_text):
            await update.message.reply_text(f"✅ The current activity is recorded successfully: \"{message_text}\"")
        else:
            await update.message.reply_text(f"❌ Recording the current activity failed. Try later")
    else:
        logger.info(f"Got regular message from {user.id}: {message_text}")


# none means not returning any sensible value
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # async means doing activites without stopping the whole code

    user = update.effective_user  # about user
    user_id = user.id

    context.bot_data['user_id'] = user_id  # saving user's id

    context.user_data.clear()

    logger.info(
        f"User {user_id} ({user.username}) is currently using the bot. ID is saved")

    await update.message.reply_html(
        f"Hi, {user.mention_html()}! 👋\n\n"
        f"I track your activites and keep you doing something great!\n"
        f"I notify you to do some habits!\n"
        f"At the end of the day, I give you a daily report, so you can evaluate your productivity!\n"
    )
    # await is used before async operations
    # update.message.reply_html(...) allows to send a message with html formatting

# main function that boots the bot


def main() -> None:
    init_db()

    application = Application.builder().token(
        BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = application.job_queue

    # important: task is added only after user sends /start
    # job_queue itself processes user_id inside ask_activity
    job_queue.run_repeating(
        callback=ask_activity,
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
