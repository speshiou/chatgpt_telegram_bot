import logging
import traceback
import html
import json
from datetime import datetime

import telegram
from telegram import BotCommand, Update, User, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ConversationHandler,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from telegram.constants import ParseMode, ChatAction

import config
import database
import chatgpt
import orders
import i18n

# setup
db = database.Database()
logger = logging.getLogger(__name__)

CHATGPT, TOP_UP, PAYMENT = range(3)

COMMANDS = [
    BotCommand("new", "Start new dialog"),
    BotCommand("mode", "Select chat mode"),
    BotCommand("balance", "Show balance"),
    BotCommand("retry", "Regenerate last bot answer"),
]

async def register_user_if_not_exists(update: Update, context: CallbackContext, user: User):
    if not db.check_if_user_exists(user.id):
        db.add_new_user(
            user.id,
            update.message.chat_id,
            username=user.username,
            first_name=user.first_name,
            last_name= user.last_name
        )

async def reply_or_edit_text(update: Update, text: str, parse_mode: ParseMode = ParseMode.HTML, reply_markup = None):
    if update.message:
        await update.message.reply_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
    else:
        query = update.callback_query
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )

async def start_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context, update.message.from_user)
    user_id = update.message.from_user.id
    print(f"language code={update.message.from_user.language_code}")
    
    _ = i18n.get_text_func(update.message.from_user.language_code)

    db.set_user_attribute(user_id, "last_interaction", datetime.now())
    db.start_new_dialog(user_id)
    
    commands_text = "".join([f"/{c.command} - {c.description}\n" for c in COMMANDS])

    reply_text = _("Hi! I'm <b>ChatGPT</b> bot powered by OpenAI GPT-3.5 API 🤖")
    reply_text += "\n\n"
    reply_text += _("<b>Commands</b>")
    reply_text += "\n"
    reply_text += commands_text
    reply_text += "\n\n"
    reply_text += _("And now... ask me anything ...")
    
    await update.message.reply_text(
        reply_text, 
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove()
        )

async def retry_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context, update.message.from_user)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    dialog_messages = db.get_dialog_messages(user_id, dialog_id=None)
    if len(dialog_messages) == 0:
        await update.message.reply_text("No message to retry 🤷‍♂️")
        return

    last_dialog_message = dialog_messages.pop()
    db.set_dialog_messages(user_id, dialog_messages, dialog_id=None)  # last message was removed from the context

    await message_handle(update, context, message=last_dialog_message["user"], use_new_dialog_timeout=False)


async def message_handle(update: Update, context: CallbackContext, message=None, use_new_dialog_timeout=True):
    # check if message is edited
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
        
    await register_user_if_not_exists(update, context, update.message.from_user)
    user_id = update.message.from_user.id

    # new dialog timeout
    if use_new_dialog_timeout:
        if (datetime.now() - db.get_user_attribute(user_id, "last_interaction")).seconds > config.NEW_DIALOG_TIMEOUT:
            db.start_new_dialog(user_id)
            await update.message.reply_text("Starting new dialog due to timeout ✅")
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    # send typing action
    await update.message.chat.send_action(action="typing")

    used_tokens = db.get_user_attribute(user_id, "n_used_tokens")
    total_tokens = db.get_user_attribute(user_id, "total_tokens")

    if used_tokens >= total_tokens:
        await update.message.reply_text(f"Insufficient tokens: {total_tokens - used_tokens}", parse_mode=ParseMode.HTML)
        return

    try:
        message = message or update.message.text

        answer, prompt, n_used_tokens, n_first_dialog_messages_removed = chatgpt.ChatGPT().send_message(
            message,
            dialog_messages=db.get_dialog_messages(user_id, dialog_id=None),
            chat_mode=db.get_user_attribute(user_id, "current_chat_mode"),
        )

        # update user data
        new_dialog_message = {"user": message, "bot": answer, "date": datetime.now()}
        db.set_dialog_messages(
            user_id,
            db.get_dialog_messages(user_id, dialog_id=None) + [new_dialog_message],
            dialog_id=None
        )

        db.set_user_attribute(user_id, "n_used_tokens", n_used_tokens + db.get_user_attribute(user_id, "n_used_tokens"))

    except Exception as e:
        error_text = f"Something went wrong during completion. Reason: {e}"
        logger.error(error_text)
        await update.message.reply_text(error_text)
        return

    # send message if some messages were removed from the context
    if n_first_dialog_messages_removed > 0:
        if n_first_dialog_messages_removed == 1:
            text = "✍️ <i>Note:</i> Your current dialog is too long, so your <b>first message</b> was removed from the context.\n Send /new command to start new dialog"
        else:
            text = f"✍️ <i>Note:</i> Your current dialog is too long, so <b>{n_first_dialog_messages_removed} first messages</b> were removed from the context.\n Send /new command to start new dialog"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    try:
        await update.message.reply_text(answer, parse_mode=ParseMode.HTML)
    except telegram.error.BadRequest:
        # answer has invalid characters, so we send it without parse_mode
        await update.message.reply_text(answer)


async def new_dialog_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context, update.message.from_user)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    db.start_new_dialog(user_id)
    await update.message.reply_text("Starting new dialog ✅")

    chat_mode = db.get_user_attribute(user_id, "current_chat_mode")
    await update.message.reply_text(f"{chatgpt.CHAT_MODES[chat_mode]['welcome_message']}", parse_mode=ParseMode.HTML)


async def show_chat_modes_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context, update.message.from_user)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    keyboard = []
    for chat_mode, chat_mode_dict in chatgpt.CHAT_MODES.items():
        keyboard.append([InlineKeyboardButton(chat_mode_dict["name"], callback_data=f"set_chat_mode|{chat_mode}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Select chat mode:", reply_markup=reply_markup)


async def set_chat_mode_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update.callback_query, context, update.callback_query.from_user)
    user_id = update.callback_query.from_user.id

    query = update.callback_query
    await query.answer()

    chat_mode = query.data.split("|")[1]

    db.set_user_attribute(user_id, "current_chat_mode", chat_mode)
    db.start_new_dialog(user_id)

    await query.edit_message_text(
        f"<b>{chatgpt.CHAT_MODES[chat_mode]['name']}</b> chat mode is set",
        parse_mode=ParseMode.HTML
    )

    await query.edit_message_text(f"{chatgpt.CHAT_MODES[chat_mode]['welcome_message']}", parse_mode=ParseMode.HTML)


async def show_balance_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context, update.message.from_user)

    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    n_used_tokens = db.get_user_attribute(user_id, "n_used_tokens")
    n_spent_dollars = n_used_tokens * (0.02 / 1000)

    text = f"You spent <b>{n_spent_dollars:.03f}$</b>\n"
    text += f"You used <b>{n_used_tokens}</b> tokens <i>(price: 0.02$ per 1000 tokens)</i>\n"

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Top up", callback_data="top_up")]])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def show_top_up(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update.callback_query, context, update.callback_query.from_user)

    query = update.callback_query
    await query.answer()

    reply_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("$10", callback_data="top_up|10"),
            InlineKeyboardButton("$50", callback_data="top_up|50"),
            InlineKeyboardButton("$100", callback_data="top_up|100"),
        ]
    ])

    await query.edit_message_text(
        "Select or enter the amount",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )

    return TOP_UP

async def show_payment_methods(update: Update, context: CallbackContext):
    if update.message:
        await register_user_if_not_exists(update, context, update.message.from_user)
        amount = update.message.text
    else:
        await register_user_if_not_exists(update.callback_query, context, update.callback_query.from_user)
        query = update.callback_query
        await query.answer()
        amount = query.data.split("|")[1]

    text_not_in_range = "💡 Only accept number between 0.1 to 100"
    if not amount.replace('.', '', 1).isdigit():
        await reply_or_edit_text(update, text_not_in_range)
        return TOP_UP
    
    amount = float(amount)

    if amount > 100 or amount < 0.1:
        await reply_or_edit_text(update, text_not_in_range)
        return TOP_UP

    text = "Choose preferred payment method"
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Paypal", callback_data=f"payment|paypal|{amount}")],
        [InlineKeyboardButton("Crypto", callback_data=f"payment|crypto|{amount}")]
    ])

    if update.message:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    else:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )

    return PAYMENT

async def show_invoice(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update.callback_query, context, update.callback_query.from_user)
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _, method, amount = query.data.split("|")

    amount = float(amount)
    token_amount = int(amount / 0.02 * 1000)
    result = orders.create(user_id, method, amount, token_amount)

    if result and result["status"] == "OK":
        text = f"Your invoice: \n ${amount} = {token_amount} tokens"
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"Pay with ${method}", url=result["url"])]
        ])
    else:
        text = "Failed to create an invoice"
        reply_markup = None

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

    ConversationHandler.END

async def edited_message_handle(update: Update, context: CallbackContext):
    text = "🥲 Unfortunately, message <b>editing</b> is not supported"
    await update.edited_message.reply_text(text, parse_mode=ParseMode.HTML)


async def error_handle(update: Update, context: CallbackContext) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # collect error message
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)[:2000]
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
        "</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    await context.bot.send_message(update.effective_chat.id, message, parse_mode=ParseMode.HTML)

async def cancel(update: Update, context: CallbackContext):
    return ConversationHandler.END

async def app_post_init(application: Application):
    # setup bot commands
    await application.bot.set_my_commands(COMMANDS)

def run_bot() -> None:
    application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(app_post_init)
        .build()
    )

    # add handlers
    if not config.ALLOWED_TELEGRAM_USERNAMES or len(config.ALLOWED_TELEGRAM_USERNAMES) == 0:
        user_filter = filters.ALL
    else:
        user_filter = filters.User(username=config.ALLOWED_TELEGRAM_USERNAMES)

    application.add_handler(CommandHandler("start", start_handle, filters=user_filter))
    application.add_handler(CommandHandler("retry", retry_handle, filters=user_filter))
    application.add_handler(CommandHandler("new", new_dialog_handle, filters=user_filter))
    application.add_handler(CommandHandler("mode", show_chat_modes_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(set_chat_mode_handle, pattern="^set_chat_mode"))
    application.add_handler(CommandHandler("balance", show_balance_handle, filters=user_filter))

    # Add conversation handler with the states GENDER, PHOTO, LOCATION and BIO
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_top_up, pattern="^top_up$"),
        ],
        states={
            TOP_UP: [
                CallbackQueryHandler(show_payment_methods, pattern="^top_up\|(\d)+"),
                MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, show_payment_methods)
            ],
            PAYMENT: [
                CallbackQueryHandler(show_invoice, pattern="^payment\|"),
            ],
            CHATGPT: [
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, message_handle))
    application.add_error_handler(error_handle)
    
    # start the bot
    application.run_polling()


if __name__ == "__main__":
    run_bot()