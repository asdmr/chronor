"""
Callback handlers for the Telegram bot commands, messages, and buttons.
"""
import asyncio
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone

# Third-party imports
import zoneinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from telegram import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                      InputFile, KeyboardButton, ReplyKeyboardRemove,
                      ReplyKeyboardMarkup, Update)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import Forbidden

# Local application imports
import database

logger = logging.getLogger(__name__)

# --- Constants / Config ---
try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    if OWNER_ID == 0:
        logger.warning(
            "OWNER_ID not set in .env file. "
            "Owner-restricted commands may not function correctly."
        )
except ValueError:
    logger.error("Invalid OWNER_ID format in .env file. Must be integer.")
    OWNER_ID = 0

DEFAULT_POLL_START_HOUR = 8
DEFAULT_POLL_END_HOUR = 22
DEFAULT_REPORT_HOUR = 8


# --- Helper Functions ---

def _get_user_local_time(user_id: int, dt_utc_aware: datetime) -> datetime:
    """Converts a timezone-aware UTC datetime to the user's local timezone."""
    tz_str = database.get_user_timezone_str(user_id)
    if tz_str:
        try:
            user_tz = ZoneInfo(tz_str)
            return dt_utc_aware.astimezone(user_tz)
        except ZoneInfoNotFoundError:
            logger.error(
                f"Invalid timezone '{tz_str}' in DB for user {user_id}. Using UTC."
            )
            return dt_utc_aware
        except Exception as e:
            logger.error(f"Error converting time for user {user_id}: {e}")
            return dt_utc_aware
    else:
        logger.debug(f"No timezone set for user {user_id}. Using UTC.")
        return dt_utc_aware


async def _send_activity_report(
        user_id: int, report_date_str: str, chat_id: int,
        context: ContextTypes.DEFAULT_TYPE
):
    """Fetches, formats, and sends the activity report document."""
    logger.info(
        f"Generating an activity report file for user {user_id}, "
        f"date {report_date_str}."
    )
    # DB function returns list of (activity_id, timestamp_str_utc, description)
    activities = database.get_activities_for_day(user_id, report_date_str)

    if not activities:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"I couldn't find any activity records for {report_date_str}."
            )
        except Exception as e:
            logger.error(
                f"Failed to send 'no records' message to chat_id {chat_id}: {e}"
            )
        return

    report_lines = []
    report_lines.append(f"The Activity Log: {report_date_str}")
    report_lines.append("=" * 30)

    # Use first activity to initialize the block
    _, start_block_ts_str, current_desc = activities[0]
    start_block_dt_utc = datetime.fromisoformat(start_block_ts_str)
    start_block_dt_local = _get_user_local_time(user_id, start_block_dt_utc)

    for i in range(1, len(activities)):
        _, next_ts_str, next_desc = activities[i]
        next_dt_utc = datetime.fromisoformat(next_ts_str)
        next_dt_local = _get_user_local_time(user_id, next_dt_utc)

        # If description changes, close the previous block
        if next_desc != current_desc:
            end_block_dt_local = next_dt_local
            report_lines.append(
                f"{start_block_dt_local.strftime('%H:%M')} - "
                f"{end_block_dt_local.strftime('%H:%M')} - {current_desc}"
            )
            # Start new block
            start_block_dt_local = next_dt_local
            current_desc = next_desc

    # Add the final block after the loop
    report_lines.append(
        f"{start_block_dt_local.strftime('%H:%M')} -       - {current_desc}"
    )

    report_content = "\n".join(report_lines)
    report_file = io.StringIO(report_content)
    filename = f"activity_report_{report_date_str}.txt"

    try:
        report_file.seek(0)
        input_file = InputFile(report_file, filename=filename)
        await context.bot.send_document(
            chat_id=chat_id,
            document=input_file,
            caption=f"Here's your activity report for {report_date_str}."
        )
        logger.info(
            f"Activity report file for {report_date_str} sent to chat_id {chat_id}."
        )
    except Exception as e:
        logger.error(
            f"Error sending activity report file to chat_id {chat_id}: {e}",
            exc_info=True
        )
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="😥 Sorry, I couldn't send the report file."
            )
        except Exception as e2:
            logger.error(
                f"Also failed to send error msg to chat_id {chat_id}: {e2}")


async def _show_editable_activity_report(
        user_id: int, report_date_str: str, update: Update | CallbackQuery,
        context: ContextTypes.DEFAULT_TYPE
):
    """Fetches activities and shows them with Edit/Download buttons."""
    # DB function returns list of (activity_id, timestamp_str_utc, description)
    activities = database.get_activities_for_day(user_id, report_date_str)

    is_callback = isinstance(update, CallbackQuery)
    target_message = update.message if is_callback else update.message

    if not activities:
        no_data_text = f"I couldn't find any activity records for {report_date_str}."
        try:
            if is_callback:
                await update.edit_message_text(no_data_text)
            else:
                await target_message.reply_text(no_data_text)
        except Exception as e:  # Handle potential error if original message was deleted
            logger.warning(f"Could not edit/reply for 'no records': {e}")
            # Send new message as fallback
            await context.bot.send_message(chat_id=user_id, text=no_data_text)
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
            # Ensure short_desc doesn't start/end with whitespace for cleaner look
            desc_stripped = description.strip()
            short_desc = desc_stripped[:50] + \
                ('...' if len(desc_stripped) > 50 else '')
            report_lines.append(f"{time_str} - {short_desc}")
            keyboard.append([
                InlineKeyboardButton(
                    f"✏️ {short_desc}",
                    callback_data=f"edit_activity:{activity_id}"
                )
            ])
        except ValueError:
            report_lines.append(f"??:?? - {description} (Error parsing time)")
            logger.warning(
                f"Could not parse timestamp '{timestamp_str}' for editable report."
            )

    report_content = "\n".join(report_lines)
    keyboard.append([
        InlineKeyboardButton(
            "⬇️ Download .txt",
            callback_data=f"download_report:{report_date_str}"
        ),
        InlineKeyboardButton(
            "Cancel",
            callback_data="edit_activity:cancel"
        )
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if is_callback:
            await update.edit_message_text(report_content, reply_markup=reply_markup)
        else:
            await target_message.reply_text(report_content, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(
            f"Could not edit/reply message for editable report {user_id}: {e}"
        )
        # Send new message as fallback if edit/reply fails
        await context.bot.send_message(
            chat_id=user_id, text=report_content, reply_markup=reply_markup
        )


# --- Command and Message Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start: registers user, shows welcome and keyboard."""
    if not update.effective_user:
        return  # Should not happen in private chat
    user = update.effective_user
    user_id = user.id

    database.add_user_if_not_exists(user_id, user.username, user.first_name)
    logger.info(f"User checked/added: id={user_id}, username={user.username}")

    # Store user_id for single-user polling job target (can be improved for multi-user)
    context.bot_data['user_id'] = user_id
    context.user_data.clear()  # Clear any previous state
    logger.info(f"User {user_id} session initiated. ID stored in bot_data.")

    keyboard = [
        [KeyboardButton("📊 Activity Report")],
        [KeyboardButton("🌐 Set Timezone"),
         KeyboardButton("⏰ Set Poll Window")],
        [KeyboardButton("🗓️ Set Report Time"),
         KeyboardButton("❓ Help / Show Menu")],
        [KeyboardButton("⌨️ Hide Keyboard")]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=False,
        input_field_placeholder="Use menu or reply to questions..."
    )

    info_text = (
        f"Hello, {user.mention_html()}! 👋 I'm your personal Time & Activity Tracker.\n\n"
        "I'll check in periodically to ask what you're up to. Just reply!\n\n"
        "Use the menu below or type /help for commands."
    )
    await update.message.reply_html(info_text, reply_markup=reply_markup)

    # Check timezone and prompt if needed
    user_tz = database.get_user_timezone_str(user_id)
    if not user_tz:
        logger.info(f"User {user_id} has no timezone set. Prompting.")
        tz_link_url = "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
        timezone_prompt_text = (
            "⚠️ **Action needed: Set your timezone!**\n\n"
            "This helps me send prompts and reports at the correct local time.\n\n"
            "Use: <code>/set_timezone Your/Timezone</code>\n"
            "(e.g., <code>/set_timezone Asia/Almaty</code>)\n\n"
            f"Find the name of your timezone <a href=\"{tz_link_url}\">here</a>."
        )
        await update.message.reply_html(
            timezone_prompt_text, disable_web_page_preview=True
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /help: shows command summary and keyboard."""
    if not update.effective_user:
        return
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user_id} requested help.")

    keyboard = [
        [KeyboardButton("📊 Activity Report")],
        [KeyboardButton("🌐 Set Timezone"),
         KeyboardButton("⏰ Set Poll Window")],
        [KeyboardButton("🗓️ Set Report Time"),
         KeyboardButton("❓ Help / Show Menu")],
        [KeyboardButton("⌨️ Hide Keyboard")]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=False,
        input_field_placeholder="Use menu or reply to questions..."
    )

    tz_link_url = "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
    info_text = (
        f"Hi {user.mention_html()}! Here's a summary:\n\n"
        "➡️ I'll ask 'What are you doing?'. Just reply.\n"
        "➡️ Use the menu buttons or type commands:\n\n"
        "<b>Commands:</b>\n"
        "<code>/report [YYYY-MM-DD]</code> - Get activity report.\n"
        "<code>/set_timezone &lt;IANA_Name&gt;</code> - Set your timezone.\n"
        f"You can find the name of your timezone <a href='{tz_link_url}'>here</a>.\n"
        "<code>/set_poll_window &lt;start&gt; &lt;end&gt;</code> - Set polling hours (0-23).\n"
        "<code>/set_report_time &lt;hour&gt;</code> - Set daily report hour (0-23).\n"
        "<code>/help</code> - Show this summary.\n"
        "<code>/hide_keyboard</code> - Hide menu buttons.\n"
    )
    await update.message.reply_html(
        info_text, reply_markup=reply_markup, disable_web_page_preview=True
    )


async def ask_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /asknow: manually triggers activity poll (owner only)."""
    if not update.effective_user:
        return
    user_id = update.effective_user.id

    # Check if OWNER_ID is valid before comparing
    if not isinstance(OWNER_ID, int) or OWNER_ID == 0:
        logger.error("OWNER_ID not set or invalid. Cannot execute /asknow.")
        await update.message.reply_text("Sorry, owner ID not configured.")
        return

    if user_id != OWNER_ID:
        logger.warning(f"User {user_id} (not owner) tried /asknow.")
        await update.message.reply_text("Restricted command.")
        return

    logger.info(f"Owner ({user_id}) triggered activity poll via /asknow.")
    await ask_activity(context)
    # Optional confirmation:
    # await update.message.reply_text("Manual activity poll initiated.")


async def ask_activity(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job: Polls all users with a timezone set about their activity."""
    logger.info("Running scheduled activity poll job for relevant users.")

    user_ids_to_poll = database.get_all_user_ids_with_tz()

    if not user_ids_to_poll:
        logger.info("No users with timezone found to poll.")
        return

    logger.info(f"Found {len(user_ids_to_poll)} users to check for polling.")
    polled_count = 0
    now_utc = datetime.now(timezone.utc)

    # Use bot_data for storing a flag
    poll_states = context.bot_data.setdefault('user_poll_state', {})

    for user_id in user_ids_to_poll:
        logger.debug(f"Checking user {user_id} for activity poll.")

        # To ensure failure for one user doesn't stop the loop for others.
        try:
            poll_window = database.get_user_poll_window(user_id)
            start_h, end_h = poll_window or (DEFAULT_POLL_START_HOUR, DEFAULT_POLL_END_HOUR)
            logger.debug(f"Using poll window {start_h}-{end_h} for user {user_id}")

            user_local_time = _get_user_local_time(user_id, now_utc)

            if not (start_h <= user_local_time.hour <= end_h):
                logger.debug(
                    f"Skipping poll for {user_id}: Local time "
                    f"{user_local_time.strftime('%H:%M')} outside window {start_h}:00-{end_h}:59."
                )
                await asyncio.sleep(0.05) # Small delay even when skipping
                continue

            # Get the user-specific data dictionary, creating it if it doesn't exist
            if not poll_states.get(user_id): # Проверяем флаг для этого user_id
                await context.bot.send_message(chat_id=user_id, text="🤔 What are you doing right now?")
                poll_states[user_id] = True # Устанавливаем флаг для этого user_id
                logger.info(
                    f"Activity inquiry sent to user {user_id} "
                    f"at their local time {user_local_time.strftime('%H:%M')}."
                )
                polled_count += 1
            else:
                # Avoid spamming if user hasn't replied to the previous prompt
                logger.warning(
                    f"Tried asking user {user_id}, but previous response still pending."
                )

            # Pause briefly between users to respect potential rate limits
            await asyncio.sleep(0.1)

        except Forbidden:
            # Handle cases where the bot is blocked by the user
            logger.warning(
                f"User {user_id} has blocked the bot. Cannot send activity prompt."
            )
            poll_states.pop(user_id, None) # Reset the flag
        except Exception as e:
            # Catch any other error during processing for this specific user
            logger.error(
                f"Error processing user {user_id} in ask_activity job: {e}",
                exc_info=True # Include traceback for unexpected errors
            )
            poll_states.pop(user_id, None) # Reset the flag

    logger.info(f"Finished activity poll job. Sent prompts to {polled_count} users.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles user messages: processes activity replies or edits."""
    if not update.message or not update.effective_user:
        return  # Ignore channel posts etc.
    user = update.effective_user
    user_id = user.id
    message_text = update.message.text

    # 1. Check if user is editing an activity
    if context.user_data.get('is_editing_activity'):
        logger.info(f"Received new description for editing from {user_id}")
        activity_id = context.user_data.get('editing_activity_id')
        new_description = message_text
        reply_text = ""

        if activity_id is None:
            logger.error(
                f"Edit text from {user_id}, but no activity_id in user_data.")
            reply_text = "😕 Sorry, I lost track. Please start the edit again via /report."
        else:
            was_updated = database.update_activity_description(
                activity_id, user_id, new_description)
            if was_updated:
                reply_text = f"✅ Activity updated!"
            else:
                reply_text = f"😕 Failed to update activity. Not found?"

        # Clean up state regardless of success
        context.user_data.pop('is_editing_activity', None)
        context.user_data.pop('editing_activity_id', None)
        await update.message.reply_text(reply_text)
        return  # IMPORTANT: Stop processing here
    
    poll_states = context.bot_data.setdefault('user_poll_state', {})
    if poll_states.get(user_id):
        logger.info(
            f"Received activity response from {user_id}: {message_text}")
        poll_states.pop(user_id, None)
        
        description_to_save = message_text
        now_utc = datetime.now(timezone.utc)  # Store time in UTC

        activity_id = database.save_activity_to_db(
            user_id, description_to_save, now_utc)

        if activity_id is not None:
            reply_text = f"✅ Got it! Logged: \"{description_to_save}\"."
        else:
            reply_text = "😥 Sorry, error saving activity."
        await update.message.reply_text(reply_text)
        return  # IMPORTANT: Stop processing here

    # 3. Handle other messages (currently ignored)
    else:
        logger.info(
            f"Received unexpected message from {user_id}: '{message_text}'")
        # Optionally reply: await update.message.reply_text("Use commands or reply when prompted.")


async def set_timezone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /set_timezone command."""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    usage_text = (
        "Please provide your timezone name (e.g., Europe/London, Asia/Almaty).\n"
        "Example: `/set_timezone Asia/Almaty`\n\n"
        "<a href='https://en.wikipedia.org/wiki/List_of_tz_database_time_zones'>List of timezone names</a>"
    )

    if not context.args:
        await update.message.reply_html(usage_text, disable_web_page_preview=True)
        return

    timezone_name = context.args[0]
    try:
        # Validate timezone name
        ZoneInfo(timezone_name)
        if database.update_user_timezone(user_id, timezone_name):
            logger.info(f"User {user_id} set timezone to {timezone_name}")
            await update.message.reply_text(f"👍 Timezone set to: {timezone_name}")
        else:
            logger.error(f"Failed to update timezone in DB for user {user_id}")
            await update.message.reply_text("😥 Failed to save setting.")
    except ZoneInfoNotFoundError:
        logger.warning(f"User {user_id} invalid timezone: {timezone_name}")
        await update.message.reply_html(f"Unknown timezone: '{timezone_name}'.\n\n{usage_text}", disable_web_page_preview=True)
    except Exception as e:
        logger.error(
            f"Error setting timezone for {user_id}: {e}", exc_info=True)
        await update.message.reply_text("😥 An unexpected error occurred.")


async def set_poll_window_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /set_poll_window command."""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    usage_text = (
        "Provide start & end hours (0-23) for activity polling.\n"
        "Example: <code>/set_poll_window 9 18</code> (polls 9:00 AM - 6:59 PM)"
    )

    if len(context.args) != 2:
        await update.message.reply_html(usage_text)
        return

    try:
        start_hour = int(context.args[0])
        end_hour = int(context.args[1])
        if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
            raise ValueError("Hours must be between 0 and 23.")
        if start_hour >= end_hour:
            raise ValueError("Start hour must be less than end hour.")

        if database.update_user_poll_window(user_id, start_hour, end_hour):
            logger.info(
                f"User {user_id} set poll window: {start_hour}-{end_hour}")
            await update.message.reply_text(f"✅ Poll window set: {start_hour:02d}:00 - {end_hour:02d}:59.")
        else:
            await update.message.reply_text("😥 Failed to save setting.")
    except ValueError as e:
        logger.warning(
            f"Invalid /set_poll_window input from {user_id}: {context.args} - {e}")
        await update.message.reply_html(f"Invalid input: {e}\n\n{usage_text}")
    except Exception as e:
        logger.error(
            f"Error setting poll window for {user_id}: {e}", exc_info=True)
        await update.message.reply_text("😥 An unexpected error occurred.")


async def set_report_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /set_report_time command."""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    usage_text = (
        "Provide the hour (0-23) for daily report delivery.\n"
        "Example: <code>/set_report_time 8</code> (for 8 AM local time)"
    )

    if len(context.args) != 1:
        await update.message.reply_html(usage_text)
        return

    try:
        report_hour = int(context.args[0])
        if not (0 <= report_hour <= 23):
            raise ValueError("Hour must be between 0 and 23.")

        if database.update_user_report_hour(user_id, report_hour):
            logger.info(f"User {user_id} set report hour to {report_hour}")
            await update.message.reply_text(f"✅ Daily report will be sent around {report_hour:02d}:00 local time.")
        else:
            await update.message.reply_text("😥 Failed to save setting.")
    except ValueError as e:
        logger.warning(
            f"Invalid /set_report_time input from {user_id}: {context.args} - {e}")
        await update.message.reply_html(f"Invalid input: {e}\n\n{usage_text}")
    except Exception as e:
        logger.error(
            f"Error setting report time for {user_id}: {e}", exc_info=True)
        await update.message.reply_text("😥 An unexpected error occurred.")


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /report command, showing date selection or editable report."""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    report_date_str = None

    if context.args:
        try:
            datetime.strptime(context.args[0], '%Y-%m-%d')
            report_date_str = context.args[0]
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid date format. Please use YYYY-MM-DD.")
            return
        logger.info(
            f"User {user_id} requesting report for specific date: {report_date_str}.")
        await _show_editable_activity_report(user_id, report_date_str, update, context)
    else:
        logger.info(
            f"User {user_id} requesting report without date. Sending options...")
        # Use local time for button dates if timezone is set, else UTC
        now_local = _get_user_local_time(user_id, datetime.now(timezone.utc))
        today_local = now_local.date()
        yesterday_local = today_local - timedelta(days=1)
        today_str = today_local.strftime('%Y-%m-%d')
        yesterday_str = yesterday_local.strftime('%Y-%m-%d')

        keyboard = [[
            InlineKeyboardButton(
                "Today", callback_data=f"report_select:activity:{today_str}"),
            InlineKeyboardButton(
                "Yesterday", callback_data=f"report_select:activity:{yesterday_str}")
        ], [
            InlineKeyboardButton(
                "Cancel", callback_data="report_select:cancel")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🗓️ Select report period:", reply_markup=reply_markup)


# --- Button handlers ---

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles all inline button presses."""
    if not update.callback_query or not update.effective_user:
        return
    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id
    needs_answer = True

    logger.info(f"Received callback: user={user_id}, data='{callback_data}'")

    if callback_data.startswith("report_select:"):
        parts = callback_data.split(":")
        if len(parts) >= 2 and parts[1] == 'cancel':
            logger.info(f"User {user_id} cancelled report selection.")
            try:
                await query.edit_message_text(text="OK, report selection cancelled.")
            except Exception:
                pass  # Ignore if editing fails
            needs_answer = False
        elif len(parts) == 3:
            report_type = parts[1]
            selected_date_str = parts[2]
            logger.info(
                f"User {user_id} selected date {selected_date_str} for {report_type} report.")
            try:
                await query.edit_message_text(text=f"Loading {report_type} entries for {selected_date_str}...")
            except Exception:
                pass  # Ignore if editing fails
            if report_type == "activity":
                await _show_editable_activity_report(user_id, selected_date_str, query, context)
            else:
                logger.error(f"Unknown report type '{report_type}'")
                await context.bot.send_message(chat_id=user_id, text="Sorry, internal error (report type).")
            needs_answer = False
        else:
            logger.error(f"Invalid 'report_select' format: {callback_data}")
            await context.bot.send_message(chat_id=user_id, text="Sorry, internal error (format).")
            needs_answer = False

    elif callback_data.startswith("edit_activity:"):
        if callback_data == "edit_activity:cancel":
            logger.info(f"User {user_id} cancelled activity edit list.")
            try:
                await query.edit_message_text(text="OK, activity list closed.")
            except Exception:
                pass
            needs_answer = False
        else:
            try:
                activity_id_to_edit = int(callback_data.split(":", 1)[1])
                context.user_data['is_editing_activity'] = True
                context.user_data['editing_activity_id'] = activity_id_to_edit
                logger.info(
                    f"User {user_id} initiated edit for activity_id {activity_id_to_edit}")
                await query.edit_message_text(text=f"Okay, please send the new description for activity:")
                needs_answer = False
            except (ValueError, IndexError):
                logger.error(f"Cannot parse activity_id: {callback_data}")
                await query.edit_message_text(text="Error: Invalid edit request.")
                needs_answer = False
            except Exception as e:
                logger.error(f"Error initiating edit: {e}", exc_info=True)
                context.user_data.pop('is_editing_activity', None)
                context.user_data.pop('editing_activity_id', None)
                await query.edit_message_text(text="Sorry, an error occurred.")
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
            await query.answer("Preparing your report file...")
            needs_answer = False
            await _send_activity_report(user_id, report_date_str, query.message.chat_id, context)
        except (ValueError, IndexError) as e:
            logger.error(
                f"Error parsing date '{report_date_str}' from {callback_data}: {e}")
            await query.answer("Error: Invalid data received.", show_alert=True)
            needs_answer = False
        except Exception as e:
            logger.error(
                f"Error processing download request for '{report_date_str}': {e}", exc_info=True)
            await query.answer("Sorry, error generating file.", show_alert=True)
            needs_answer = False

    else:
        logger.warning(f"Unhandled callback_data received: {callback_data}")

    # Fallback answer if necessary
    if needs_answer:
        try:
            await query.answer()  # Simple ack
        except Exception:
            pass  # Ignore if already answered


async def hide_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /hide_keyboard command."""
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to hide reply keyboard.")
    await update.message.reply_text("OK, custom keyboard hidden. Use /start or /help to bring it back.", reply_markup=ReplyKeyboardRemove())

async def set_timezone_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the 'Set Timezone' button press by showing the current timezone
    and instructions on how to set it using the command.
    """
    if not update.effective_user:
        # Should not happen in private chat, but good practice to check
        return
    user_id = update.effective_user.id
    logger.info(f"User {user_id} pressed 'Set Timezone' button.")

    # Get current setting from DB
    current_tz = database.get_user_timezone_str(user_id)

    # Prepare first part of the message
    if current_tz:
        message_part1 = f"Your currently set timezone is: <code>{current_tz}</code>\n\n"
    else:
        message_part1 = "Your timezone is not set yet.\n\n"

    # Prepare second part (instructions)
    tz_link_url = "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
    message_part2 = (
        "To set or change it, use the command followed by the timezone name.\n"
        "Example: <code>/set_timezone Asia/Almaty</code>\n\n"
        f"Find standard names (IANA format) <a href='{tz_link_url}'>here</a>."
    )

    # Send the combined message
    try:
        await update.message.reply_text(
            message_part1 + message_part2,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
         # Log error if message sending fails
         logger.error(f"Error sending timezone info message to user {user_id}: {e}")

async def set_poll_window_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the 'Set Poll Window' button press by showing current setting
    and instructions on how to set it using the command.
    """
    if not update.effective_user: return
    user_id = update.effective_user.id
    logger.info(f"User {user_id} pressed 'Set Poll Window' button.")

    # Get current setting from DB or use defaults
    window = database.get_user_poll_window(user_id)
    start_h_disp, end_h_disp = window if window else (DEFAULT_POLL_START_HOUR, DEFAULT_POLL_END_HOUR)

    # Prepare message parts
    message_part1 = (
        f"Your current polling window is set from "
        f"<code>{start_h_disp:02d}:00</code> to "
        f"<code>{end_h_disp:02d}:59</code> local time.\n\n"
    )
    message_part2 = (
        "To change it, use the command followed by start and end hours (0-23).\n"
        "Example: <code>/set_poll_window 9 18</code>"
    )

    # Send message
    try:
        await update.message.reply_text(
            message_part1 + message_part2,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error sending poll window info to user {user_id}: {e}")


async def set_report_time_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the 'Set Report Time' button press by showing current setting
    and instructions on how to set it using the command.
    """
    if not update.effective_user: return
    user_id = update.effective_user.id
    logger.info(f"User {user_id} pressed 'Set Report Time' button.")

    # Get current setting from DB or use default
    hour = database.get_user_report_hour(user_id)
    hour_disp = hour if hour is not None else DEFAULT_REPORT_HOUR

    # Prepare message parts
    message_part1 = (
        f"Your daily report is currently scheduled around "
        f"<code>{hour_disp:02d}:00</code> local time.\n\n"
    )
    message_part2 = (
        "To change it, use the command followed by the desired hour (0-23).\n"
        "Example: <code>/set_report_time 7</code> (for 7 AM)"
    )

    # Send message
    try:
        await update.message.reply_text(
            message_part1 + message_part2,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error sending report time info to user {user_id}: {e}")

# --- Button Handlers reuse command logic ---
# Use dictionary for cleaner mapping maybe? For now, direct assignment is fine.
report_button_handler = report_handler
help_button_handler = help_command
hide_keyboard_button_handler = hide_keyboard_handler
# set_timezone_button_handler is separate
# set_poll_window_button_handler is separate
# set_report_time_button_handler is separate


# --- Job function for daily reports ---
async def check_and_send_daily_reports_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job: Checks and sends daily reports to users around 8 AM local time."""
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
            report_hour_setting = database.get_user_report_hour(user_id)
            effective_report_hour = report_hour_setting if report_hour_setting is not None else DEFAULT_REPORT_HOUR
            logger.debug(
                f"User {user_id}: Local time {user_local_time.strftime('%H:%M %Z%z')}, Target report hour: {effective_report_hour}")

            if user_local_time.hour == effective_report_hour:
                report_date_local = user_local_time.date() - timedelta(days=1)
                report_date_str = report_date_local.strftime('%Y-%m-%d')
                last_sent_date_str = database.get_last_report_sent_date(
                    user_id)
                logger.debug(
                    f"User {user_id}: Checking report for {report_date_str}, last sent was {last_sent_date_str}")
                if last_sent_date_str != report_date_str:
                    logger.info(
                        f"It's report time for user {user_id}. Sending report for {report_date_str}.")
                    try:
                        logger.debug(
                            f"Attempting _send_activity_report for user {user_id}, date {report_date_str}")
                        await _send_activity_report(user_id, report_date_str, user_id, context)
                        logger.debug(
                            f"Attempting update_last_report_sent_date for user {user_id} to {report_date_str}")
                        database.update_last_report_sent_date(
                            user_id, report_date_str)
                        processed_users += 1
                        await asyncio.sleep(0.3)
                    except Exception as send_e:
                        logger.error(
                            f"Failed sending daily report to user {user_id}: {send_e}", exc_info=False)
                else:
                    logger.info(
                        f"Report for {report_date_str} already sent to user {user_id}.")
            # No need for else clause logging 'Not report time' every hour for every user
        except Exception as user_e:
            logger.error(
                f"Error processing user {user_id} in daily report job: {user_e}", exc_info=True)

    if processed_users > 0:
        logger.info(f"Finished report check. Sent to {processed_users} users.")
    # No need to log when no reports were sent this hour
