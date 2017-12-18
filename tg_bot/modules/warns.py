import re

import telegram
from telegram import MessageEntity
from telegram.ext import CommandHandler, run_async, DispatcherHandlerStop, MessageHandler, Filters

from tg_bot import dispatcher
from tg_bot.modules.helper_funcs import user_admin, bot_admin
from tg_bot.modules.sql import warns_sql as sql
from tg_bot.modules.users import get_user_id

WARN_HANDLER_GROUP = 9


# TODO: Make a single user_id and argument extraction function! this one is inaccurate
def extract_userid(message):
    args = message.text.split(None, 2)  # use python's maxsplit to separate Cmd, warn recipient, and warn reason

    if len(args) >= 2 and args[1][0] == '@':
        user = args[1]
        user_id = get_user_id(user)
        if not user_id:
            message.reply_text("I don't have that user in my db. You'll be able to interact with them if "
                               "you reply to that person's message instead.")
            return
        return user_id, args[2]

    elif message.entities and message.parse_entities([MessageEntity.TEXT_MENTION]):
        entities = message.parse_entities([MessageEntity.TEXT_MENTION])
        for e in entities:
            return e.user.id, message.text.split(None, 1)[1]  # TODO: User entity offset here to account for split names

    elif message.reply_to_message:
        return message.reply_to_message.from_user.id, message.text.split(None, 1)[1]


@run_async
@user_admin
@bot_admin
def warn(bot, update):
    message = update.effective_message
    chat = update.effective_chat

    user_id, reason = extract_userid(message) or None, ""
    if user_id:
        user_warned = sql.warn_user(user_id, chat.id, reason)
        if user_warned.num_warns >= 3:
            # TODO: check if member is admin/creator
            res = chat.kick_member(user_id)
            if res:
                bot.send_sticker(chat.id, 'CAADAgADOwADPPEcAXkko5EB3YGYAg')  # banhammer marie sticker
                message.reply_text("3 warnings, this user has been banned!")
                sql.reset_warns(user_id, chat.id)
            else:
                message.reply_text("An error occurred, I couldn't ban this person!")
        else:
            message.reply_text("{}/3 warnings... watch out!".format(user_warned.num_warns))
    else:
        message.reply_text("No user was designated!")


@run_async
@user_admin
@bot_admin
def reset_warns(bot, update):
    message = update.effective_message
    chat = update.effective_chat

    user_id, _ = extract_userid(message) or None, None
    if user_id:
        sql.reset_warns(user_id, chat.id)
        message.reply_text("Warnings have been reset!")
    else:
        message.reply_text("No user has been designated!")


@run_async
def warns(bot, update):
    message = update.effective_message
    user_id, _ = extract_userid(message) or update.effective_user.id, None
    warned_user = sql.get_warns(user_id, update.effective_chat.id)
    if warned_user and warned_user.num_warns != 0:
        if warned_user.reasons:
            text = "This user has {} warnings, for the following reasons:".format(warned_user.num_warns)
            for reason in warned_user.reasons:
                text += "\n - {}".format(reason)
            # TODO: Check length of text to send.
            update.effective_message.reply_text(text)
        else:
            update.effective_message.reply_text(
                "User has {} warnings, but no reasons for any of them.".format(warned_user.num_warns))
    else:
        update.effective_message.reply_text("This user hasn't got any warnings!")


@run_async
@user_admin
def add_warn_filter(bot, update):
    chat = update.effective_chat
    msg = update.effective_message
    args = msg.text.split(None, 2)  # use python's maxsplit to separate Cmd, keyword, and reply_text

    if len(args) >= 3:
        keyword = args[1]
        content = args[2]

    else:
        return

    # Note: perhaps handlers can be removed somehow using sql.get_chat_filters
    for handler in dispatcher.handlers.get(WARN_HANDLER_GROUP, []):
        if handler.filters == (keyword, chat.id):
            dispatcher.remove_handler(handler, WARN_HANDLER_GROUP)

    sql.add_warn_filter(chat.id, keyword, content)

    update.effective_message.reply_text("Warn handler added for {}!".format(keyword))
    raise DispatcherHandlerStop


@run_async
@user_admin
def remove_warn_filter(bot, update, args):
    chat = update.effective_chat

    if len(args) < 1:
        return

    chat_filters = sql.get_chat_filters(chat.id)

    if not chat_filters:
        update.effective_message.reply_text("No filters are active here!")
        return

    for filt in chat_filters:
        if filt.chat_id == str(chat.id) and filt.keyword == args[0]:
            sql.remove_warn_filter(chat.id, args[0])
            update.effective_message.reply_text("Yep, I'll stop replying to that.")
            return

    update.effective_message.reply_text("That's not a current filter - run /filters for all active filters.")


@run_async
def list_warn_filters(bot, update):
    chat = update.effective_chat
    all_handlers = sql.get_chat_filters(chat.id)

    if not all_handlers:
        update.effective_message.reply_text("No filters are active here!")
        return

    filter_list = "Current warn filters in this chat:\n"
    for handler in all_handlers:
        entry = " - {}\n".format(handler.keyword)
        if len(entry) + len(filter_list) > telegram.MAX_MESSAGE_LENGTH:
            update.effective_message.reply_text(filter_list)
            filter_list = entry
        else:
            filter_list += entry

    if not filter_list == "Current warn filters in this chat:\n":
        update.effective_message.reply_text(filter_list)


@run_async
def reply_filter(bot, update):
    chat_filters = sql.get_chat_filters(update.effective_chat.id)
    message = update.effective_message
    to_match = message.text or message.caption or (message.sticker.emoji if message.sticker else None)
    if not to_match:
        return
    for filt in chat_filters:
        pattern = "( |^|[^\w])" + re.escape(filt.keyword) + "( |$|[^\w])"
        if re.search(pattern, to_match, flags=re.IGNORECASE):
            if filt.is_sticker:
                message.reply_sticker(filt.reply)
            else:
                message.reply_text(filt.reply)
            break


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


__help__ = """
 - /warn <userhandle>: warn a user. After 3 warns, the user will be banned from the group. Can also be used as a reply.
 - /resetwarn <userhandle>: reset the warnings for a user. Can also be used as a reply.
 - /warns <userhandle>: get a user's number, and reason, of warnings.
 - /addwarn <keyword> <reply message>: set a warning filter on a certain keyword
 - /nowarn <keyword>: stop a warning filter
"""

# TODO: remove warn button.
WARN_HANDLER = CommandHandler("warn", warn)
RESET_WARN_HANDLER = CommandHandler("resetwarn", reset_warns)
MYWARNS_HANDLER = CommandHandler("warns", warns)
ADD_WARN_HANDLER = CommandHandler("addwarn", add_warn_filter)
RM_WARN_HANDLER = CommandHandler("nowarn", remove_warn_filter)
LIST_WARN_HANDLER = CommandHandler("listwarn", list_warn_filters)
WARN_FILTER_HANDLER = MessageHandler(Filters.text | Filters.command | Filters.sticker | Filters.photo, reply_filter)

dispatcher.add_handler(WARN_HANDLER)
dispatcher.add_handler(RESET_WARN_HANDLER)
dispatcher.add_handler(MYWARNS_HANDLER)
dispatcher.add_handler(ADD_WARN_HANDLER)
dispatcher.add_handler(RM_WARN_HANDLER)
dispatcher.add_handler(LIST_WARN_HANDLER)
dispatcher.add_handler(WARN_FILTER_HANDLER, WARN_HANDLER_GROUP)