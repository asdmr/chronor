import logging
import io
import re
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

import database

logger = logging.getLogger(__name__)


def _format_tags_display(tags_concat_str: str | None) -> str:
    """Helper function to format concatenated tags for display."""
    if not tags_concat_str:
        return "Untagged"
    tags = tags_concat_str.split(',')
    return ", ".join(f"#{tag}" for tag in tags)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name

    database.add_user_if_not_exists(user_id, username, first_name)
    logger.info(f"Checked/added user to DB: user_id={user_id}, username={username}")

    context.bot_data['user_id'] = user_id
    context.user_data.clear()
    logger.info(f"User {user_id} ({username}) started the bot. User ID stored in bot_data.")

    await update.message.reply_html(
        f"Hello, {user.mention_html()}! 👋\n\n"
        f"I am your time & activity tracking bot.\n"
        f"I will periodically ask what you are doing.\n\n"
        f"Just reply to my question with your activity. You can add #tags too!",
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
                    text="🤔 What are you doing right now?"
                )
                current_user_data['is_awaiting_activity'] = True
                logger.info(f"Activity question sent to user {user_id}. Awaiting response...")
            else:
                logger.warning(f"Tried to ask user {user_id} about activity, but previous response is still awaited.")

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
        logger.warning("Could not send question in ask_activity: user_id not found in bot_data.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    message_text = update.message.text

    if context.user_data.get('is_awaiting_activity'):
        logger.info(f"Received activity response from {user_id}: {message_text}")

        context.user_data['is_awaiting_activity'] = False

        found_hashtags = re.findall(r"#(\w+)", message_text)
        tag_names_from_message = [tag.lower() for tag in found_hashtags]
        logger.debug(f"Hashtags found in message: {tag_names_from_message}")

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
                        logger.info(f"Tag '{tag_name}' provided by user {user_id} was not found in their tag list.")

            reply_parts = [f"✅ Recorded: \"{description_to_save}\" (ID: {activity_id})"]
            if linked_tags:
                reply_parts.append(f"Tags: {', '.join(['#' + t for t in linked_tags])}")
            if ignored_tags:
                reply_parts.append(f"Unknown tags (ignored): {', '.join(['#' + t for t in ignored_tags])}")
            reply_text = "\n".join(reply_parts)

        else:
            reply_text = "❌ An error occurred while saving the activity. Tags were not linked."

        await update.message.reply_text(reply_text)

    else:
        logger.info(f"Received a regular message from {user.id} (not an activity response): '{message_text}'")


async def add_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    if not context.args:
        await update.message.reply_text("Please provide a tag name after the command.\nExample: `/addtag work`")
        return

    tag_name = context.args[0]

    if len(tag_name) > 50:
         await update.message.reply_text("Tag name is too long (max 50 characters).")
         return
    if '#' in tag_name or ' ' in tag_name:
         await update.message.reply_text("Tag name should not contain spaces or the '#' symbol.")
         return

    logger.info(f"User {user_id} trying to add tag: '{tag_name}'")
    tag_id = database.add_tag(user_id, tag_name)

    if tag_id is not None:
        await update.message.reply_text(f"✅ Tag '{tag_name.lower()}' added or already exists (ID: {tag_id}).")
    else:
        await update.message.reply_text(f"❌ Failed to add tag '{tag_name.lower()}'. An error occurred.")

async def list_tags_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user_id} requested tag list.")
    tags_list = database.get_user_tags(user_id)

    if not tags_list:
        reply_text = "You don't have any tags yet. Add one using `/addtag <tag_name>`"
    else:
        tags_formatted = "\n".join(f"• #{tag}" for tag in tags_list)
        reply_text = "Your tags:\n" + tags_formatted

    await update.message.reply_text(reply_text)

async def delete_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    if not context.args:
        await update.message.reply_text("Please provide the name of the tag you want to delete.\nExample: `/deltag work`")
        return

    tag_name = context.args[0]
    tag_name_lower = tag_name.lower()
    logger.info(f"User {user_id} trying to delete tag: '{tag_name_lower}'")
    was_deleted = database.delete_tag(user_id, tag_name_lower)

    if was_deleted:
        await update.message.reply_text(f"✅ Tag '{tag_name_lower}' deleted.")
    else:
        await update.message.reply_text(f"❓ Tag '{tag_name_lower}' not found among your tags.")


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    today_str = datetime.now().strftime('%Y-%m-%d')
    logger.info(f"User {user_id} requested activity report for {today_str}.")

    activities = database.get_activities_for_day(user_id, today_str)

    if not activities:
        await update.message.reply_text(f"No activity records found for today ({today_str}).")
        return

    report_lines = []
    report_lines.append(f"Activity Report for {today_str}")
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
    filename = f"activity_report_{today_str}.txt"

    try:
        await update.message.reply_document(
            document=report_file,
            filename=filename,
            caption=f"Activity report for {today_str}."
        )
        logger.info(f"Activity report for {today_str} sent successfully to user {user_id}.")
    except Exception as e:
        logger.error(f"Error sending activity report file to user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Could not send the activity report file. Please try again later.")


async def tag_report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    today_str = datetime.now().strftime('%Y-%m-%d')
    logger.info(f"User {user_id} requested tag report for {today_str}.")

    activities_with_tags = database.get_activities_with_tags_for_day(user_id, today_str)

    if not activities_with_tags:
        await update.message.reply_text(f"No activity records found for today ({today_str}).")
        return

    report_lines = []
    report_lines.append(f"Tag Report for {today_str}")
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
    filename = f"tag_report_{today_str}.txt"

    try:
        await update.message.reply_document(
            document=report_file,
            filename=filename,
            caption=f"Tag report for {today_str}."
        )
        logger.info(f"Tag report for {today_str} sent successfully to user {user_id}.")
    except Exception as e:
        logger.error(f"Error sending tag report file to user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Could not send the tag report file. Please try again later.")