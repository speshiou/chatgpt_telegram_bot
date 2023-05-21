import os
import logging
import traceback
import html
import json
import re
import math
from datetime import datetime

import telegram
from telegram import Message, Chat, BotCommand, Update, User, InlineKeyboardButton, InlineKeyboardMarkup
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

from pydub import AudioSegment

import config
import database
import openai_utils
import chatgpt
import tts_helper
import api
import ui
import i18n
import bugreport

# setup
db = database.Database()
logger = logging.getLogger(__name__)

def get_commands(lang=i18n.DEFAULT_LOCALE):
    _ = i18n.get_text_func(lang)
    return [
        BotCommand("gpt", _("switch to ChatGPT mode")),
        BotCommand("proofreader", _("switch to Proofreader mode")),
        BotCommand("dictionary", _("switch to Dictionary mode")),
        BotCommand("image", _("generate images ({} tokens)").format(config.DALLE_TOKENS)),
        BotCommand("role", _("chat with dream characters")),
        BotCommand("reset", _("start a new conversation")),
        BotCommand("balance", _("check balance")),
        BotCommand("settings", _("settings")),
        # BotCommand("earn", _("earn rewards by referral")),
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
    elif update.callback_query:
        query = update.callback_query
        await query.edit_message_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )

def get_text_func(user, chat_id):
    if user:
        lang = db.get_chat_lang(chat_id) or user.language_code
    else:
        lang = None
    return i18n.get_text_func(lang)

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

    user = await register_user_if_not_exists(update, context, referred_by=referred_by)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    await settings_handle(update, context, data="about")

    if is_new_user and update.message:
        await update.message.reply_text(
            _("✅ {:,} free tokens have been credited, check /balance").format(config.FREE_QUOTA), 
            parse_mode=ParseMode.HTML,
            )

async def retry_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    messages = db.get_chat_messages(chat_id)
    if not messages or len(messages) == 0:
        await update.message.reply_text(_("😅 No conversation history to retry"))
        return

    last_dialog_message = messages.pop()
    db.pop_chat_messages(chat_id)  # last message was removed from the context

    await message_handle(update, context, message=last_dialog_message["user"], use_new_dialog_timeout=False)

def parse_command(message):
    if not message.strip():
        return None
    m = re.match(f"\/([^\s@]+)(@{config.TELEGRAM_BOT_NAME})?", message, re.DOTALL)
    if m:
        return m[1].strip()
    return None

def strip_command(message):
    if not message.strip():
        return None
    m = re.match(f"\/\w+(@{config.TELEGRAM_BOT_NAME})? (.*)", message, re.DOTALL)
    if m:
        return m[2].strip()
    return None

async def send_openai_error(update: Update, context: CallbackContext, e: Exception, placeholder = None):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    text = "⚠️ " + _("Temporary OpenAI server failure, please try again later.")
    error_msg = f"{e}"
    if "JSONDecodeError" not in error_msg:
        # ignore JSONDecodeError content. openai api may response html, which will cause message too long error
        text += " " + _("Reason: {}").format(error_msg)
    if placeholder is None:
        await update.effective_message.reply_text(text)
    else:
        await placeholder.edit_text(text)

    logger.error(error_msg)
    # printing stack trace
    traceback.print_exc()

async def common_command_handle(update: Update, context: CallbackContext):
    # check if message is edited
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
    
    user = await register_user_if_not_exists(update, context)
    if not user:
        return
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    cached_msg_id = None

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, cached_msg_id = query.data.split("|")
        message = db.get_cached_message(cached_msg_id)

        if not message:
            await update.effective_message.edit_text(update.effective_message.text, parse_mode=ParseMode.MARKDOWN, reply_markup=None)
            return
    else:
        message = update.message.text

    command = parse_command(message)
    if command == "gpt":
        command = "chatgpt"
    message = strip_command(message)

    chat_mode = command if command in config.CHAT_MODES else None

    if not chat_mode:
        print(f"WARNING: invalid command: {command}")
        return

    if message:
        await message_handle(update, context, message=message, chat_mode=chat_mode, cached_msg_id=cached_msg_id)
    else:
        await set_chat_mode(update, context, chat_mode)
    return

def get_message_chunks(text, chuck_size=config.MESSAGE_MAX_LENGTH):
    return [text[i:i + chuck_size] for i in range(0, len(text), chuck_size)]

async def voice_message_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    placeholder = None
    try:
        voice = update.message.voice
        print(voice)
        duration = voice.duration

        # check balance
        used_tokens = 0
        if duration > config.WHISPER_FREE_QUOTA:
            used_tokens = (duration - config.WHISPER_FREE_QUOTA) * config.WHISPER_TOKENS

        remaining_tokens = db.get_user_remaining_tokens(user.id)
        if remaining_tokens < used_tokens:
            await update.message.reply_text(_("⚠️ Insufficient tokens. You need {} tokens to decode this voice message. Check /balance").format(used_tokens), parse_mode=ParseMode.HTML)
            return
        
        placeholder = await update.effective_message.reply_text("🎙 " + _("Decoding voice message ..."))

        file_id = voice.file_id
        type = voice.mime_type.split("/")[1]
        new_file = await context.bot.get_file(file_id)
        src_filename = os.path.join(config.AUDIO_FILE_TMP_DIR, file_id)
        filename = src_filename
        await new_file.download_to_drive(src_filename)
        if type not in ['m4a', 'mp3', 'webm', 'mp4', 'mpga', 'wav', 'mpeg']:
            # convert to wav if source format is not supported by OpenAI
            wav_filename = src_filename + ".wav"
            seg = AudioSegment.from_file(src_filename, type)
            seg.export(wav_filename, format='wav')
            filename = wav_filename

        file_size = os.path.getsize(filename)
        print(f"size: {file_size}/{config.WHISPER_FILE_SIZE_LIMIT}")
        if file_size < config.WHISPER_FILE_SIZE_LIMIT:
            text = await openai_utils.audio_transcribe(filename)
            if used_tokens > 0:
                print(f"voice used tokens: {used_tokens}")
                db.inc_user_used_tokens(user.id, used_tokens)
            await message_handle(update, context, text, placeholder=placeholder)
        else:
            await placeholder.edit_text("⚠️ " + _("Voice data size exceeds 20MB limit"))
        # clean up
        os.remove(filename)
        if os.path.exists(src_filename):
            os.remove(src_filename)
        
    except Exception as e:
        await send_openai_error(update, context, e, placeholder=placeholder)

async def message_handle(update: Update, context: CallbackContext, message=None, use_new_dialog_timeout=True, chat_mode=None, placeholder: Message=None, cached_msg_id=None):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    
    # check if message is edited
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
        
    _ = get_text_func(user, chat_id)

    user_id = user.id
    chat = update.effective_chat
    reply_markup = None

    voice_mode = db.get_chat_voice_mode(chat_id)
    if chat_mode is None:
        chat_mode = db.get_current_chat_mode(chat_id)

    push_new_message = True
    
    if chat_mode not in config.CHAT_MODES:
        # fallback to the first mode
        chat_mode = config.DEFAULT_CHAT_MODE
        # lead to timeout process
        messages = None
    elif "disable_history" in config.CHAT_MODES[chat_mode]:
        # to keep the language of input message, not to send chat history to model
        messages = []
        push_new_message = False
        use_new_dialog_timeout = False
        if cached_msg_id is None:
            cached_message = update.effective_message.text
            if not cached_message.startswith("/"):
                cached_message = "/{} {}".format(chat_mode, cached_message)
            cached_msg_id = db.cache_chat_message(cached_message)
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(_("Retry"), callback_data=f"retry|{cached_msg_id}")]
        ])
    else:
        # load chat history to context
        messages = db.get_chat_messages(chat_id)

    system_prompt = config.CHAT_MODES[chat_mode]["prompt"]

    # new dialog timeout
    if use_new_dialog_timeout:
        last_chat_time = db.get_last_chat_time(chat_id)
        timeout = db.get_chat_timeout(chat_id)
        if messages is None or last_chat_time is None:
            # first launch
            await set_chat_mode(update, context, chat_mode)
            messages = []
        elif timeout > 0 and (datetime.now() - last_chat_time).total_seconds() > timeout:
            # timeout
            await set_chat_mode(update, context, chat_mode, reason="timeout")
            messages = []
            # drop placeholder to prevent the answer from showing before the timeout message
            placeholder = None

    # flood control, must run after set_chat_mode
    rate_limit_start, rate_count = db.get_chat_rate_limit(chat_id)
    if rate_limit_start is None or  (datetime.now() - rate_limit_start).total_seconds() > 60:
        db.reset_chat_rate_limit(chat_id)
    else:
        db.inc_chat_rate_count(chat_id)

    rate_limit = 10 if chat.type == Chat.PRIVATE else 8
    # telegram flood control limit is 20 messages per minute, we set 12 to leave some budget
    if rate_count >= rate_limit:
        if rate_count < rate_limit + 3:
            await update.effective_message.reply_text(_("⚠️ This chat has exceeded the rate limit. Please wait for up to 60 seconds."), parse_mode=ParseMode.HTML)
        return

    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    # send typing action
    await update.effective_chat.send_action(action="typing")

    remaining_tokens = db.get_user_remaining_tokens(user_id)

    max_tokens = chatgpt.MODEL_MAX_TOKENS
    if remaining_tokens < chatgpt.MODEL_MAX_TOKENS:
        max_tokens = remaining_tokens
    if remaining_tokens < 10000 or chat_mode not in config.DEFAULT_CHAT_MODES:
        # enable token saving mode for low balance users and external modes
        max_tokens = min(max_tokens, 2000)

    if remaining_tokens < 0:
        # TODO: show different messages for private and group chats
        await update.effective_message.reply_text(_("⚠️ Insufficient tokens, check /balance"), parse_mode=ParseMode.HTML)
        return

    if message is None:
        message = update.effective_message.text

    voice_placeholder = None    
    answer = None
    sent_answer = None
    used_tokens = None
    # handle long message that exceeds telegram's limit
    n_message_chunks = 0
    current_message_chunk_index = 0
    n_sent_chunks = 0
    # handle too many tokens
    max_message_count = -1

    try:
        api_type = config.OPENAI_CHAT_API_TYPE
        if api_type != config.DEFAULT_OPENAI_API_TYPE and "api_type" in config.CHAT_MODES[chat_mode]:
            api_type = config.CHAT_MODES[chat_mode]["api_type"]

        stream = chatgpt.send_message(
            message,
            dialog_messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            stream=config.STREAM_ENABLED,
            api_type=api_type,
        )

        num_dialog_messages_removed = 0
        prev_answer = ""
        
        if api_type == "azure":
            stream_len = 150 if chat.type == Chat.PRIVATE else 200
        else:
            stream_len = 100 if chat.type == Chat.PRIVATE else 150

        if placeholder is None:
            placeholder = await update.effective_message.reply_text("...")
        
        async for buffer in stream:
            
            finished, answer, used_tokens, n_first_dialog_messages_removed = buffer

            num_dialog_messages_removed += n_first_dialog_messages_removed

            if not finished and len(answer) - len(prev_answer) < stream_len:
                # reduce edit message requests
                continue
            prev_answer = answer

            if finished:
                parse_mode = ParseMode.MARKDOWN
                final_reply_markup = reply_markup
            else:
                parse_mode = None
                final_reply_markup = None

            # send warning if the anwser is too long (based on telegram's limit)
            if len(answer) > config.MESSAGE_MAX_LENGTH:
                parse_mode = None

            # send answer chunks
            n_message_chunks = math.ceil(len(answer) / config.MESSAGE_MAX_LENGTH)
            for chuck_index in range(current_message_chunk_index, n_message_chunks):
                start_index = chuck_index * config.MESSAGE_MAX_LENGTH
                end_index = (chuck_index + 1) * config.MESSAGE_MAX_LENGTH
                message_chunk = answer[start_index:end_index]
                if not finished:
                    message_chunk += " ..."
                if current_message_chunk_index < n_message_chunks - 1 or placeholder is None:
                    # send a new message chunk
                    placeholder = await update.effective_message.reply_text(message_chunk, parse_mode=parse_mode, reply_markup=final_reply_markup)
                elif placeholder is not None:
                    # update last message chunk
                    try:
                        await placeholder.edit_text(message_chunk, parse_mode=parse_mode, reply_markup=final_reply_markup)
                    except telegram.error.BadRequest as e:
                        if str(e).startswith("Message is not modified"):
                            continue
                        print(e)
                sent_answer = answer[0:end_index]
                current_message_chunk_index = chuck_index
                n_sent_chunks = chuck_index + 1

        # send warning if some messages were removed from the context
        if num_dialog_messages_removed > 0:
            # if num_dialog_messages_removed == 1:
            #     text = _("⚠️ The <b>first message</b> was removed from the context due to OpenAI's token amount limit. Use /reset to reset")
            # else:
            #     text = _("⚠️ The <b>first {} messages</b> have removed from the context due to OpenAI's token amount limit. Use /reset to reset").format(num_dialog_messages_removed)
            # await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
            print(f"removed {num_dialog_messages_removed} messages from context")
            max_message_count = len(messages) + 1 - num_dialog_messages_removed

        # send warning if the anwser is too long (based on telegram's limit)
        if len(answer) > config.MESSAGE_MAX_LENGTH:
            await update.effective_message.reply_text(_("⚠️ The answer was too long, has been splitted into multiple unformatted messages"))
    except telegram.error.BadRequest as e:
        error_text = f"Errors from Telegram: {e}"
        logger.error(error_text)    
        if answer and n_sent_chunks < n_message_chunks:
            # send remaining answer chunks
            chunks = get_message_chunks(answer)
            for i in range(current_message_chunk_index + 1, n_message_chunks):
                chunk = chunks[i]
                # answer may have invalid characters, so we send it without parse_mode
                await update.effective_message.reply_text(chunk, reply_markup=final_reply_markup)
            sent_answer = answer
    except ValueError as e:
        await update.effective_message.reply_text(_("⚠️ Require {} tokens to process the input text, check /balance").format(e.args[1]), parse_mode=ParseMode.HTML)
    except Exception as e:
        await send_openai_error(update, context, e)
    
    # TODO: consume tokens even if an exception occurs
    # consume tokens and append the message record to db
    if sent_answer is not None and used_tokens is not None:
        if push_new_message:
            # update user data
            new_dialog_message = {"user": message, "bot": sent_answer, "date": datetime.now(), "used_tokens": used_tokens}
            db.push_chat_messages(
                chat_id,
                new_dialog_message,
                max_message_count,
            )
        else:
            db.update_chat_last_interaction(chat_id)

        # IMPORTANT: consume tokens in the end of function call to protect users' credits
        db.inc_user_used_tokens(user_id, used_tokens)

        if voice_mode != "text":
            await send_voice_message(update, context, sent_answer, chat_mode, placeholder=voice_placeholder)

async def send_voice_message(update: Update, context: CallbackContext, message: str, chat_mode: str, placeholder = None):
    if chat_mode not in config.TTS_MODELS:
        return
    
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    limit = 600
    if len(message) > limit:
        print("[TTS] message too long")
        message = message[:limit]

    # estimate token amount
    used_tokens = config.TTS_ESTIMATED_DURATION_BASE * len(message) * config.COQUI_TOKENS
    print(f"[TTS] estimated used tokens: {used_tokens}")
    if used_tokens > db.get_user_remaining_tokens(user.id):
        await update.effective_message.reply_text("⚠️ " + _("Insufficient tokens. You need {} tokens to generate this voice message. Check /balance").format(used_tokens))
        return

    if placeholder is None:
        placeholder = await update.effective_message.reply_text("🗣 " + _("Recording ..."))

    try:
        tts_model = config.TTS_MODELS[chat_mode]
        filename = os.path.join(config.AUDIO_FILE_TMP_DIR, "{}-{}-{}.wav".format(chat_id, user.id, datetime.now()))
        output = await tts_helper.tts(message, output=filename, model=tts_model)
        if output:
            seg = AudioSegment.from_wav(output)
            # recalculate real token amount
            used_tokens = int(seg.duration_seconds * config.COQUI_TOKENS)
            ogg_filename = os.path.splitext(output)[0] + ".ogg"
            # must use OPUS codec to show spectrogram on Telegram
            seg.export(ogg_filename, format='ogg', codec="libopus")
            try:
                # in case the user deletes the placeholders manually
                if placeholder is not None:
                    await placeholder.delete()
            except Exception as e:
                print(e)
            await update.effective_message.reply_voice(ogg_filename)
            db.inc_user_used_tokens(user.id, used_tokens)
            print(f"[TTS] real used tokens: {used_tokens}")
            # clean up
            if os.path.exists(output):
                os.remove(output)
            if os.path.exists(ogg_filename):
                os.remove(ogg_filename)
        else:
            text = "⚠️ " + _("The voice message could not be created. Voice messages are only valid in English.")
            try:
                # in case the user deletes the placeholders manually
                if placeholder is not None:
                    await placeholder.edit_text(text)
            except Exception as e:
                print(e)
                await update.effective_message.reply_text(text)
    except Exception as e:
        print(e)
        text = "⚠️ " + _("Failed to generate the voice message, please try again later.")
        text += " " + _("Reason: {}").format(e)
        await update.effective_message.reply_text(text)

async def image_message_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    user_id = user.id
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
        placeholder = await update.message.reply_text(_("👨‍🎨 painting ..."))
        image_url = await openai_utils.create_image(message)
        try:
            # in case the user deletes the placeholders manually
            await placeholder.delete()
        except Exception as e:
            print(e)
        await update.message.reply_photo(image_url)
        db.inc_user_used_tokens(user_id, used_tokens)
        db.mark_user_is_generating_image(user_id, False)
    except Exception as e:
        db.mark_user_is_generating_image(user_id, False)
        await send_openai_error(update, context, e, placeholder=placeholder)

async def reset_handle(update: Update, context: CallbackContext):
    await set_chat_mode(update, context, reason="reset")

async def show_chat_modes_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    text, reply_markup = ui.settings(db, chat_id, _, "settings>current_chat_mode")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def set_chat_mode(update: Update, context: CallbackContext, chat_mode = None, reason: str = None):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    if chat_mode is None:
        chat_mode = db.get_current_chat_mode(chat_id)
    
    if chat_mode not in config.CHAT_MODES:
        # fallback to ChatGPT mode
        chat_mode = config.DEFAULT_CHAT_MODE

    # reset chat history
    db.reset_chat(chat_id, chat_mode)

    # to trigger roles to start the conversation
    send_empty_message = False

    icon_prefix = config.CHAT_MODES[chat_mode]["icon"] + " " if "icon" in config.CHAT_MODES[chat_mode] else ""
    if reason == "timeout":
        text = icon_prefix + _("It's been a long time since we talked, and I've forgotten what we talked about before.")
        text += " " + _("(/settings to change timeout)")
    elif reason == "reset":
        text = icon_prefix + _("I have already forgotten what we previously talked about.")
    elif "greeting" in config.CHAT_MODES[chat_mode]:
        text = icon_prefix + _(config.CHAT_MODES[chat_mode]["greeting"])
    else:
        text = icon_prefix + _("You're now chatting with {} ...").format(config.CHAT_MODES[chat_mode]["name"])
        send_empty_message = True

    chat = update.effective_chat
    if chat.type != Chat.PRIVATE:
        text += "\n\n"
        text += ui.build_tips([
            _("To continue the conversation in the group chat, please \"reply\" to my messages."),
            _("Please slow down your interactions with the chatbot as group chats can easily exceed the Telegram rate limit. "),
        ], _)

    await reply_or_edit_text(update, text)
    if send_empty_message:
        await message_handle(update, context, "")

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
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
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
    text += _("""<i>💡 The longer conversation would spend more tokens. /reset the chat. (<a href="{}">Learn more</a>)</i>""").format("https://tgchat.co/faq")
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

def price_to_tokens(price: float):
    return int(price / config.TOKEN_PRICE * 1000)

async def show_payment_methods(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    query = update.callback_query
    await query.answer()
    c, amount, tokens_amount = query.data.split("|")

    amount = float(amount)

    if amount > 100 or amount < 0.1:
        text_not_in_range = _("💡 Only accept number between 0.1 to 100")
        await reply_or_edit_text(update, text_not_in_range)

    text = _("🛒 Choose the payment method\n\n")
    text += _("💳 Debit or Credit Card - support 200+ countries/regions\n")
    text += "\n"
    text += _("💎 Crypto - BTC, USDT, USDC, TON, BNB\n")
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(_("💳 Debit or Credit Card"), callback_data=f"payment|paypal|{amount}|{tokens_amount}")],
        [InlineKeyboardButton(_("💎 Crypto"), callback_data=f"payment|crypto|{amount}|{tokens_amount}")]
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def show_invoice(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

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
            button_text = _("💳 Pay with Debit or Credit Card")
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

async def settings_handle(update: Update, context: CallbackContext, data: str = None):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    chat_mode = db.get_current_chat_mode(chat_id)
    db.upsert_chat(chat_id, chat_mode, clear_messages=False)
    _ = get_text_func(user, chat_id)

    query = update.callback_query
    if query:
        await query.answer()

    if data is None:
        data = query.data if query else None

    if data and data.startswith("about"):
        text, reply_markup = ui.about(_)
    else:
        text, reply_markup = ui.settings(db, chat_id, _, data=data)

    await reply_or_edit_text(update, text, reply_markup=reply_markup, disable_web_page_preview=True)

async def show_earn_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

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
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    text = _("💡 Edited messages won't take effects")
    await update.edited_message.reply_text(text, parse_mode=ParseMode.HTML)


async def error_handle(update: Update, context: CallbackContext) -> None:
    # collect error message
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    callstacks = "".join(tb_list)

    if "Message is not modified" in callstacks:
        # ignore telegram.error.BadRequest: Message is not modified. 
        # The issue is caused by users clicking inline keyboards repeatedly
        return
    
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    chunks = get_message_chunks(callstacks, chuck_size=2000)
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
    await application.bot.set_my_commands(get_commands('zh_CN'), language_code="zh")

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
    application.add_handler(CommandHandler("reset", reset_handle, filters=user_filter))
    application.add_handler(CommandHandler("role", show_chat_modes_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(set_chat_mode_handle, pattern="^set_chat_mode"))
    application.add_handler(CommandHandler("balance", show_balance_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(show_payment_methods, pattern="^top_up\|(\d)+"))
    application.add_handler(CallbackQueryHandler(show_invoice, pattern="^payment\|"))
    application.add_handler(CommandHandler("earn", show_earn_handle, filters=user_filter))
    application.add_handler(CommandHandler("gpt", common_command_handle, filters=user_filter))
    application.add_handler(CommandHandler("proofreader", common_command_handle, filters=user_filter))
    application.add_handler(CommandHandler("dictionary", common_command_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(common_command_handle, pattern="^retry"))
    application.add_handler(CommandHandler("image", image_message_handle, filters=user_filter))
    application.add_handler(CommandHandler("settings", settings_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(settings_handle, pattern="^(settings|about)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, message_handle))
    application.add_handler(MessageHandler(filters.VOICE & user_filter, voice_message_handle))
    application.add_error_handler(error_handle)
    
    # start the bot
    application.run_polling()


if __name__ == "__main__":
    if not config.TELEGRAM_BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN not set")
    if not config.OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY not set")
    run_bot()