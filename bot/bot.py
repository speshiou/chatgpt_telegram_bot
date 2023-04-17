import logging
import traceback
import html
import json
import re
import math
from datetime import datetime

import telegram
from telegram import Chat, BotCommand, Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from telegram.constants import ParseMode, ChatAction

import config
import database
import openai_utils
import chatgpt
import api
import i18n
import bugreport

# setup
db = database.Database()
logger = logging.getLogger(__name__)

def get_commands(lang=i18n.DEFAULT_LOCALE):
    _ = i18n.get_text_func(lang)
    return [
        BotCommand("gpt", _("switch to ChatGPT mode")),
        BotCommand("proofreader", _("switch to Proofreader")),
        BotCommand("image", _("generate images ({} tokens)").format(config.DALLE_TOKENS)),
        BotCommand("new", _("start a new conversation")),
        BotCommand("retry", _("regenerate last answer")),
        # BotCommand("mode", _("select chat mode")),
        BotCommand("balance", _("check balance")),
        # BotCommand("earn", _("earn rewards by referral")),
        BotCommand("language", _("set UI language")),
    ]

async def register_user_if_not_exists(update: Update, context: CallbackContext, referred_by: int = None):
    user = None
    if update.message:
        user = update.message.from_user
    elif update.edited_message:
        user = update.edited_message.from_user
    elif update.callback_query:
        user = update.callback_query.from_user
    if not user:
        print(f"Unknown callback event: {update}")
        return
    
    if not db.check_if_user_exists(user.id):
        if referred_by and (user.id == referred_by or not db.check_if_user_exists(referred_by)):
            # referred by unknown user or self, unset referral
            referred_by = None

        db.add_new_user(
            user.id,
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

async def reply_or_edit_text(update: Update, text: str, parse_mode: ParseMode = ParseMode.HTML, reply_markup = None, disable_web_page_preview = None):
    if update.message:
        await update.message.reply_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    else:
        query = update.callback_query
        await query.edit_message_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )

def get_chat_id(update: Update):
    chat_id = None
    if update.message:
        chat_id = update.message.chat_id
    elif update.callback_query:
        chat_id = update.effective_chat.id
    return chat_id

def get_text_func(user):
    if user:
        lang = db.get_user_preferred_language(user.id) or user.language_code
    else:
        lang = None
    return i18n.get_text_func(lang)

async def send_greeting(update: Update, context: CallbackContext, is_new_user=False):
    user = await register_user_if_not_exists(update, context)
    lang = db.get_user_preferred_language(user.id) or user.language_code
    _ = i18n.get_text_func(lang)

    commands_text = "".join([f"/{c.command} - {c.description}\n" for c in get_commands(lang)])

    reply_text = _("Hi! I'm an AI chatbot powered by OpenAI's GPT-3.5 turbo and DALL·E models.")
    reply_text += "\n\n"
    reply_text += _("""By using this chatbot, you agree to our <a href="{}">terms of service</a> and <a href="{}">privacy policy</a>.""").format("https://tgchat.co/terms-of-service", "https://tgchat.co/privacy-policy")
    reply_text += "\n\n"
    reply_text += _("<b>Commands</b>")
    reply_text += "\n"
    reply_text += commands_text
    
    await reply_or_edit_text(
        update,
        reply_text, 
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        )
    
    if is_new_user and update.message:
        await update.message.reply_text(
            _("✅ {:,} free tokens have been credited, check /balance").format(config.FREE_QUOTA), 
            parse_mode=ParseMode.HTML,
            )
    chat_id = get_chat_id(update)
    if chat_id:
        text = _("Now you can ask me anything like\n\n")
        text += _("🔎 Find answers\n")
        text += _("🌎 Translate\n")
        text += _("✍️ Writing and proofreading\n")
        text += _("💡 Provide ideas and solve problems\n")
        text += _("💻 Programming and debugging\n")
        text += _("🧙‍♀️ Role-playing\n")
        text += _("and much more ...\n")
        await context.bot.send_message(chat_id, text)

async def start_handle(update: Update, context: CallbackContext):
    chat = update.effective_chat
    if chat.type != Chat.PRIVATE:
        return
    
    user_id = update.message.from_user.id
    is_new_user = not db.check_if_user_exists(user_id)

    # Extract the referral URL from the message text
    message_text = update.message.text
    m = re.match("\/start u(\d+)", message_text)
    referred_by = int(m[1]) if m else None

    await register_user_if_not_exists(update, context, referred_by=referred_by)

    db.set_user_attribute(user_id, "last_interaction", datetime.now())
    
    await send_greeting(update, context, is_new_user=is_new_user)

async def retry_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = get_chat_id(update)
    if not chat_id:
        return
    _ = get_text_func(user)
    
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    dialog_messages = db.get_dialog_messages(chat_id)
    if not dialog_messages or len(dialog_messages) == 0:
        await update.message.reply_text(_("😅 No conversation history to retry"))
        return

    last_dialog_message = dialog_messages.pop()
    db.pop_dialog_messages(chat_id)  # last message was removed from the context

    await message_handle(update, context, message=last_dialog_message["user"], use_new_dialog_timeout=False)

def strip_command(message):
    if not message.strip():
        return None
    m = re.match(f"\/\w+(@{config.TELEGRAM_BOT_NAME})? (.*)", message, re.DOTALL)
    if m:
        return m[2].strip()
    return None

async def group_chat_message_handle(update: Update, context: CallbackContext):
    # check if message is edited
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
    user = await register_user_if_not_exists(update, context)
    if not user:
        return
    _ = get_text_func(user)
    chat = update.effective_chat
    if chat.type == Chat.PRIVATE:
        text = _("👥 This command is also for group chats to talk to ChatGPT, please add @{} to a group chat as a group member").format(config.TELEGRAM_BOT_NAME)
        await update.message.reply_text(text)
        await set_chat_mode(update, context, "chatgpt")
        return
    
    message = strip_command(update.message.text)
    if not message:
        text = _("💡 Please type /gpt and followed by your question or topic\n\n")
        text += _("<b>Example:</b> /gpt what can you do?")
        await update.message.reply_text(text, ParseMode.HTML)
        return
    await message_handle(update, context, message=message)

async def proofreader_message_handle(update: Update, context: CallbackContext):
    # check if message is edited
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
    
    user = await register_user_if_not_exists(update, context)
    if not user:
        return

    _ = get_text_func(user)

    chat = update.effective_chat
    if chat.type == Chat.PRIVATE:
        await set_chat_mode(update, context, "proofreader")
        return

    # group chat
    message = strip_command(update.message.text)    
    if not message:
        text = _("💡 Please type /proofreader and followed by the content you want to rephrase\n\n")
        text += _("<b>Example:</b> /proofreader your sentences")
        await update.message.reply_text(text, ParseMode.HTML)
        return
    await message_handle(update, context, message=message, chat_mode="proofreader")

def finalize_message_handle(user_id, chat_id, message, answer, used_tokens, max_message_count: int=-1):
    # update user data
    new_dialog_message = {"user": message, "bot": answer, "date": datetime.now(), "used_tokens": used_tokens}
    db.push_dialog_messages(
        chat_id,
        new_dialog_message,
        max_message_count,
    )

    # IMPORTANT: consume tokens in the end of function call to protect users' credits
    db.inc_user_used_tokens(user_id, used_tokens)

def get_message_chunks(text, chuck_size=config.MESSAGE_MAX_LENGTH):
    return [text[i:i + chuck_size] for i in range(0, len(text), chuck_size)]

async def message_handle(update: Update, context: CallbackContext, message=None, use_new_dialog_timeout=True, chat_mode=None):
    user = update.message.from_user if update.message else None
    chat_id = get_chat_id(update)
    if not user or not chat_id:
        # sent from a channel
        return
    
    # check if message is edited
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
        
    user = await register_user_if_not_exists(update, context)
    _ = get_text_func(user)

    user_id = update.message.from_user.id
    if chat_mode is None:
        chat_mode = db.get_current_chat_mode(chat_id)
    # load chat history to context
    messages = db.get_dialog_messages(chat_id)
    if chat_mode == "proofreader":
        # to keep the language of input message, not to send chat history to model
        messages = []
    if chat_mode not in config.CHAT_MODES.keys():
        # fallback to the first mode
        chat_mode = list(config.CHAT_MODES.keys())[0]
        # lead to timeout process
        messages = None

    system_prompt = config.CHAT_MODES[chat_mode]["prompt"]

    # new dialog timeout
    if use_new_dialog_timeout:
        if messages is None or (datetime.now() - db.get_user_attribute(user_id, "last_interaction")).seconds > config.NEW_DIALOG_TIMEOUT:
            await set_chat_mode(update, context, chat_mode, reason="timeout")
            messages = []

    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    # send typing action
    await update.message.chat.send_action(action="typing")

    remaining_tokens = db.get_user_remaining_tokens(user_id)

    if remaining_tokens < 0:
        # TODO: show different messages for private and group chats
        await update.message.reply_text(_("⚠️ Insufficient tokens, check /balance"), parse_mode=ParseMode.HTML)
        return

    message = message or update.message.text
    answer = None
    sent_answer = None
    used_tokens = None
    # handle long message that exceeds telegram's limit
    n_message_chunks = 0
    current_message_chunk_index = 0
    n_sent_chunks = 0
    last_answer_message = None
    # handle too many tokens
    max_message_count = -1

    try:
        stream = chatgpt.send_message(
            message,
            dialog_messages=messages,
            system_prompt=system_prompt,
            max_tokens=remaining_tokens if remaining_tokens < chatgpt.MODEL_MAX_TOKENS else None,
            stream=config.STREAM_ENABLED
        )

        num_dialog_messages_removed = 0
        prev_answer = ""
        
        async for buffer in stream:
            
            finished, answer, used_tokens, n_first_dialog_messages_removed = buffer

            num_dialog_messages_removed += n_first_dialog_messages_removed

            if not finished and len(answer) - len(prev_answer) < 100:
                # reduce edit message requests
                continue
            prev_answer = answer
            parse_mode = ParseMode.MARKDOWN if finished else None

            # send warning if the anwser is too long (based on telegram's limit)
            if len(answer) > config.MESSAGE_MAX_LENGTH:
                parse_mode = None

            # send answer chunks
            n_message_chunks = math.ceil(len(answer) / config.MESSAGE_MAX_LENGTH)
            for chuck_index in range(current_message_chunk_index, n_message_chunks):
                start_index = chuck_index * config.MESSAGE_MAX_LENGTH
                end_index = (chuck_index + 1) * config.MESSAGE_MAX_LENGTH
                message_chunk = answer[start_index:end_index]
                if current_message_chunk_index < n_message_chunks - 1 or last_answer_message is None:
                    # send a new message chunk
                    last_answer_message = await update.message.reply_text(message_chunk, parse_mode=parse_mode)
                elif last_answer_message is not None:
                    # update last message chunk
                    try:
                        await context.bot.edit_message_text(message_chunk, chat_id=chat_id, message_id=last_answer_message.message_id, parse_mode=parse_mode)
                    except telegram.error.BadRequest as e:
                        if str(e).startswith("Message is not modified"):
                            continue
                        print(e)
                sent_answer = answer[0:end_index]
                current_message_chunk_index = chuck_index
                n_sent_chunks = chuck_index + 1

        # send warning if some messages were removed from the context
        if num_dialog_messages_removed > 0:
            if num_dialog_messages_removed == 1:
                text = _("⚠️ The <b>first message</b> was removed from the context due to OpenAI's token amount limit. Use /new to reset")
            else:
                text = _("⚠️ The <b>first {} messages</b> have removed from the context due to OpenAI's token amount limit. Use /new to reset").format(num_dialog_messages_removed)

            max_message_count = len(messages) + 1 - num_dialog_messages_removed

            await update.message.reply_text(text, parse_mode=ParseMode.HTML)

        # send warning if the anwser is too long (based on telegram's limit)
        if len(answer) > config.MESSAGE_MAX_LENGTH:
            await update.message.reply_text(_("⚠️ The answer was too long, has been splitted into multiple unformatted messages"))
    except telegram.error.BadRequest as e:
        error_text = f"Errors from Telegram: {e}"
        logger.error(error_text)    
        if answer and n_sent_chunks < n_message_chunks:
            # send remaining answer chunks
            chunks = get_message_chunks(answer)
            for i in range(current_message_chunk_index + 1, n_message_chunks):
                chunk = chunks[i]
                # answer may have invalid characters, so we send it without parse_mode
                await update.message.reply_text(chunk)
            sent_answer = answer
    except ValueError as e:
        await update.message.reply_text(_("⚠️ Require {} tokens to process the input text, check /balance").format(e.args[1]), parse_mode=ParseMode.HTML)
    except Exception as e:
        error_text = "⚠️ " + _("Temporary OpenAI server failure, please try again later. Reason: {}").format(e)
        logger.error(error_text)
        await update.message.reply_text(error_text)
        # printing stack trace
        traceback.print_exc()
        return
    
    # consume tokens and append the message record to db
    if sent_answer is not None and used_tokens is not None:
        finalize_message_handle(user_id, chat_id, message, sent_answer, used_tokens, max_message_count)

async def image_message_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = get_chat_id(update)
    if not chat_id:
        return
    
    _ = get_text_func(user)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    used_tokens = config.DALLE_TOKENS
    
    message = strip_command(update.message.text)
    if not message:
        text = _("💡 Please type /image and followed by the image prompt\n\n")
        text += _("<b>Example:</b> /image a cat wearing a spacesuit\n")
        text += _("<b>Price:</b> {} tokens per image").format(used_tokens)
        await update.message.reply_text(text, ParseMode.HTML)
        return
    
    remaining_tokens = db.get_user_remaining_tokens(user_id)
    if remaining_tokens < used_tokens:
        await update.message.reply_text(_("⚠️ Insufficient tokens. To generate an image, it will cost {} tokens. Check /balance").format(used_tokens), parse_mode=ParseMode.HTML)
        return
    
    remaing_time = db.is_user_generating_image(user_id)
    if remaing_time:
        await update.message.reply_text(_("⚠️ It is only possible to generate one image at a time. Please wait for {} seconds to retry.").format(int(remaing_time)), parse_mode=ParseMode.HTML)
        return
    
    placeholder = None
    try:
        db.mark_user_is_generating_image(user_id, True)
        placeholder = await update.message.reply_text("👨‍🎨 painting ...")
        image_url = await openai_utils.create_image(message)
        await placeholder.delete()
        await update.message.reply_photo(image_url)
        db.inc_user_used_tokens(user_id, used_tokens)
        db.mark_user_is_generating_image(user_id, False)
    except Exception as e:
        db.mark_user_is_generating_image(user_id, False)
        text = _("Temporary OpenAI server failure, please try again later. Reason: {}").format(e)
        if placeholder is None:
            await update.message.reply_text(text)
        else:
            await placeholder.edit_text(text)

async def new_dialog_handle(update: Update, context: CallbackContext):
    await set_chat_mode(update, context, reason="reset")

async def show_chat_modes_handle(update: Update, context: CallbackContext):
    await register_user_if_not_exists(update, context)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    keyboard = []
    for chat_mode, chat_mode_dict in config.CHAT_MODES.items():
        keyboard.append([InlineKeyboardButton(chat_mode_dict["name"], callback_data=f"set_chat_mode|{chat_mode}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Select chat mode:", reply_markup=reply_markup)

async def set_chat_mode(update: Update, context: CallbackContext, chat_mode = None, reason: str = None):
    user = await register_user_if_not_exists(update, context)
    chat_id = get_chat_id(update)
    if not chat_id:
        return
    
    _ = get_text_func(user)

    if chat_mode is None:
        chat_mode = db.get_current_chat_mode(chat_id)
    
    if chat_mode not in config.CHAT_MODES:
        # fallback to ChatGPT mode
        chat_mode = list(config.CHAT_MODES.keys())[0]

    # reset chat history
    db.start_new_dialog(chat_id, chat_mode)

    icon_prefix = config.CHAT_MODES[chat_mode]["icon"] + " " if "icon" in config.CHAT_MODES[chat_mode] else ""
    if reason == "timeout":
        text = icon_prefix + _("It's been a long time since we talked, and I've forgotten what we talked about before.")
    elif reason == "reset":
        text = icon_prefix + _("I have already forgotten what we previously talked about.")
    elif "greeting" in config.CHAT_MODES[chat_mode]:
        text = icon_prefix + config.CHAT_MODES[chat_mode]["greeting"]
    else:
        text = icon_prefix + _("You're now chatting with {} ...").format(config.CHAT_MODES[chat_mode]["name"])

    await reply_or_edit_text(update, text)

async def set_chat_mode_handle(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    chat_mode = query.data.split("|")[1]
    await set_chat_mode(update, context, chat_mode)

async def show_balance_handle(update: Update, context: CallbackContext):
    user = update.message.from_user if update.message else None
    if not user:
        # sent from a channel
        return
    user = await register_user_if_not_exists(update, context)
    _ = get_text_func(user)
    chat = update.effective_chat
    if chat.type != Chat.PRIVATE:
        text = _("🔒 For privacy reason, your balance won't show in a group chat. Please contact @{} directly.").format(config.TELEGRAM_BOT_NAME)
        await update.message.reply_text(text)
        return

    db.set_user_attribute(user.id, "last_interaction", datetime.now())

    used_tokens = db.get_user_attribute(user.id, "used_tokens")
    n_spent_dollars = used_tokens * (config.TOKEN_PRICE / 1000)

    text = _("👛 <b>Balance</b>\n\n")
    text += _("<b>{:,}</b> tokens left\n").format(db.get_user_remaining_tokens(user.id))
    text += _("<i>You used <b>{:,}</b> tokens</i>\n\n").format(used_tokens)
    text += _("""<i>💡 The longer conversation would spend more tokens, use /new to reset. (<a href="{}">Learn more</a>)</i>""").format("https://tgchat.co/faq")
    # text += f"You spent <b>{n_spent_dollars:.03f}$</b>\n"
    # text += f"You used <b>{used_tokens}</b> tokens <i>(price: ${config.TOKEN_PRICE} per 1000 tokens)</i>\n"

    tokens_packs = [
        {
            "payment_amount": 1.99,
            "tokens_amount": price_to_tokens(2),
        },
        {
            "payment_amount": 5.0 * 0.9,
            "tokens_amount": price_to_tokens(5),
            "caption": "-10%",
        },
        {
            "payment_amount": 7.99,
            "tokens_amount": price_to_tokens(10),
            "caption": "-20%",
        },
        {
            "payment_amount": 13.99,
            "tokens_amount": price_to_tokens(20),
            "caption": "-30%",
        },
    ]

    buttons = map(lambda pack: \
                  InlineKeyboardButton("+{:,} tokens - ${:,.2f}{}".format(pack["tokens_amount"], pack["payment_amount"], " ({})".format(pack["caption"]) if "caption" in pack else ""), \
                    callback_data="top_up|{}|{}".format(pack["payment_amount"], pack["tokens_amount"])), \
                        tokens_packs)
    rows = map(lambda button: [button], buttons)
    reply_markup = InlineKeyboardMarkup(list(rows))

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=True)

async def show_languages_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    _ = get_text_func(user)

    chat = update.effective_chat
    if chat.type != Chat.PRIVATE:
        text = _("💡 Please contact @{} directly to set UI language").format(config.TELEGRAM_BOT_NAME)
        await update.message.reply_text(text)
        return

    reply_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("English", callback_data="set_language|en"),
        ],
        [
            InlineKeyboardButton("简体中文", callback_data="set_language|zh_CN"),
        ],
        [
            InlineKeyboardButton("繁體中文", callback_data="set_language|zh_TW"),
        ],
    ])

    await reply_or_edit_text(
        update,
        _("🌐 Select preferred UI language"),
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

async def show_payment_methods(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    _ = get_text_func(user)

    query = update.callback_query
    await query.answer()
    c, amount, tokens_amount = query.data.split("|")

    amount = float(amount)

    if amount > 100 or amount < 0.1:
        text_not_in_range = _("💡 Only accept number between 0.1 to 100")
        await reply_or_edit_text(update, text_not_in_range)

    text = _("🛒 Choose the payment method\n\n")
    text += _("💳 Paypal - Debit or Credit Card\n")
    text += _("💎 Crypto - BTC, USDT, USDC, TON\n")
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(_("💳 Paypal"), callback_data=f"payment|paypal|{amount}|{tokens_amount}")],
        [InlineKeyboardButton(_("💎 Crypto"), callback_data=f"payment|crypto|{amount}|{tokens_amount}")]
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

async def show_invoice(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    _ = get_text_func(user)

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    c, method, amount, token_amount = query.data.split("|")

    amount = float(amount)
    token_amount = int(float(token_amount))

    await query.edit_message_text(
        _("📋 Creating an invoice ..."),
        parse_mode=ParseMode.HTML,
    )

    result = await api.create_order(user_id, method, amount, token_amount)

    if result and result["status"] == "OK":
        text = _("📋 <b>Your invoice</b>:\n\n")
        text += "{:,} tokens\n".format(token_amount)
        text += "------------------\n"
        text += f"${amount}\n\n\n"

        text += _("💡 <b>Tips</b>:\n")

        tips = []

        button_text = ""
        if method == "paypal":
            tips.append(_("If you do not have a PayPal account, click on the button located below the login button to pay with cards directly."))
            button_text = _("💳 Pay with Paypal")
        elif method == "crypto":
            tips.append(_("If you have any issues related to crypto payment, please contact the customer service in the payment page, or send messages to {} directly for assistance.").format("@cryptomus_support"))
            button_text = _("💎 Pay with Crypto")

        tips.append(_("Tokens will be credited within 10 minutes of payment."))
        tips.append(_("Please contact @gpt_chatbot_support if tokens are not received after 1 hour of payment."))

        text += "\n\n".join(map(lambda s: "• " + s, tips))

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(button_text, url=result["url"])]
        ])
    else:
        text = _("⚠️ Failed to create an invoice, please try again later.")
        reply_markup = None

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def show_earn_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    _ = get_text_func(user)

    result = await api.earn(user.id)

    if result and result["status"] == "OK":
        referral_url = result['referral_url']

        text = _("<b>💰 Earn</b>\n\n")
        # text += "\n\n"
        text += _("Get %s%% rewards from the referred payments\n\n") % (result['commission_rate'] * 100)
        text += _("Unused rewards: ${:,.2f}\n").format(result['unused_rewards'])
        text += _("Total earned: ${:,.2f}\n\n").format(result['total_earned'])
        text += _("Referral link:\n")
        text += f'<a href="{referral_url}">{referral_url}</a>\n'
        text += _("<i>You have referred {:,} new users</i>\n\n").format(result['referred_count'])
        text += _("<i>💡 Refer the new users via your referral link, and you'll get a reward when they make a payment.</i>")
    else:
        text = _("⚠️ Server error, please try again later.")

    await reply_or_edit_text(update, text)

async def edited_message_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    _ = get_text_func(user)

    text = _("💡 Edited messages won't take effects")
    await update.edited_message.reply_text(text, parse_mode=ParseMode.HTML)


async def error_handle(update: Update, context: CallbackContext) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # collect error message
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    chunks = get_message_chunks("".join(tb_list), chuck_size=2000)
    update_str = update.to_dict() if isinstance(update, Update) else str(update)

    try:
        for i, chuck in enumerate(chunks):
            if i == 0:
                message = (
                    f"An exception was raised while handling an update\n"
                    f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
                    "</pre>\n\n"
                    f"<pre>{html.escape(chuck)}</pre>"
                )
            else:
                message = f"<pre>{html.escape(chuck)}</pre>"
            await bugreport.send_bugreport(message)
    except Exception as e:
        print(f"Failed to send bugreport: {e}")

async def app_post_init(application: Application):
    # setup bot commands
    await application.bot.set_my_commands(get_commands())

def run_bot() -> None:
    application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
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
    # application.add_handler(CallbackQueryHandler(set_chat_mode_handle, pattern="^set_chat_mode"))
    application.add_handler(CommandHandler("balance", show_balance_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(show_payment_methods, pattern="^top_up\|(\d)+"))
    application.add_handler(CallbackQueryHandler(show_invoice, pattern="^payment\|"))
    application.add_handler(CommandHandler("earn", show_earn_handle, filters=user_filter))
    application.add_handler(CommandHandler("language", show_languages_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(set_language_handle, pattern="^set_language"))
    application.add_handler(CommandHandler("gpt", group_chat_message_handle, filters=user_filter))
    application.add_handler(CommandHandler("proofreader", proofreader_message_handle, filters=user_filter))
    application.add_handler(CommandHandler("image", image_message_handle, filters=user_filter))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, message_handle))
    application.add_error_handler(error_handle)
    
    # start the bot
    application.run_polling()


if __name__ == "__main__":
    if not config.TELEGRAM_BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN not set")
    if not config.OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY not set")
    run_bot()