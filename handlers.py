import logging
import io
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, CallbackQuery
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters, CommandHandler

import database

logger = logging.getLogger(__name__)

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    if OWNER_ID == 0:
        logger.warning(
            "OWNER_ID not set in .env file. Owner-restricted commands may not function correctly.")
except ValueError:
    logger.error(
        "Invalid OWNER_ID format in .env file. It should be an integer.")
    OWNER_ID = 0


async def _send_activity_report(user_id: int, report_date_str: str, query: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"Generating merged activity report for user {user_id}, date {report_date_str}.")
    activities = database.get_activities_for_day(user_id, report_date_str)
    reply_target = query.message if isinstance(
        query, CallbackQuery) else query.message
    
    if not activities:
        await reply_target.reply_text(f"No activity records found for {report_date_str} to generate file.")
        return

    report_lines = []
    report_lines.append(f"Merged Activity Log: {report_date_str}")
    report_lines.append("=" * 30)

    if activities:
        _, start_block_ts_str, current_desc = activities[0]
        start_block_dt = datetime.fromisoformat(start_block_ts_str)

        for i in range(1, len(activities)):
            _, next_ts_str, next_desc = activities[i]
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
        await context.bot.send_document(
            chat_id=reply_target.chat_id,
            document=input_file,
            caption=f"Activity Log File: {report_date_str}."
        )
        logger.info(f"Merged activity report file for {report_date_str} sent successfully to user {user_id}.")
    except Exception as e:
        logger.error(f"Error sending merged activity report file to user {user_id}: {e}", exc_info=True)
        await reply_target.reply_text("Could not send the merged activity report file. Please try again later.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name
    database.add_user_if_not_exists(user_id, username, first_name)
    logger.info(
        f"Checked/added user to DB: user_id={user_id}, username={username}")
    context.bot_data['user_id'] = user_id
    context.user_data.clear()
    logger.info(
        f"User {user_id} ({username}) initiated session. User ID stored in bot_data.")

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


async def ask_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually triggers the ask_activity function (owner only)."""
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        logger.warning(f"User {user_id} (not owner) tried to use /asknow.")
        await update.message.reply_text("This command is restricted to the bot owner.")
        return

    logger.info(
        f"Owner ({user_id}) manually triggered activity poll via /asknow.")
    await ask_activity(context)


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
                logger.info(
                    f"Activity inquiry sent to user {user_id}. Awaiting response...")
            else:
                logger.warning(
                    f"Tried to ask user {user_id} about activity, but previous response is still pending.")
        except Exception as e:
            logger.error(
                f"Error processing ask_activity for user {user_id}: {e}", exc_info=True)
            if current_user_data is not None:
                try:
                    current_user_data.pop('is_awaiting_activity', None)
                    logger.info(
                        f"Flag 'is_awaiting_activity' cleared for {user_id} due to error.")
                except Exception as cleanup_e:
                    logger.error(
                        f"Failed to clear 'is_awaiting_activity' flag for {user_id} during cleanup: {cleanup_e}")
            else:
                logger.warning(
                    f"Could not clear flag for {user_id} during cleanup, as current_user_data was not assigned.")
    else:
        logger.warning(
            "Could not send inquiry in ask_activity: user_id not found in bot_data.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    message_text = update.message.text

    if context.user_data.get('is_editing_activity'):
        logger.info(f"Received new description for editing from {user_id}")
        activity_id = context.user_data.get('editing_activity_id')
        new_description = message_text

        if activity_id is None:
            logger.error(
                f"User {user_id} sent edit text, but editing_activity_id not found in user_data.")
            await update.message.reply_text("Error: Could not find which activity to edit. Please try again.")
        else:
            was_updated = database.update_activity_description(
                activity_id, user_id, new_description)
            if was_updated:
                await update.message.reply_text(f"Activity ID {activity_id} description updated successfully.")
            else:
                await update.message.reply_text(f"Failed to update activity ID {activity_id}. It might not exist or belong to you.")

        context.user_data.pop('is_editing_activity', None)
        context.user_data.pop('editing_activity_id', None)
        return

    elif context.user_data.get('is_awaiting_activity'):
        logger.info(
            f"Received activity response from {user_id}: {message_text}")
        context.user_data['is_awaiting_activity'] = False
        description_to_save = message_text
        now = datetime.now()
        activity_id = database.save_activity_to_db(
            user_id, description_to_save, now)
        if activity_id is not None:
            reply_text = f"Acknowledged. Logged: \"{description_to_save}\" (ID: {activity_id})."
        else:
            reply_text = "Error during data persistence. Activity log potentially incomplete."
        await update.message.reply_text(reply_text)
        return
    else:
        logger.info(
            f"Received standard message from {user.id} (not an activity response): '{message_text}'")
        await update.message.reply_text("Processing context unclear. Use commands or reply when prompted.")


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
            datetime.strptime(context.args[0], '%Y-%m-%d')
            report_date_str = context.args[0]
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid date format. Please use YYYY-MM-DD or omit for today's report.")
            return
    else:
        logger.info(
            f"User {user_id} requested activity report without date. Sending options...")
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        today_str = today.strftime('%Y-%m-%d')
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        keyboard = [[InlineKeyboardButton("Today", callback_data=f"report_select:activity:{today_str}"), InlineKeyboardButton(
            "Yesterday", callback_data=f"report_select:activity:{yesterday_str}")], [InlineKeyboardButton("Cancel", callback_data="report_select:cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select report period:", reply_markup=reply_markup)
        return

    logger.info(
        f"User {user_id} requested activity report for {report_date_str}. Showing editable list.")
    await _show_editable_activity_report(user_id, report_date_str, update, context)


async def _show_editable_activity_report(user_id: int, report_date_str: str, update: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """Fetches activities and displays them as a message with 'Edit' buttons."""
    activities = database.get_activities_for_day(user_id, report_date_str)

    target_message = update.message if isinstance(
        update, CallbackQuery) else update.message
    is_callback = isinstance(update, CallbackQuery)

    if not activities:
        no_data_text = f"No activity records found for {report_date_str}."
        if is_callback:
            await update.edit_message_text(no_data_text)
        else:
            await target_message.reply_text(no_data_text)
        return

    report_lines = []
    keyboard = []
    report_lines.append(
        f"Activities for {report_date_str} (Click ✏️ to edit):")
    report_lines.append("-" * 20)

    for activity_id, timestamp_str, description in activities:
        try:
            ts_obj = datetime.fromisoformat(timestamp_str)
            time_str = ts_obj.strftime('%H:%M')
            short_desc = description[:50] + \
                ('...' if len(description) > 50 else '')
            report_lines.append(f"{time_str} - {short_desc}")
            keyboard.append([
                InlineKeyboardButton(
                    f"✏️ {short_desc}", callback_data=f"edit_activity:{activity_id}")
            ])
        except ValueError:
            report_lines.append(f"??:?? - {description} (Error parsing time)")
            logger.warning(
                f"Could not parse timestamp '{timestamp_str}' while showing editable report.")

    report_content = "\n".join(report_lines)
    keyboard.append([
        InlineKeyboardButton("⬇️ Download as a .txt file",
                             callback_data=f"download_report:{report_date_str}"),
        InlineKeyboardButton("Cancel / Close List",
                             callback_data="edit_activity:cancel")
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if is_callback:
        try:
            await update.edit_message_text(report_content, reply_markup=reply_markup)
        except Exception as e:
            logger.warning(
                f"Could not edit message to show editable report for user {user_id}: {e}")
            await context.bot.send_message(chat_id=user_id, text=report_content, reply_markup=reply_markup)
    else:
        await target_message.reply_text(report_content, reply_markup=reply_markup)


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    callback_data = query.data

    if not callback_data.startswith("download_report:"):
        await query.answer()

    user_id = query.from_user.id
    logger.info(
        f"Received callback_query from user {user_id} with data: {callback_data}")

    if callback_data.startswith("report_select:"):
        logger.debug(f"Handling 'report_select' callback: {callback_data}")
        parts = callback_data.split(":")

        if len(parts) >= 2 and parts[1] == 'cancel':
            logger.info(f"User {user_id} cancelled report selection.")
            try:
                await query.edit_message_text(text="Report selection cancelled.")
            except Exception as e:
                logger.warning(
                    f"Could not edit message on cancellation for user {user_id}: {e}")
                return

        elif len(parts) == 3:
            report_type = parts[1]
            selected_date_str = parts[2]
            logger.info(
                f"User {user_id} selected date {selected_date_str} for {report_type} report via button.")
            try:
                await query.edit_message_text(text=f"Generating {report_type} report for {selected_date_str}...")
            except Exception as e:
                logger.warning(
                    f"Could not edit message to show 'Generating...' for user {user_id}: {e}")

            if report_type == "activity":
                await _show_editable_activity_report(user_id, selected_date_str, query, context)
            else:
                logger.error(
                    f"Unknown report type '{report_type}' in callback data: {callback_data}")
                await context.bot.send_message(chat_id=user_id, text="An internal error occurred processing your request (unknown report type).")
        else:
            logger.error(
                f"Invalid 'report_select' callback data format received: {callback_data}")
            await context.bot.send_message(chat_id=user_id, text="An internal error occurred processing your request (invalid format).")

    elif callback_data.startswith("edit_activity:"):
        logger.debug(f"Handling 'edit_activity' callback: {callback_data}")

        if callback_data == "edit_activity:cancel":
            logger.info(f"User {user_id} cancelled activity editing list.")
            try:
                await query.edit_message_text(text="Closed activity list.")
            except Exception as e:
                logger.warning(
                    f"Could not edit message on edit cancellation for user {user_id}: {e}")
            return

        try:
            activity_id_to_edit = int(callback_data.split(":", 1)[1])
            context.user_data['is_editing_activity'] = True
            context.user_data['editing_activity_id'] = activity_id_to_edit
            logger.info(
                f"User {user_id} initiated editing for activity_id {activity_id_to_edit}")
            await query.edit_message_text(
                text=f"Please send the new description for activity (ID: {activity_id_to_edit}):"
            )
        except (ValueError, IndexError):
            logger.error(
                f"Could not parse activity_id from callback_data: {callback_data}")
            await query.edit_message_text(text="An error occurred. Could not initiate edit (invalid ID).")
        except Exception as e:
            logger.error(
                f"Error initiating activity edit for user {user_id}: {e}", exc_info=True)
            context.user_data.pop('is_editing_activity', None)
            context.user_data.pop('editing_activity_id', None)
            await query.edit_message_text(text="An error occurred while trying to initiate edit.")

    elif callback_data.startswith("download_report:"):
        try:
            report_date_str = callback_data.split(":", 1)[1]
            datetime.strptime(report_date_str, '%Y-%m-%d')

            logger.info(
                f"User {user_id} requested download for activity report date: {report_date_str}")
            await query.answer("Generating report file...")

            await _send_activity_report(user_id, report_date_str, query, context)

        except (ValueError, IndexError):
            logger.error(
                f"Could not parse date from download callback_data: {callback_data}")
            await query.answer("Error: Invalid data received.", show_alert=True)
        except Exception as e:
            logger.error(
                f"Error processing download report request for user {user_id}: {e}", exc_info=True)
            await query.answer("Error generating report file.", show_alert=True)

    else:
        logger.warning(f"Unhandled callback_data received: {callback_data}")
        await query.answer("This action is not recognized.", show_alert=True)

report_button_handler = report_handler
help_button_handler = help_command
hide_keyboard_button_handler = hide_keyboard_handler
