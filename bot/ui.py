import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
from database import Database

def load_settings(db: Database, chat_id: int, _):
    current_chat_mode = db.get_current_chat_mode(chat_id)
    if current_chat_mode not in config.CHAT_MODES:
        current_chat_mode = list(config.CHAT_MODES.keys())[0]

    voice_mode = db.get_chat_voice_mode(chat_id)
    timeout = db.get_chat_timeout(chat_id)
    lang = db.get_chat_lang(chat_id)

    settings = {
        "current_chat_mode": {
            "icon": "💬",
            "name": _("Chat Mode"),
            "value": current_chat_mode,
            "disable_check_mark": True,
            "options": [ { "label": "{} {}".format(role["icon"], role["name"]), "value": chat_mode, "callback": "set_chat_mode|" + chat_mode } for chat_mode, role in config.CHAT_MODES.items()]
        },
        "voice_mode": {
            "icon": "🗣",
            "name": _("Chat Voice"),
            "desc": _("This setting only applies to the character with 🗣 icon, see /role.\n\n<b>Price:</b> {} tokens per second").format(config.COQUI_TOKENS),
            "value": voice_mode,
            "options": [
                {
                    "label": _("Text Only"),
                    "value": "text",
                },
                {
                    "label": _("Voice Only"),
                    "value": "voice",
                },
                {
                    "label": _("Text and Voice"),
                    "value": "text_and_voice",
                },
            ]
        },
        "timeout": {
            "icon": "⏱",
            "name": _("Chat Timeout"),
            "desc": _("Setting a proper timeout can help reduce token consumption. When a timeout occurs, the chatbot will not generate an answer based on previous chat history.\n\nYou can also use /reset to clear chat history manually."),
            "value": timeout,
            "options": [
                {
                    "label": _("1 Hour"),
                    "value": 60 * 60 * 1,
                },
                {
                    "label": _("6 Hours"),
                    "value": 60 * 60 * 6,
                },
                {
                    "label": _("12 Hours"),
                    "value": 60 * 60 * 12,
                },
                {
                    "label": _("24 Hours"),
                    "value": 60 * 60 * 24,
                },
                {
                    "label": _("Never"),
                    "value": 0,
                },
            ]
        },
        "lang": {
            "icon": "🌐",
            "name": _("UI Language"),
            "desc": _("This setting won't effect the answers from the chatbot"),
            "value": lang,
            "options": [
                {
                    "label": "English",
                    "value": "en",
                },
                {
                    "label": "简体中文",
                    "value": "zh_CN",
                },
                {
                    "label": "繁體中文",
                    "value": "zh_TW",
                },
                {
                    "label": _("Not specify"),
                    "value": None,
                },
            ]
        },
    }

    return settings

def settings(db: Database, chat_id: int, _, data: str = None):
    if data and "|" in data:
        # save settings
        segs = data.split("|")
        setting_key, value = segs[1:]
        if not value:
            value = None
        elif value.isnumeric():
            value = int(value)
        db.set_chat_attribute(chat_id, setting_key, value)

    settings = load_settings(db, chat_id, _)

    segs = data.split(">") if data else []

    keyboard = []

    title_format = "{} <b>{}</b>"

    if len(segs) <= 1:
        # main setting menu
        text = title_format.format("⚙️", _("Settings"))
        for key, setting in settings.items():
            value = setting["value"]
            label = value
            for option in setting["options"]:
                if value == option["value"]:
                    label = option["label"]
            keyboard.append([InlineKeyboardButton("{} {} - {}".format(setting["icon"], setting["name"], label), callback_data=f"settings>{key}")])
        keyboard.append([InlineKeyboardButton("ℹ️ " + _("About"), callback_data=f"about")])
    else:
        # sub setting menu
        setting_key = segs[-1]
        if setting_key in settings:
            setting = settings[setting_key]
            text = title_format.format(setting["icon"], setting["name"])

            if "desc" in setting:
                text += "\n\n"
                text += setting["desc"]

            for option in setting["options"]:
                label = option["label"]
                if "disable_check_mark" not in setting and setting["value"] == option["value"]:
                    label = "✅ " + label

                callback_value = option["value"] if option["value"] is not None else ""
                callback_data = option["callback"] if "callback" in option else f"settings|{setting_key}|{callback_value}"
                keyboard.append([InlineKeyboardButton(label, callback_data=callback_data)])

            keyboard.append([InlineKeyboardButton("< " + _("Back"), callback_data="settings")])
        else:
            text = "⚠️ " + _("This setting is outdated")

    reply_markup = InlineKeyboardMarkup(keyboard)

    return text, reply_markup

def about(_):
    text = _("Hi! I'm an AI chatbot powered by OpenAI's GPT and DALL·E models.")
    text += "\n\n"
    text += _("<b>What can I do for you?</b>\n")
    text += _("🌎 Translate\n")
    text += _("✉️ Writing\n")
    text += _("🗂 Summarize\n")
    text += _("🤔 Provide ideas and solve problems\n")
    text += _("💻 Programming and debugging\n")
    text += "\n"
    text += _("<b>More than ChatGPT</b>\n")
    text += _("🎙 Support voice messages (100 tokens/s when exceeding 10s)\n")
    text += _("✍️ Proofreading (/proofreader)\n")
    text += _("👨‍🎨 Generate images (/image)\n")
    text += _("🧙‍♀️ Chat with dream characters (/role)\n")
    text += _("👥 Group chat - add @{} to a group chat, then use /gpt to start.\n").format(config.TELEGRAM_BOT_NAME)
    text += _("💡 Subscribe to @ChatGPT_Prompts_Lab for more inspiration")
    text += "\n\n"
    text += _("""By using this chatbot, you agree to our <a href="{}">terms of service</a> and <a href="{}">privacy policy</a>.""").format("https://tgchat.co/terms-of-service", "https://tgchat.co/privacy-policy")

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ " + _("Settings"), callback_data="settings")],
        [
            InlineKeyboardButton("❓ " + _("FAQ"), url="https://tgchat.co/faq"),
            InlineKeyboardButton("✉️ " + _("Feedback"), url="https://t.me/gpt_chatbot_support"),
        ]
    ])

    return text, reply_markup
