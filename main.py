import logging
import os

from datetime import timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue

from dotenv import load_dotenv

load_dotenv()

# to see errors
logging.basicConfig(
    # format for logs
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# filters out unnecessary http logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)  # logs activites of this file

# constants
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("Bot token is not found. Check .env")
    exit()

ASK_INTERVAL_SECONDS = 3600  # each hour


async def ask_activity(context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_data = context.bot_data
    user_id = bot_data.get('user_id')

    # if user is saved:
    if user_id:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="What is you doing right now? 🤔"
            )
            logger.info(f"Sent a message for asking activity to {user_id}")
        except Exception as e:
            logger.error(
                f"Sending a message for asking activity to {user_id} is failed: {e}")
    # if user is not saved:
    else:
        logger.warning(
            "Sending a message is failed: user_id is not found in bot_data. User must send /start first")

# handles commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # none means not returning any sensible value
    # async means doing activites without stopping the whole code

    user = update.effective_user  # about user
    user_id = user.id

    context.bot_data['user_id'] = user_id  # saving user's id

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
    application = Application.builder().token(
        BOT_TOKEN).build()  # builds the bot with token

    # triggers on "/start" command and runs "start" function
    application.add_handler(CommandHandler("start", start))

    job_queue = application.job_queue

    # important: task is added only after user sends /start
    # job_queue itself processes user_id inside ask_activity 
    job_queue.run_repeating(
        callback=ask_activity,                              # calling the ask_activity function
        interval=timedelta(seconds=ASK_INTERVAL_SECONDS),   # interval between callbacks
        #first=10,                                          # time delay before first run in seconds 
        name="ask_activity_job"                             # name of the task in logs
    )

    logger.info(
        f"Task ask_activity is planned with time interval of {ASK_INTERVAL_SECONDS} seconds")

    logger.info("Bot is running")
    application.run_polling()  # checks any input
    logger.info("Bot is stopped")


if __name__ == "__main__":
    main()
