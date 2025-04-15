import logging
import io
import re # Оставляем re на всякий случай, но он не используется сейчас
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, CallbackQuery
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters, CommandHandler

import database

logger = logging.getLogger(__name__)

async def _send_activity_report(user_id: int, report_date_str: str, query: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Generating merged activity report for user {user_id}, date {report_date_str}.")
    activities = database.get_activities_for_day(user_id, report_date_str)
    reply_target = query.message if isinstance(query, CallbackQuery) else query.message
    if not activities:
        await reply_target.reply_text(f"No activity records found for {report_date_str}.")
        return
    report_lines = []
    report_lines.append(f"Merged Activity Log: {report_date_str}")
    report_lines.append("=" * 30)
    if activities:
        start_block_ts_str, current_desc = activities[0]
        start_block_dt = datetime.fromisoformat(start_block_ts_str)
        for i in range(1, len(activities)):
            next_ts_str, next_desc = activities[i]
            next_dt = datetime.fromisoformat(next_ts_str)
            if next_desc != current_desc:
                end_block_dt = next_dt
                report_lines.append(f"{start_block_dt.strftime('%H:%M')} - {end_block_dt.strftime('%H:%M')} - {current_desc}")
                start_block_dt = next_dt
                current_desc = next_desc
        report_lines.append(f"{start_block_dt.strftime('%H:%M')} -       - {current_desc}")
    report_content = "\n".join(report_lines)
    report_file = io.StringIO(report_content)
    filename = f"activity_report_merged_{report_date_str}.txt"
    try:
        report_file.seek(0)
        input_file = InputFile(report_file, filename=filename)
        await reply_target.reply_document(document=input_file, caption=f"Activity Log: {report_date_str}.")
        logger.info(f"Merged activity report for {report_date_str} sent successfully to user {user_id}.")
    except Exception as e:
        logger.error(f"Error sending merged activity report file to user {user_id}: {e}", exc_info=True)
        await reply_target.reply_text("Could not send the merged activity report file. Please try again later.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name
    database.add_user_if_not_exists(user_id, username, first_name)
    logger.info(f"Checked/added user to DB: user_id={user_id}, username={username}")
    context.bot_data['user_id'] = user_id
    context.user_data.clear()
    logger.info(f"User {user_id} ({username}) initiated session. User ID stored in bot_data.")

    keyboard = [
        [KeyboardButton("📊 Activity Report")],
        [KeyboardButton("❓ Help / Show Menu")],
        [KeyboardButton("⌨️ Hide Keyboard")]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True, one_time_keyboard=False,
        input_field_placeholder="Use menu or reply to questions..."
    )
    info_text = (
        f"User {user.mention_html()} identified.\n\n"
        f"<b>Objective:</b> Meticulous time and activity logging.\n"
        f"<b>Procedure:</b> Respond accurately to periodic activity inquiries (approx. every 30 min, 06:00-23:00 local time).\n"
        f"<b>Input format:</b> Activity description.\n\n"
        f"Use the keyboard below for common actions or type /help for details."
    )
    await update.message.reply_html(info_text, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user_id} requested directive summary.")

    keyboard = [
        [KeyboardButton("📊 Activity Report")],
        [KeyboardButton("❓ Help / Show Menu")],
        [KeyboardButton("⌨️ Hide Keyboard")]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True, one_time_keyboard=False,
        input_field_placeholder="Use menu or reply to questions..."
    )
    info_text = (
        f"<b>Available directives (or use keyboard):</b>\n"
        f"/report [YYYY-MM-DD] - Generate activity log (default: today).\n"
        f"/help - Display this directive summary.\n"
        f"/hide_keyboard - Hide this custom keyboard."
    )
    await update.message.reply_html(info_text, reply_markup=reply_markup)


async def ask_activity(context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_data = context.bot_data
    user_id = bot_data.get('user_id')
    current_user_data = None
    if user_id:
        try:
            if user_id not in context.application.user_data:
                context.application.user_data[user_id] = {}
            current_user_data = context.application.user_data[user_id]
            if not current_user_data.get('is_awaiting_activity'):
                await context.bot.send_message(chat_id=user_id, text="Report current activity.")
                current_user_data['is_awaiting_activity'] = True
                logger.info(f"Activity inquiry sent to user {user_id}. Awaiting response...")
            else:
                logger.warning(f"Tried to ask user {user_id} about activity, but previous response is still pending.")
        except Exception as e:
            logger.error(f"Error processing ask_activity for user {user_id}: {e}", exc_info=True)
            if current_user_data is not None:
                 try: current_user_data.pop('is_awaiting_activity', None); logger.info(f"Flag 'is_awaiting_activity' cleared for {user_id} due to error.")
                 except Exception as cleanup_e: logger.error(f"Failed to clear 'is_awaiting_activity' flag for {user_id} during cleanup: {cleanup_e}")
            else: logger.warning(f"Could not clear flag for {user_id} during cleanup, as current_user_data was not assigned.")
    else: logger.warning("Could not send inquiry in ask_activity: user_id not found in bot_data.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    message_text = update.message.text
    if context.user_data.get('is_awaiting_activity'):
        logger.info(f"Received activity response from {user_id}: {message_text}")
        context.user_data['is_awaiting_activity'] = False
        description_to_save = message_text
        now = datetime.now()
        activity_id = database.save_activity_to_db(user_id, description_to_save, now)
        if activity_id is not None:
            reply_text = f"Acknowledged. Logged: \"{description_to_save}\" (ID: {activity_id})."
        else:
            reply_text = "Error during data persistence. Activity log potentially incomplete."
        await update.message.reply_text(reply_text)
    else:
        logger.info(f"Received standard message from {user.id} (not an activity response): '{message_text}'")

async def hide_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to hide reply keyboard.")
    await update.message.reply_text(
        "Custom keyboard hidden. Use /start or /help to show it again.",
        reply_markup=ReplyKeyboardRemove()
    )


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    report_date_str = None
    if context.args:
        try:
            datetime.strptime(context.args[0], '%Y-%m-%d'); report_date_str = context.args[0]
            logger.info(f"User {user_id} requested activity report for specific date: {report_date_str}.")
            await _send_activity_report(user_id, report_date_str, update, context)
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid date format. Please use YYYY-MM-DD or omit for date selection.")
            return
    else:
        logger.info(f"User {user_id} requested activity report without date. Sending options...")
        today = datetime.now(); yesterday = today - timedelta(days=1)
        today_str = today.strftime('%Y-%m-%d'); yesterday_str = yesterday.strftime('%Y-%m-%d')
        keyboard = [[ InlineKeyboardButton("Today", callback_data=f"report_select:activity:{today_str}"), InlineKeyboardButton("Yesterday", callback_data=f"report_select:activity:{yesterday_str}") ], [ InlineKeyboardButton("Cancel", callback_data="report_select:cancel") ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select report period:", reply_markup=reply_markup)


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    user_id = query.from_user.id
    logger.info(f"Received callback_query from user {user_id} with data: {callback_data}")

    if callback_data.startswith("report_select:"):
        parts = callback_data.split(":")
        if len(parts) >= 2 and parts[1] == 'cancel':
            logger.info(f"User {user_id} cancelled report selection.")
            try: await query.edit_message_text(text="Report selection cancelled.")
            except Exception as e: logger.warning(f"Could not edit message on cancellation for user {user_id}: {e}")
            return
        if len(parts) == 3:
            report_type = parts[1]
            selected_date_str = parts[2]
            logger.info(f"User {user_id} selected date {selected_date_str} for {report_type} report via button.")
            try: await query.edit_message_text(text=f"Generating {report_type} report for {selected_date_str}...")
            except Exception as e: logger.warning(f"Could not edit message to show 'Generating...' for user {user_id}: {e}")
            if report_type == "activity": await _send_activity_report(user_id, selected_date_str, query, context)
            else: logger.error(f"Unknown report type '{report_type}' in callback data: {callback_data}"); await context.bot.send_message(chat_id=user_id, text="An internal error occurred processing your request.")
        else: logger.error(f"Invalid callback data format received (expected 3 parts or cancel): {callback_data}"); await context.bot.send_message(chat_id=user_id, text="An internal error occurred.")
    else: logger.warning(f"Unhandled callback_data received: {callback_data}")

report_button_handler = report_handler
help_button_handler = help_command
hide_keyboard_button_handler = hide_keyboard_handler    