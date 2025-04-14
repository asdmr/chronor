import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
import re

import database

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name

    database.add_user_if_not_exists(user_id, username, first_name)
    logger.info(f"Added/checked in database: user_id = {user_id}, username = {username}")

    # saving user_id before using it in ask_activity
    context.bot_data['user_id'] = user_id
    # /start clears the 'is_awaiting_activity' flag
    context.user_data.clear()

    await update.message.reply_html(
        f"Hi, {user.mention_html()}! 👋\n\n"
        f"I track your activites and keep you doing something great!\n"
        f"I notify you to do some habits!\n"
        f"At the end of the day, I give you a daily report, so you can evaluate your productivity!\n"
    )

    # await is used before async operations
    # update.message.reply_html(...) allows to send a message with html formatting

async def ask_activity(context: ContextTypes.DEFAULT_TYPE) -> None:
    """ Sends a question about activity to user, whose id is saved in bot_data """
    bot_data = context.bot_data
    user_id = bot_data.get('user_id')
    current_user_data = None # initialized in order to avoid error while handling

    # if user is saved:
    if user_id:
        try: 
            # --- getting user_data from application ---
            if user_id not in context.application.user_data:
                context.application.user_data[user_id] = {}
            current_user_data = context.application.user_data[user_id]

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
                    f"Trying to send another message for asking activity to {user_id}, but still waiting the response for previous question")
        except Exception as e:
            logger.error(
                f"Sending a message for asking activity to {user_id} is failed: {e}", exc_info=True)
            # clearing flag in case of fault
            if current_user_data is not None:
                try:
                    current_user_data.pop('is_waiting_activity', None)
                    logger.info(f"Flag is_awaiting_activity is reset for {user_id} because of fault")
                except Exception as cleanup_e:
                    logger.error(f"Resetting the flag is_awaiting_activity for {user_id} is failed: {e}")
            else:
                logger.warning(f"Resetting the flag is_awaiting_activity for {user_id} is failed, because current_user_data is not declared")
            context.application.user_data[user_id].pop('is_awaiting_activity', None)  # means false
    # if user is not saved:
    else:
        logger.warning(
            "Sending a message is failed: user_id is not found in bot_data. User must send /start first")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ catches message as a response if bot is waiting for response, else just processing """

    user = update.effective_user
    user_id = user.id
    message_text = update.message.text

    if context.user_data.get('is_awaiting_activity'):
        logger.info(
            f"Got the response about current activity from {user.id}: {message_text}")

        context.user_data['is_awaiting_activity'] = False

        found_hashtags = re.findall(r"#(\w+)", message_text)
        tag_names_from_message = [tag.lower() for tag in found_hashtags]
        logger.debug(f"Found hashtags in message: {tag_names_from_message}")

        description_to_save = message_text

        now = datetime.now()

        activity_id = database.save_activity_to_db(user_id, description_to_save, now)

        linked_tags = []
        ignored_tags = []

        if activity_id is not None:
            if tag_names_from_message:
                for tag_name in tag_names_from_message:
                    print(tag_name)
                    tag_id = database.get_tag_id(user_id, tag_name)
                    print(tag_id)
                    if tag_id is not None:
                        if database.link_activity_tag(activity_id, tag_id):
                            linked_tags.append(tag_name)
                        else:
                            ignored_tags.append(tag_name)
                            logger.error(f"Linking the tag '{tag_name}' with tag_id {tag_id} with activity_id {activity_id} is failed")
                    else:
                        ignored_tags.append(tag_name)
                        logger.info(f"The tag '{tag_name}', mentioned by {user_id}, is not found in user tags list")
            reply_parts = [f"✅ The current activity is recorded successfully: \"{description_to_save}\""]
            if linked_tags:
                reply_parts.append(f"Tags: {', '.join(['#' + t for t in linked_tags])}")
            if ignored_tags:
                reply_parts.append(f"Ignored tags: {', '.join(['#' + t for t in ignored_tags])}")
            reply_text = "\n".join(reply_parts)
        else:
            reply_text = "❌ Recording the current activity failed. Try later"
        
        await update.message.reply_text(reply_text)
    else:
        logger.info(f"Got regular message from {user.id}: {message_text}")

async def add_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ handles tag creation """
    user = update.effective_user
    user_id = user.id
    
    if not context.args:
        await update.message.reply_text("Please, write name of a tag after command. \nExample: '/addtag study'")

    # TODO: support multiple word tags

    tag_name = context.args[0]

    if len(tag_name) > 50:
        await update.message.reply_text("Too long tag name (maximum 50 characters)")
        return
    if '#' in tag_name or ' ' in tag_name:
        await update.message.reply_text("Tag name should not contain any spaces or hashtag #")
        return
    
    logger.info(f"User {user_id} is trying to add tag: '{tag_name}'")

    tag_id = database.add_tag(user_id, tag_name)

    if tag_id is not None:
        await update.message.reply_text(f"✅ The tag '{tag_name.lower()}' is successfully added")
    else:
        await update.message.reply_text(f"❌ Adding tag '{tag_name.lower()}' is failed")

    
    logger.info(f"The tag '{tag_name.lower()}' is added or already exists for user {user_id} with tag_id: {tag_id}")

async def list_tags_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ returns list of created tags """
    
    user = update.effective_user
    user_id = user.id
    
    logger.info(f"User {user_id} requests list of tags")

    tags_list = database.get_user_tags(user_id)

    if not tags_list:
        reply_text = "You don't have any tags. Use /addtag 'name of tag'"
    else:
        tags_formatted = "\n".join(f"• #{tag}" for tag in tags_list)
        reply_text = "Your tags:\n" + tags_formatted
    
    await update.message.reply_text(reply_text)

    

async def delete_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ handles tag deletion """

    user = update.effective_user
    user_id = user.id

    if not context.args:
        await update.message.reply_text("Please, write name of tag that you want to delete.\nExample: '/deltag' study")
        return
    
    tag_name = context.args[0]
    tag_name_lower = tag_name.lower()

    logger.info(f"User {user_id} attemps to delete tag '{tag_name_lower}'")

    was_deleted = database.delete_tag(user_id, tag_name_lower)

    if was_deleted:
        await update.message.reply_text(f"✅ The tag '{tag_name_lower}' is successfully deleted.")
    else:
        await update.message.reply_text(f"❓ The tag '{tag_name_lower}' is not found.")
