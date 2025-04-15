import logging
import io
import re
from datetime import datetime, timedelta
from telegram import (
    Update, 
    InputFile, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove,
    CallbackQuery
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

import database

logger = logging.getLogger(__name__)


def _format_tags_display(tags_concat_str: str | None) -> str:
    if not tags_concat_str:
        return "Untagged"
    tags = tags_concat_str.split(',')
    return ", ".join(f"#{tag}" for tag in tags)

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
        await reply_target.reply_document(
            document=input_file,
            caption=f"Activity Log: {report_date_str}."
        )
        logger.info(f"Merged activity report for {report_date_str} sent successfully to user {user_id}.")
    except Exception as e:
        logger.error(f"Error sending merged activity report file to user {user_id}: {e}", exc_info=True)
        await reply_target.reply_text("Could not send the merged activity report file. Please try again later.")


async def _send_tag_report(user_id: int, report_date_str: str, query: Update | CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Generating merged tag report for user {user_id}, date {report_date_str}.")
    activities_with_tags = database.get_activities_with_tags_for_day(user_id, report_date_str)

    reply_target = query.message if isinstance(query, CallbackQuery) else query.message

    if not activities_with_tags:
        await reply_target.reply_text(f"No activity records found for {report_date_str}.")
        return

    report_lines = []
    report_lines.append(f"Merged Tag Allocation Report: {report_date_str}")
    report_lines.append("=" * 30)

    if activities_with_tags:
        start_block_ts_str, current_tags_concat = activities_with_tags[0]
        start_block_dt = datetime.fromisoformat(start_block_ts_str)
        for i in range(1, len(activities_with_tags)):
            next_ts_str, next_tags_concat = activities_with_tags[i]
            next_dt = datetime.fromisoformat(next_ts_str)
            if next_tags_concat != current_tags_concat:
                end_block_dt = next_dt
                tags_display = _format_tags_display(current_tags_concat)
                report_lines.append(f"{start_block_dt.strftime('%H:%M')} - {end_block_dt.strftime('%H:%M')} - {tags_display}")
                start_block_dt = next_dt
                current_tags_concat = next_tags_concat
        tags_display = _format_tags_display(current_tags_concat)
        report_lines.append(f"{start_block_dt.strftime('%H:%M')} -       - {tags_display}")

    report_content = "\n".join(report_lines)
    report_file = io.StringIO(report_content)
    filename = f"tag_report_merged_{report_date_str}.txt"

    try:
        report_file.seek(0)
        input_file = InputFile(report_file, filename=filename)
        await reply_target.reply_document(
            document=input_file,
            caption=f"Tag Allocation Report: {report_date_str}."
        )
        logger.info(f"Merged tag report for {report_date_str} sent successfully to user {user_id}.")
    except Exception as e:
        logger.error(f"Error sending merged tag report file to user {user_id}: {e}", exc_info=True)
        await reply_target.reply_text("Could not send the merged tag report file. Please try again later.")

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
        [KeyboardButton("🏷️ List Tags"), KeyboardButton("📊 Activity Report")],
        [KeyboardButton("📈 Tag Report"), KeyboardButton("❓ Help / Show Menu")],
        [KeyboardButton("⌨️ Hide Keyboard")]
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Use menu or reply to questions..."
    )

    info_text = (
        f"User {user.mention_html()} identified. Reviewing operational parameters.\n\n"
        f"<b>Objective:</b> Meticulous time and activity logging.\n"
        f"<b>Procedure:</b> Respond accurately to periodic activity inquiries (approx. every 30 min, 08:00-23:00 local time).\n"
        f"<b>Input format:</b> Activity description. Optional: <code>#Tag_Name</code> for categorization.\n\n"
        f"Use the keyboard below or type commands directly."
        f"Ensure compliance."
    )
    await update.message.reply_html(info_text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user_id} requested directive summary.")

    keyboard = [
        [KeyboardButton("🏷️ List Tags"), KeyboardButton("📊 Activity Report")],
        [KeyboardButton("📈 Tag Report"), KeyboardButton("❓ Help / Show Menu")],
        [KeyboardButton("⌨️ Hide Keyboard")]
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Use menu or reply to questions..."
    )

    info_text = (
        f"<b>Available directives:</b>\n"
        f"/addtag &lt;name&gt; - Register a new category tag.\n"
        f"/listtags - Display currently registered tags.\n"
        f"/deltag &lt;name&gt; - Remove a registered tag.\n"
        f"/report [YYYY-MM-DD] - Generate activity log (default: today).\n"
        f"/tag_report [YYYY-MM-DD] - Generate tag allocation log (default: today).\n"
    )
    await update.message.reply_html(info_text, reply_markup=reply_markup)

async def hide_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to hide reply keyboard.")
    await update.message.reply_text(
        "Custom keyboard hidden. Use /start or /help to show it again.",
        reply_markup=ReplyKeyboardRemove()
    )


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
                await context.bot.send_message(
                    chat_id=user_id,
                    text="Report current activity."
                )
                current_user_data['is_awaiting_activity'] = True
                logger.info(f"Activity inquiry sent to user {user_id}. Awaiting response...")
            else:
                logger.warning(f"Attempted to inquire activity from user {user_id}, but previous response is still pending.")

        except Exception as e:
            logger.error(f"Error processing ask_activity for user {user_id}: {e}", exc_info=True)
            if current_user_data is not None:
                 try:
                     current_user_data.pop('is_awaiting_activity', None)
                     logger.info(f"Flag 'is_awaiting_activity' cleared for {user_id} due to error.")
                 except Exception as cleanup_e:
                     logger.error(f"Failed to clear 'is_awaiting_activity' flag for {user_id} during cleanup: {cleanup_e}")
            else:
                 logger.warning(f"Could not clear flag for {user_id} during cleanup, as current_user_data was not assigned.")
    else:
        logger.warning("Could not send inquiry in ask_activity: user_id not found in bot_data.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    message_text = update.message.text

    if context.user_data.get('is_awaiting_activity'):
        logger.info(f"Received activity response from {user_id}: {message_text}")

        context.user_data['is_awaiting_activity'] = False

        found_hashtags = re.findall(r"#(\w+)", message_text)
        tag_names_from_message = [tag.lower() for tag in found_hashtags]
        logger.debug(f"Hashtags parsed from message: {tag_names_from_message}")

        description_to_save = message_text
        now = datetime.now()
        activity_id = database.save_activity_to_db(user_id, description_to_save, now)

        linked_tags = []
        ignored_tags = []

        if activity_id is not None:
            if tag_names_from_message:
                for tag_name in tag_names_from_message:
                    tag_id = database.get_tag_id(user_id, tag_name)
                    if tag_id is not None:
                        if database.link_activity_tag(activity_id, tag_id):
                            linked_tags.append(tag_name)
                        else:
                            ignored_tags.append(tag_name)
                            logger.error(f"Failed to link tag '{tag_name}' (ID: {tag_id}) to activity_id {activity_id}")
                    else:
                        ignored_tags.append(tag_name)
                        logger.info(f"Tag '{tag_name}' provided by user {user_id} was not found in their tag registry.")

            reply_parts = [f"Acknowledged. Logged: \"{description_to_save}\" (ID: {activity_id})."]
            if linked_tags:
                reply_parts.append(f"Applied tags: {', '.join(['#' + t for t in linked_tags])}.")
            if ignored_tags:
                reply_parts.append(f"Unrecognized tags ignored: {', '.join(['#' + t for t in ignored_tags])}.")
            reply_text = " ".join(reply_parts)

        else:
            reply_text = "Error during data persistence. Activity log potentially incomplete."

        await update.message.reply_text(reply_text)

    else:
        logger.info(f"Received standard message from {user.id} (not an activity response): '{message_text}'")


async def add_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    if not context.args:
        await update.message.reply_text("Directive /addtag requires parameter: <tag_name>.")
        return

    tag_name = context.args[0]

    if len(tag_name) > 50:
         await update.message.reply_text("Input rejected. Tag name exceeds maximum length (50 characters).")
         return
    if '#' in tag_name or ' ' in tag_name:
         await update.message.reply_text("Input rejected. Tag name must not contain spaces or '#' symbol.")
         return

    logger.info(f"User {user_id} attempting to register tag: '{tag_name}'")
    tag_id = database.add_tag(user_id, tag_name)

    if tag_id is not None:
        await update.message.reply_text(f"Tag '{tag_name.lower()}' registered or verified (ID: {tag_id}).")
    else:
        await update.message.reply_text(f"Operation failed. Could not register tag '{tag_name.lower()}'. System error logged.")

async def list_tags_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user_id} requested tag registry list.")
    tags_list = database.get_user_tags(user_id)

    if not tags_list:
        reply_text = "No tags currently registered. Use /addtag <tag_name>."
        await update.message.reply_text(reply_text)
        return
    """
    else:
        tags_formatted = "\n".join(f"- {tag}" for tag in tags_list)
        reply_text = "Registered tags:\n" + tags_formatted
    """
    keyboard = []
    for tag_name in tags_list:
        callback_data_string = f"delete_tag:{tag_name}"
        button = InlineKeyboardButton(f"🗑️ #{tag_name}", callback_data=callback_data_string)
        keyboard.append([button])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Your registered tags (click to delete):", reply_markup=reply_markup)


async def delete_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    if not context.args:
        await update.message.reply_text("Directive /deltag requires parameter: <tag_name>.")
        return

    tag_name = context.args[0]
    tag_name_lower = tag_name.lower()
    logger.info(f"User {user_id} attempting to deregister tag: '{tag_name_lower}'")
    was_deleted = database.delete_tag(user_id, tag_name_lower)

    if was_deleted:
        await update.message.reply_text(f"Tag '{tag_name_lower}' successfully deregistered.")
    else:
        await update.message.reply_text(f"Tag '{tag_name_lower}' not found in your registry.")

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    user_id = query.from_user.id

    logger.info(f"Received callback_query from user {user_id} with data: {callback_data}")

    if callback_data.startswith("delete_tag:"):
        tag_name_to_delete = callback_data.split(":", 1)[1]
        logger.info(f"User {user_id} requested deletion of tag '{tag_name_to_delete}' via button.")

        was_deleted = database.delete_tag(user_id, tag_name_to_delete)

        if was_deleted:
            new_tags_list = database.get_user_tags(user_id)
            if not new_tags_list:
                 new_text = "You don't have any tags left."
                 new_reply_markup = None
            else:
                 new_keyboard = []
                 for tag_name in new_tags_list:
                     callback_data_string = f"delete_tag:{tag_name}"
                     button = InlineKeyboardButton(f"🗑️ #{tag_name}", callback_data=callback_data_string)
                     new_keyboard.append([button])
                 new_reply_markup = InlineKeyboardMarkup(new_keyboard)
                 new_text = "Tag deleted. Remaining tags (click to delete):"

            try:
                await query.edit_message_text(text=new_text, reply_markup=new_reply_markup)
            except Exception as e:
                 logger.warning(f"Could not edit message after tag deletion for user {user_id}: {e}")
                 await context.bot.send_message(chat_id=user_id, text=f"Tag '{tag_name_to_delete}' deleted. Use /listtags to see the updated list.")
        else:
            await query.edit_message_text(text=f"Could not delete tag '{tag_name_to_delete}'. It might have been already deleted.")

    elif callback_data.startswith("report_select:"):
        parts = callback_data.split(":")
        # report_select : report_type : date_str

        if len(parts) >= 2 and parts[1] == 'cancel':
            logger.info(f"User {user_id} cancelled report selection.")
            try:
                await query.edit_message_text(text="Report selection cancelled.")
            except Exception as e:
                logger.warning(f"Could not edit message on cancellation for user {user_id}: {e}")
            return

        if len(parts) == 3:
            report_type = parts[1]
            selected_date_str = parts[2]


            logger.info(f"User {user_id} selected date {selected_date_str} for {report_type} report via button.")

            try:
                await query.edit_message_text(text=f"Generating {report_type} report for {selected_date_str}...")
            except Exception as e:
                 logger.warning(f"Could not edit message to show 'Generating...' for user {user_id}: {e}")

            if report_type == "activity":
                await _send_activity_report(user_id, selected_date_str, query, context)
            elif report_type == "tag":
                await _send_tag_report(user_id, selected_date_str, query, context)
            elif selected_date_str == 'cancel':
                await query.edit_message_text(text="Report selection cancelled.")
                return
            else:
                logger.error(f"Unknown report type '{report_type}' in callback data: {callback_data}")
                await context.bot.send_message(chat_id=user_id, text="An internal error occurred processing your request.")

        else:
            logger.error(f"Invalid callback data format received: {callback_data}")
            await context.bot.send_message(chat_id=user_id, text="An internal error occurred.")
    # -------------------------------------------------

    # else: # Другие возможные callback'и
    #     logger.warning(f"Unhandled callback_data received: {callback_data}")




async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id =  update.effective_user.id
    report_date_str = None

    if context.args:
        try:
            datetime.strptime(context.args[0], '%Y-%m-%d')
            report_date_str = context.args[0]
            logger.info(f"User {user_id} requested activity report for specific date: {report_date_str}.")
            await _send_activity_report(user_id, report_date_str, update, context)
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid date format. Please use YYYY-MM-DD or omit for today's report.")
            return
    else:
        logger.info(f"User {user_id} requested activity report without date. Sending options...")
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        today_str = today.strftime('%Y-%m-%d')
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        keyboard = [
            [
                InlineKeyboardButton("Today", callback_data=f"report_select:activity:{today_str}"),
                InlineKeyboardButton("Yesterday", callback_data=f"report_select:activity:{yesterday_str}"),
                InlineKeyboardButton("Cancel", callback_data="report_select:cancel")
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select report period:", reply_markup=reply_markup)


async def tag_report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    report_date_str = None

    if context.args:
        try:
            datetime.strptime(context.args[0], '%Y-%m-%d')
            report_date_str = context.args[0]
            logger.info(f"User {user_id} requested tag report for specific date: {report_date_str}.")
            await _send_tag_report(user_id, report_date_str, update, context)
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid date format. Please use YYYY-MM-DD or omit for date selection.")
            return
    else:
        logger.info(f"User {user_id} requested tag report without date. Sending options...")
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        today_str = today.strftime('%Y-%m-%d')
        yesterday_str = yesterday.strftime('%Y-%m-%d')

        keyboard = [
            [
                InlineKeyboardButton("Today", callback_data=f"report_select:tag:{today_str}"),
                InlineKeyboardButton("Yesterday", callback_data=f"report_select:tag:{yesterday_str}"),
                InlineKeyboardButton("Cancel", callback_data="report_select:cancel")
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select report period:", reply_markup=reply_markup)




list_tags_button_handler = list_tags_handler
report_button_handler = report_handler
tag_report_button_handler = tag_report_handler
help_button_handler = help_command
hide_keyboard_button_handler = hide_keyboard_handler    