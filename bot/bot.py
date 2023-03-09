import logging
import traceback
import html
import json
import re
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
import bugreport

# setup
db = database.Database()
logger = logging.getLogger(__name__)

CHATGPT, TOP_UP, PAYMENT = range(3)

def get_commands(lang=i18n.DEFAULT_LOCALE):
    _ = i18n.get_text_func(lang)
    return [
        BotCommand("new", _("start a new dialog")),
        BotCommand("retry", _("regenerate last answer")),
        # BotCommand("mode", _("select chat mode")),
        BotCommand("balance", _("show balance")),
        BotCommand("topup", _("top-up tokens")),
        # BotCommand("earn", _("earn rewards by referral")),
        BotCommand("language", _("set UI language")),
    ]

async def register_user_if_not_exists(update: Update, context: CallbackContext, referred_by: int = None):
    user = None
    if update.message:
        user = update.message.from_user
        chat_id = update.message.chat_id
    elif update.callback_query:
        user = update.callback_query.from_user
        chat_id = update.effective_chat.id
    if not user or not chat_id:
        print(f"Unknown callback event: {update}")
        return
    
    if not db.check_if_user_exists(user.id):
        if referred_by and (user.id == referred_by or not db.check_if_user_exists(referred_by)):
            # referred by unknown user or self, unset referral
            referred_by = None

        db.add_new_user(
            user.id,
            chat_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            referred_by=referred_by
        )
        db.inc_stats('new_users')
        if referred_by:
            db.inc_user_referred_count(referred_by)
            db.inc_stats('referral_new_users')
    return user

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

def get_chat_id(update: Update):
    chat_id = None
    if update.message:
        chat_id = update.message.chat_id
    elif update.callback_query:
        chat_id = update.effective_chat.id
    return chat_id

async def send_greeting(update: Update, context: CallbackContext, is_new_user=False):
    user = await register_user_if_not_exists(update, context)
    lang = db.get_user_preferred_language(user.id) or user.language_code
    _ = i18n.get_text_func(lang)

    commands_text = "".join([f"/{c.command} - {c.description}\n" for c in get_commands(lang)])

    reply_text = _("🤖 Hi! I'm <b>ChatGPT</b> bot powered by OpenAI GPT-3.5 API")
    reply_text += "\n\n"
    reply_text += _("<b>Commands</b>")
    reply_text += "\n"
    reply_text += commands_text
    
    await reply_or_edit_text(
        update,
        reply_text, 
        parse_mode=ParseMode.HTML,
        )
    
    if is_new_user and update.message:
        await update.message.reply_text(
            "✅ {:,} free tokens have been credited, check /balance".format(config.FREE_QUOTA), 
            parse_mode=ParseMode.HTML,
            )
    chat_id = get_chat_id(update)
    if chat_id:
        await context.bot.send_message(chat_id, _("now you can ask me anything ..."))

async def start_handle(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    is_new_user = not db.check_if_user_exists(user_id)

    # Extract the referral URL from the message text
    message_text = update.message.text
    m = re.match("\/start u(\d+)", message_text)
    referred_by = int(m[1]) if m else None

    user = await register_user_if_not_exists(update, context, referred_by=referred_by)
    
    _ = i18n.get_text_func(user.language_code)

    db.set_user_attribute(user_id, "last_interaction", datetime.now())
    db.start_new_dialog(user_id)
    
    await send_greeting(update, context, is_new_user=is_new_user)

async def retry_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    dialog_messages = db.get_dialog_messages(user_id)
    if not dialog_messages or len(dialog_messages) == 0:
        await update.message.reply_text("🤷‍♂️ No messages to retry")
        return

    last_dialog_message = dialog_messages.pop()
    db.set_dialog_messages(user_id, dialog_messages)  # last message was removed from the context

    await message_handle(update, context, message=last_dialog_message["user"], use_new_dialog_timeout=False)

def finalize_message_handle(user_id, message, answer, used_tokens):
    # update user data
    new_dialog_message = {"user": message, "bot": answer, "date": datetime.now()}
    db.set_dialog_messages(
        user_id,
        db.get_dialog_messages(user_id) + [new_dialog_message],
    )

    # IMPORTANT: consume tokens in the end of function call to protect users' credits
    db.inc_user_used_tokens(user_id, used_tokens)

async def message_handle(update: Update, context: CallbackContext, message=None, use_new_dialog_timeout=True):
    # check if message is edited
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
        
    user = await register_user_if_not_exists(update, context)
    _ = i18n.get_text_func(user.language_code)

    user_id = update.message.from_user.id

    # new dialog timeout
    if use_new_dialog_timeout:
        if (datetime.now() - db.get_user_attribute(user_id, "last_interaction")).seconds > config.NEW_DIALOG_TIMEOUT:
            db.start_new_dialog(user_id)
            await update.message.reply_text("💬 Starting a new dialog due to timeout")
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    # send typing action
    await update.message.chat.send_action(action="typing")

    remaining_tokens = db.get_user_remaining_tokens(user_id)

    if remaining_tokens < 0:
        await update.message.reply_text(_("⚠️ Insufficient tokens, check /balance"), parse_mode=ParseMode.HTML)
        return

    message = message or update.message.text
    answer = None
    used_tokens = None

    try:
        messages = db.get_dialog_messages(user_id)
        if not messages:
            logger.warning("missing dialog data, start a new dialog")
            db.start_new_dialog(user_id)
            messages = []

        answer, prompt, used_tokens, n_first_dialog_messages_removed = chatgpt.ChatGPT().send_message(
            message,
            dialog_messages=messages,
            chat_mode=db.get_user_attribute(user_id, "current_chat_mode"),
        )

        # send message if some messages were removed from the context
        if n_first_dialog_messages_removed > 0:
            if n_first_dialog_messages_removed == 1:
                text = "✍️ <i>Note:</i> Your current dialog is too long, so your <b>first message</b> was removed from the context.\n Send /new command to start new dialog"
            else:
                text = f"✍️ <i>Note:</i> Your current dialog is too long, so <b>{n_first_dialog_messages_removed} first messages</b> were removed from the context.\n Send /new command to start new dialog"
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)

        await update.message.reply_text(answer, parse_mode=ParseMode.MARKDOWN)

        # update user data
        finalize_message_handle(user_id, message, answer, used_tokens)
    except telegram.error.BadRequest as e:
        if answer:
            # answer has invalid characters, so we send it without parse_mode
            await update.message.reply_text(answer)
            # update user data
            finalize_message_handle(user_id, message, answer, used_tokens)
        else:
            error_text = f"Errors from Telegram: {e}"
            logger.error(error_text)    
    except Exception as e:
        error_text = f"Something went wrong during completion. Reason: {e}"
        logger.error(error_text)
        await update.message.reply_text(error_text)
        return

async def new_dialog_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    db.start_new_dialog(user_id)
    await update.message.reply_text("💬 Starting new dialog")

    # chat_mode = db.get_user_attribute(user_id, "current_chat_mode")
    # await update.message.reply_text(f"{chatgpt.CHAT_MODES[chat_mode]['welcome_message']}", parse_mode=ParseMode.HTML)


async def show_chat_modes_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    keyboard = []
    for chat_mode, chat_mode_dict in chatgpt.CHAT_MODES.items():
        keyboard.append([InlineKeyboardButton(chat_mode_dict["name"], callback_data=f"set_chat_mode|{chat_mode}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Select chat mode:", reply_markup=reply_markup)


async def set_chat_mode_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context)
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
    await register_user_if_not_exists(update, context)

    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    used_tokens = db.get_user_attribute(user_id, "used_tokens")
    n_spent_dollars = used_tokens * (config.TOKEN_PRICE / 1000)

    text = f"👛 <b>Balance</b>\n\n"
    text += "<b>{:,}</b> tokens\n".format(db.get_user_remaining_tokens(user_id))
    text += "<i>You used <b>{:,}</b> tokens</i>".format(used_tokens)
    # text += f"You spent <b>{n_spent_dollars:.03f}$</b>\n"
    # text += f"You used <b>{used_tokens}</b> tokens <i>(price: ${config.TOKEN_PRICE} per 1000 tokens)</i>\n"

    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Top up", callback_data="top_up")]])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def show_languages_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context)

    reply_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("English", callback_data="set_language|en"),
        ],
        [
            InlineKeyboardButton("繁體中文", callback_data="set_language|zh_TW"),
        ],
        [
            InlineKeyboardButton("简体中文", callback_data="set_language|zh_CN"),
        ]
    ])

    await reply_or_edit_text(
        update,
        "🌐 Select preferred language",
        reply_markup=reply_markup,
    )

async def set_language_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)

    query = update.callback_query
    await query.answer()
    language = query.data.split("|")[1]

    db.set_user_attribute(user.id, 'preferred_lang', language)

    await send_greeting(update, context)
    

def price_to_tokens(price: float):
    return int(price / config.TOKEN_PRICE * 1000)

async def show_top_up(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context)

    if update.callback_query:
        await update.callback_query.answer()

    reply_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("{:,} tokens - $1".format(price_to_tokens(1)), callback_data="top_up|1"),
        ],
        [
            InlineKeyboardButton("{:,} tokens - $5".format(price_to_tokens(5)), callback_data="top_up|5"),
        ],
        [
            InlineKeyboardButton("{:,} tokens - $10".format(price_to_tokens(10)), callback_data="top_up|10"),
        ]
    ])

    await reply_or_edit_text(
        update,
        "💡 Select a token package",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )

    return TOP_UP

async def show_payment_methods(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context)
    if update.message:
        amount = update.message.text
    else:
        query = update.callback_query
        await query.answer()
        amount = query.data.split("|")[1]

    text_not_in_range = "💡 Only accept number between 0.1 to 100, or /cancel top-up"
    if not amount.replace('.', '', 1).isdigit():
        await reply_or_edit_text(update, text_not_in_range)
        return TOP_UP
    
    amount = float(amount)

    if amount > 100 or amount < 0.1:
        await reply_or_edit_text(update, text_not_in_range)
        return TOP_UP

    text = "💡 Choose preferred payment method"
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Paypal", callback_data=f"payment|paypal|{amount}")],
        [InlineKeyboardButton("💎 Crypto", callback_data=f"payment|crypto|{amount}")]
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
    await register_user_if_not_exists(update, context)
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _, method, amount = query.data.split("|")

    amount = float(amount)
    token_amount = price_to_tokens(amount)

    await query.edit_message_text(
        "📋 Creating an invoice ...",
        parse_mode=ParseMode.HTML,
    )

    result = orders.create(user_id, method, amount, token_amount)

    if result and result["status"] == "OK":
        text = f"📋 <b>Your invoice</b>:\n\n"
        text += "{:,} tokens\n".format(token_amount)
        text += "------------------\n"
        text += f"${amount}\n\n"
        text += "<i>Your tokens will be credited within 10 minutes of payment.</i>"

        button_text = ""
        if method == "paypal":
            button_text = "💳 Pay with Paypal"
        elif method == "crypto":
            button_text = "💎 Pay with Crypto"
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(button_text, url=result["url"])]
        ])
    else:
        text = "⚠️ Failed to create an invoice, please try again later."
        reply_markup = None

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

    ConversationHandler.END

async def show_earn_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    referral_url = f"https://t.me/{config.TELEGRAM_BOT_NAME}?start=u{user.id}"

    message = "<b>💰 Earn</b>"
    message += "\n\n"
    message += "Get 5% rewards from the referred payments"
    message += "\n\n"
    message += "Referral link:"
    message += "\n"
    message += f'<a href="{referral_url}">{referral_url}</a>'
    message += "\n\n"
    message += "<i>💡 Refer someone via your referral link, and you'll get a reward when they make a payment.</i>"
    await reply_or_edit_text(update, message)

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

    try:
        await bugreport.send_bugreport(message)
    except Exception as e:
        print(f"Failed to send bugreport: {e}")

async def cancel(update: Update, context: CallbackContext):
    return ConversationHandler.END

async def app_post_init(application: Application):
    # setup bot commands
    await application.bot.set_my_commands(get_commands())

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
    # application.add_handler(CommandHandler("mode", show_chat_modes_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(set_chat_mode_handle, pattern="^set_chat_mode"))
    application.add_handler(CommandHandler("balance", show_balance_handle, filters=user_filter))
    application.add_handler(CommandHandler("earn", show_earn_handle, filters=user_filter))
    application.add_handler(CommandHandler("language", show_languages_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(set_language_handle, pattern="^set_language"))

    # Add conversation handler with the states GENDER, PHOTO, LOCATION and BIO
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("topup", show_top_up, filters=user_filter),
            CallbackQueryHandler(show_top_up, pattern="^top_up$"),
        ],
        states={
            TOP_UP: [
                CallbackQueryHandler(show_payment_methods, pattern="^top_up\|(\d)+"),
                # MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, show_payment_methods)
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