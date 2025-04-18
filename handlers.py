import asyncio
import logging
import io
import os
from datetime import datetime, timezone, timedelta
import zoneinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
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

def _get_user_local_time(user_id: int, dt_utc_aware: datetime) -> datetime:
    tz_str = database.get_user_timezone_str(user_id)
    if tz_str:
        try:
            user_tz = ZoneInfo(tz_str)
            return dt_utc_aware.astimezone(user_tz)
        except ZoneInfoNotFoundError:
            logger.error(
                f"Invalid timezone string '{tz_str}' found in DB for user {user_id}. Falling back to UTC.")
            return dt_utc_aware
        except Exception as e:
            logger.error(
                f"Error converting time for user {user_id} with tz '{tz_str}': {e}")
            return dt_utc_aware
    else:
        logger.debug(
            f"No timezone set for user {user_id}. Returning UTC time.")
        return dt_utc_aware


async def _send_activity_report(user_id: int, report_date_str: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"Generating activity report file for user {user_id}, date {report_date_str}.")
    activities = database.get_activities_for_day(user_id, report_date_str)

    if not activities:
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"I couldn't find any activity records for {report_date_str}.")
        except Exception as e:
            logger.error(
                f"Failed to send 'no records' message to chat_id {chat_id}: {e}")
        return

    report_lines = []
    report_lines.append(f"Activity Log: {report_date_str}")
    report_lines.append("=" * 30)
    if activities:
        _, start_block_ts_str, current_desc = activities[0]
        start_block_dt_utc = datetime.fromisoformat(start_block_ts_str)
        start_block_dt_local = _get_user_local_time(
            user_id, start_block_dt_utc)
        for i in range(1, len(activities)):
            _, next_ts_str, next_desc = activities[i]
            next_dt_utc = datetime.fromisoformat(next_ts_str)
            next_dt_local = _get_user_local_time(user_id, next_dt_utc)
            if next_desc != current_desc:
                end_block_dt_local = next_dt_local
                report_lines.append(
                    f"{start_block_dt_local.strftime('%H:%M')} - {end_block_dt_local.strftime('%H:%M')} - {current_desc}")
                start_block_dt_local = next_dt_local
                current_desc = next_desc
        report_lines.append(
            f"{start_block_dt_local.strftime('%H:%M')} -       - {current_desc}")

    report_content = "\n".join(report_lines)
    report_file = io.StringIO(report_content)
    filename = f"activity_report_{report_date_str}.txt"
    try:
        report_file.seek(0)
        input_file = InputFile(report_file, filename=filename)
        await context.bot.send_document(
            chat_id=chat_id, document=input_file, caption=f"Here's your activity report for {report_date_str}."
        )
        logger.info(
            f"Activity report file for {report_date_str} sent successfully to chat_id {chat_id}.")
    except Exception as e:
        logger.error(
            f"Error sending activity report file to chat_id {chat_id}: {e}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=chat_id, text="😥 Sorry, I couldn't send the report file.")
        except Exception as e2:
            logger.error(
                f"Also failed to send error message to chat_id {chat_id}: {e2}")


async def _show_editable_activity_report(user_id: int, report_date_str: str, update: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    activities = database.get_activities_for_day(user_id, report_date_str)
    is_callback = isinstance(update, CallbackQuery)
    target_message = update.message if is_callback else update.message

    if not activities:
        no_data_text = f"I couldn't find any activity records for {report_date_str}."
        if is_callback:
            await update.edit_message_text(no_data_text)
        else:
            await target_message.reply_text(no_data_text)
        return

    report_lines = []
    keyboard = []
    report_lines.append(
        f"Activities for {report_date_str} (Click ✏️ to edit):")
    report_lines.append("-" * 30)
    for activity_id, timestamp_str, description in activities:
        try:
            ts_utc_aware = datetime.fromisoformat(timestamp_str)
            ts_local = _get_user_local_time(user_id, ts_utc_aware)
            time_str = ts_local.strftime('%H:%M')
            short_desc = description.strip(
            )[:50] + ('...' if len(description.strip()) > 50 else '')
            report_lines.append(f"{time_str} - {short_desc}")
            keyboard.append([InlineKeyboardButton(
                f"✏️ {short_desc}", callback_data=f"edit_activity:{activity_id}")])
        except ValueError:
            report_lines.append(f"??:?? - {description} (Error parsing time)")
            logger.warning(
                f"Could not parse timestamp '{timestamp_str}' while showing editable report.")

    report_content = "\n".join(report_lines)
    keyboard.append([InlineKeyboardButton("⬇️ Download .txt", callback_data=f"download_report:{report_date_str}"), InlineKeyboardButton(
        "Cancel / Close List", callback_data="edit_activity:cancel")])
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
    keyboard = [[KeyboardButton("📊 Activity Report")], [KeyboardButton(
        "❓ Help / Show Menu")], [KeyboardButton("⌨️ Hide Keyboard")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False,
                                       input_field_placeholder="Use menu or reply to questions...")
    info_text = (
        f"Hello, {user.mention_html()}! 👋 I'm your personal Time & Activity Tracker.\n\n"
        f"I'll check in with you roughly every half hour (8 AM - 10 PM your time) to ask what you're up to. "
        f"Just reply with your activity!\n\n"
        f"Use the menu below for common actions or type /help for a list of commands."
    )
    await update.message.reply_html(info_text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user_id} requested help.")
    keyboard = [[KeyboardButton("📊 Activity Report")], [KeyboardButton(
        "❓ Help / Show Menu")], [KeyboardButton("⌨️ Hide Keyboard")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False,
                                       input_field_placeholder="Use menu or reply to questions...")
    info_text = (
        f"Hi {user.mention_html()}! Here's how I can help:\n\n"
        f"➡️ I'll periodically ask 'What are you doing?'. Just reply with your activity.\n"
        f"➡️ Use the buttons below or type commands:\n\n"
        f"<b>Commands:</b>\n"
        f"/report [YYYY-MM-DD] - Get your activity report (default: today).\n"
        f"/set_timezone <IANA_Name> - Set your timezone (e.g., Asia/Almaty).\n"
        f"/help - Show this help message.\n"
        f"/hide_keyboard - Hide the menu buttons.\n"
        f"/asknow - (Owner) Ask for activity input now."
    )
    await update.message.reply_html(info_text, reply_markup=reply_markup)


async def ask_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if OWNER_ID == 0:
        logger.error("OWNER_ID is not set or invalid. Cannot execute /asknow.")
        await update.message.reply_text("Sorry, owner ID not configured correctly.")
        return
    if user_id != OWNER_ID:
        logger.warning(f"User {user_id} (not owner) tried to use /asknow.")
        await update.message.reply_text("Sorry, this command is restricted to the bot owner.")
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
            now_utc = datetime.now(timezone.utc)
            user_local_time = _get_user_local_time(user_id, now_utc)
            if not (8 <= user_local_time.hour <= 22):
                logger.debug(
                    f"Skipping poll for user {user_id}: Local time {user_local_time.strftime('%H:%M')} outside window.")
                return
        except Exception as time_check_e:
            logger.error(
                f"Error checking time for poll (user {user_id}): {time_check_e}", exc_info=True)
            return
        try:
            if user_id not in context.application.user_data:
                context.application.user_data[user_id] = {}
            current_user_data = context.application.user_data[user_id]
            if not current_user_data.get('is_awaiting_activity'):
                await context.bot.send_message(chat_id=user_id, text="🤔 What are you doing right now?")
                current_user_data['is_awaiting_activity'] = True
                logger.info(
                    f"Activity inquiry sent to user {user_id} at their local time {user_local_time.strftime('%H:%M')}.")
            else:
                logger.warning(
                    f"Tried to ask user {user_id}, but previous response still pending.")
        except Exception as e:
            logger.error(
                f"Error processing ask_activity for user {user_id}: {e}", exc_info=True)
            if current_user_data is not None:
                try:
                    current_user_data.pop('is_awaiting_activity', None)
                    logger.info(f"Flag cleared for {user_id} due to error.")
                except Exception as cleanup_e:
                    logger.error(
                        f"Failed to clear flag for {user_id}: {cleanup_e}")
            else:
                logger.warning(
                    f"Could not clear flag for {user_id}, user_data not assigned.")
    else:
        logger.warning(
            "Could not send inquiry: user_id not found in bot_data.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    message_text = update.message.text
    if context.user_data.get('is_editing_activity'):
        logger.info(f"Received new description for editing from {user_id}")
        activity_id = context.user_data.get('editing_activity_id')
        new_description = message_text
        reply_text = ""  # Initialize reply text
        if activity_id is None:
            logger.error(
                f"Edit text from {user_id}, but no activity_id found.")
            reply_text = "😕 Sorry, I lost track of which activity you were editing. Please try again."
        else:
            was_updated = database.update_activity_description(
                activity_id, user_id, new_description)
            if was_updated:
                reply_text = f"✅ Activity (ID: {activity_id}) updated successfully!"
            else:
                reply_text = f"😕 Failed to update activity (ID: {activity_id}). It might no longer exist or wasn't yours."
        context.user_data.pop('is_editing_activity', None)
        context.user_data.pop('editing_activity_id', None)
        await update.message.reply_text(reply_text)
        return
    elif context.user_data.get('is_awaiting_activity'):
        logger.info(
            f"Received activity response from {user_id}: {message_text}")
        context.user_data['is_awaiting_activity'] = False
        description_to_save = message_text
        now_utc = datetime.now(timezone.utc)
        activity_id = database.save_activity_to_db(
            user_id, description_to_save, now_utc)
        if activity_id is not None:
            reply_text = f"✅ Got it! Logged: \"{description_to_save}\" (ID: {activity_id})."
        else:
            reply_text = "😥 Sorry, there was an error saving your activity. Please try again later."
        await update.message.reply_text(reply_text)
        return
    else:
        logger.info(
            f"Received standard message from {user.id} (not expected): '{message_text}'")


async def set_timezone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    usage_text = ("Please provide your timezone name like Europe/London, Asia/Almaty, America/New_York.\n" "Example: `/set_timezone Asia/Almaty`\n" "List of names: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
    if not context.args:
        await update.message.reply_text(usage_text)
        return
    timezone_name = context.args[0]
    try:
        ZoneInfo(timezone_name)
        if database.update_user_timezone(user_id, timezone_name):
            logger.info(f"User {user_id} set timezone to {timezone_name}")
            await update.message.reply_text(f"👍 Timezone successfully set to: {timezone_name}")
        else:
            logger.error(f"Failed to update timezone in DB for user {user_id}")
            await update.message.reply_text("😥 Failed to save timezone setting. Please try again.")
    except ZoneInfoNotFoundError:
        logger.warning(f"User {user_id} invalid timezone: {timezone_name}")
        await update.message.reply_text(f"Hmm, I don't recognize the timezone '{timezone_name}'.\n\n{usage_text}")
    except Exception as e:
        logger.error(
            f"Error setting timezone for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("😥 An unexpected error occurred.")


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    report_date_str = None
    if context.args:
        try:
            datetime.strptime(context.args[0], '%Y-%m-%d')
            report_date_str = context.args[0]
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid date format. Please use YYYY-MM-DD or omit for date selection.")
            return
        logger.info(
            f"User {user_id} requested activity report for specific date: {report_date_str}.")
        await _show_editable_activity_report(user_id, report_date_str, update, context)
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
        await update.message.reply_text("🗓️ Select report period:", reply_markup=reply_markup)


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id
    needs_answer = True  # Assume we need to answer by default

    logger.info(
        f"Received callback_query from user {user_id} with data: {callback_data}")

    if callback_data.startswith("report_select:"):
        parts = callback_data.split(":")
        if len(parts) >= 2 and parts[1] == 'cancel':
            logger.info(f"User {user_id} cancelled report selection.")
            try:
                await query.edit_message_text(text="OK, report selection cancelled.")
            except Exception as e:
                logger.warning(f"Could not edit message on cancellation: {e}")
            needs_answer = False  # Already implicitly answered by edit_message_text or error
        elif len(parts) == 3:
            report_type = parts[1]
            selected_date_str = parts[2]
            logger.info(
                f"User {user_id} selected date {selected_date_str} for {report_type} report.")
            try:
                await query.edit_message_text(text=f"Loading {report_type} entries for {selected_date_str}...")
            except Exception as e:
                logger.warning(
                    f"Could not edit message to show 'Loading...': {e}")
            if report_type == "activity":
                await _show_editable_activity_report(user_id, selected_date_str, query, context)
            else:
                logger.error(f"Unknown report type '{report_type}'")
                await context.bot.send_message(chat_id=user_id, text="Sorry, an internal error occurred.")
            needs_answer = False  # edit_message_text implicitly answers
        else:
            logger.error(f"Invalid 'report_select' format: {callback_data}")
            await context.bot.send_message(chat_id=user_id, text="Sorry, an internal error occurred.")
            needs_answer = False
    elif callback_data.startswith("edit_activity:"):
        if callback_data == "edit_activity:cancel":
            logger.info(f"User {user_id} cancelled activity edit list.")
            try:
                await query.edit_message_text(text="OK, activity list closed.")
            except Exception as e:
                logger.warning(
                    f"Could not edit message on edit cancellation: {e}")
            needs_answer = False
        else:
            try:
                activity_id_to_edit = int(callback_data.split(":", 1)[1])
                context.user_data['is_editing_activity'] = True
                context.user_data['editing_activity_id'] = activity_id_to_edit
                logger.info(
                    f"User {user_id} initiated editing for activity_id {activity_id_to_edit}")
                await query.edit_message_text(text=f"Okay, please send the new description for activity (ID: {activity_id_to_edit}):")
                needs_answer = False
            except (ValueError, IndexError):
                logger.error(f"Could not parse activity_id: {callback_data}")
                await query.edit_message_text(text="Error: Could not initiate edit (invalid ID).")
                needs_answer = False
            except Exception as e:
                logger.error(f"Error initiating edit: {e}", exc_info=True)
                context.user_data.pop('is_editing_activity', None)
                context.user_data.pop('editing_activity_id', None)
                await query.edit_message_text(text="Sorry, an error occurred while trying to edit.")
                needs_answer = False
    elif callback_data.startswith("download_report:"):
        report_date_str = "PARSE_ERROR"
        try:
            report_date_str = callback_data.split(":", 1)[1]
            logger.info(f"Extracted date for download: '{report_date_str}'")
            parsed_date = datetime.strptime(report_date_str, '%Y-%m-%d')
            logger.info(f"Date parsed successfully: {parsed_date}")
            logger.info(
                f"User {user_id} confirmed download request for date: {report_date_str}")
            # Use answer here for quick feedback
            await query.answer("Preparing your report file...")
            needs_answer = False  # Answered the query
            await _send_activity_report(user_id, report_date_str, query.message.chat_id, context)
        except (ValueError, IndexError) as e:
            logger.error(
                f"Error parsing date '{report_date_str}' from {callback_data}: {e}", exc_info=True)
            await query.answer("Error: Invalid data received.", show_alert=True)
            needs_answer = False
        except Exception as e:
            logger.error(
                f"Error processing download request for date '{report_date_str}': {e}", exc_info=True)
            await query.answer("Sorry, error generating report file.", show_alert=True)
            needs_answer = False
    else:
        logger.warning(f"Unhandled callback_data received: {callback_data}")

    # Fallback answer if no other answer/edit was called
    if needs_answer:
        try:
            await query.answer("Action processed.")
        except Exception as e:
            logger.error(
                f"Error sending fallback answer for callback {callback_data}: {e}")


async def hide_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to hide reply keyboard.")
    await update.message.reply_text("OK, custom keyboard hidden. Use /start or /help to bring it back.", reply_markup=ReplyKeyboardRemove())

report_button_handler = report_handler
help_button_handler = help_command
hide_keyboard_button_handler = hide_keyboard_handler


async def check_and_send_daily_reports_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Running hourly check for sending daily reports.")
    user_ids_to_check = database.get_all_user_ids_with_tz()
    if not user_ids_to_check:
        logger.info("No users with timezone found to check.")
        return
    now_utc = datetime.now(timezone.utc)
    processed_users = 0
    for user_id in user_ids_to_check:
        logger.debug(f"Checking daily report status for user {user_id}.")
        try:
            user_local_time = _get_user_local_time(user_id, now_utc)
            logger.debug(
                f"User {user_id}: Calculated local time {user_local_time.strftime('%Y-%m-%d %H:%M:%S %Z%z')}")
        except Exception as e:
            logger.error(
                f"Error calculating local time for user {user_id}: {e}")
            continue
        if user_local_time.hour == 8:  # Check for 8 AM local time
            report_date_local = user_local_time.date() - timedelta(days=1)
            report_date_str = report_date_local.strftime('%Y-%m-%d')
            last_sent_date_str = database.get_last_report_sent_date(user_id)
            logger.debug(
                f"User {user_id}: Checking report for {report_date_str}, last sent was {last_sent_date_str}")
            if last_sent_date_str != report_date_str:
                logger.info(
                    f"It's report time for user {user_id} ({user_local_time.strftime('%H:%M %Z')}). Sending report for {report_date_str}.")
                try:
                    logger.debug(
                        f"Attempting to call _send_activity_report for user {user_id}, date {report_date_str}")
                    await _send_activity_report(user_id, report_date_str, user_id, context)
                    logger.debug(
                        f"Report sent, attempting to update last_sent_date for user {user_id} to {report_date_str}")
                    database.update_last_report_sent_date(
                        user_id, report_date_str)
                    processed_users += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.error(
                        f"Failed to send daily report to user {user_id} for date {report_date_str}: {e}", exc_info=False)
            else:
                logger.info(
                    f"Daily report for {report_date_str} already sent to user {user_id}. Skipping.")
        else:
            logger.debug(
                f"Not report time for user {user_id} (Local hour: {user_local_time.hour}, needed: 8)")
    if processed_users > 0:
        logger.info(
            f"Finished checking/sending daily reports. Sent to {processed_users} users.")
    else:
        logger.info(
            "Finished checking daily reports. No reports sent this hour.")
