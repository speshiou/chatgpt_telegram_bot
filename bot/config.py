import os, csv

# dummy gettext function for parsing pot file
def _(text):
    return text

CHAT_MODES = {
    "chatgpt": {
        "icon": "🤖",
        "name": "ChatGPT",
        "greeting": _("Hello! How can I assist you today?"),
        "prompt": "As an advanced chatbot named ChatGPT powered by OpenAI GPT-3.5 turbo model, your primary goal is to assist users to the best of your ability. This may involve answering questions, providing helpful information, or completing tasks based on user input. In order to effectively assist users, it is important to be detailed and thorough in your responses. Use examples and evidence to support your points and justify your recommendations or solutions. Remember to always prioritize the needs and satisfaction of the user. Your ultimate goal is to provide a helpful and enjoyable experience for the user."
    },
    "proofreader": {
        "icon": "📝",
        "name": _("Proofreader"),
        "disable_history": True,
        "greeting": _("Hi, I'm Proofreader. Now you can give me any text in any languages, I will help you check grammar, spelling and wording usage, then rephrase it and do proofreading."),
        "prompt": """As a Proofreader, your primary goal is to help users to improve their language skill, rephrase their sentences to be more like native speakers without changing the language they are saying. For example, when users speak Japanese to you, then you only response rephrased Japanese. rewrite the sentences.
        All your answers MUST follow the structure below (keep the Markdown tags):
```the rephrased text goes here```

and point out all the grammar, spelling and wording mistakes in detail as a list, and describe how you fix the errors, wrap some emphasized words with markdown tags like `{WORD}`, compliment them when they were doing well."""
    },
    "dictionary": {
        "icon": "📔",
        "name": _("Dictionary"),
        "disable_history": True,
        "greeting": _("This is a dictionary where you can search for any words or phrases in various languages."),
        "prompt": """As a dictionary, all of your responses MUST follow the structure below:
`the inquired word or phrase` along with its pronunciation in phonetic transcription and an explanation of its part of speech, meaning, and usage

list different tenses if any

list similar words and phrases if any

list opposite words and phrases if any

list 5 of example sentences.
        """,
    },
}

def _env_parse_int(name, default_value = None):
    value = os.getenv(name, default_value)
    if value:
        if isinstance(value, int):
            return value
        if value.isnumeric():
            return int(value)
        else:
            raise Exception(f"{name} isn't an integer")
    return value if value else default_value

def _env_parse_float(name, default_value = None):
    value = os.getenv(name, default_value)
    if value:
        if isinstance(value, float):
            return value
        if value.replace('.', '', 1).isdigit():
            return float(value)
        else:
            raise Exception(f"{name} isn't an number")
    return value if value else default_value

def _env_parse_str_array(name, default_value = None):
    value = os.getenv(name, default_value)
    if value:
        return value.split(",")
    return value

def load_prompts(tsv):
    if not os.path.isfile(tsv):
        return {}
    prompts = {}
    with open(tsv, "r") as file:
        tsv_file = csv.reader(file, delimiter="\t")
        for line in tsv_file:
            icon, role, api_type, prompt = line
            key = role.lower().replace(" ", "_")
            prompts[key] = {
                "icon": icon,
                "name": role,
                "api_type": api_type,
                "prompt": prompt,
            }
    return prompts

def load_tts_models(tsv):
    models = {}
    with open(tsv) as file:
        tsv_file = csv.reader(file, delimiter="\t")
        for line in tsv_file:
            role, model = line
            key = role.lower().replace(" ", "_")
            models[key] = model
    return models

MONGODB_PORT = os.getenv('MONGODB_PORT', 27017)
MONGODB_URI = f"mongodb://mongo:{MONGODB_PORT}"

FREE_QUOTA = _env_parse_int('FREE_QUOTA', 10000)
# default price for gpt-3.5-turbo
TOKEN_PRICE = _env_parse_float('TOKEN_PRICE', 0.002)
# DALL·E tokens
DALLE_TOKENS = _env_parse_int('DALLE_TOKENS', 10000)
IMAGE_TIMEOUT = _env_parse_int('IMAGE_TIMEOUT', 60)
# prompts
if os.getenv('GPT_PROMPTS'):
    CHAT_MODES = { **CHAT_MODES, **load_prompts(os.getenv('GPT_PROMPTS')) }

TTS_MODELS = {}
# TTS models
if os.getenv('TTS_MODELS'):
    TTS_MODELS = { **TTS_MODELS, **load_tts_models(os.getenv('TTS_MODELS')) }

TELEGRAM_BOT_NAME = os.getenv('TELEGRAM_BOT_NAME')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MESSAGE_MAX_LENGTH = 4000
# OpenAI official API
DEFAULT_OPENAI_API_TYPE = "open_ai"
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_CHAT_API_TYPE = os.getenv('OPENAI_CHAT_API_TYPE', DEFAULT_OPENAI_API_TYPE)
if not OPENAI_CHAT_API_TYPE:
    OPENAI_CHAT_API_TYPE = DEFAULT_OPENAI_API_TYPE
# OpenAI API on Azure
AZURE_OPENAI_API_BASE = os.getenv('AZURE_OPENAI_API_BASE')
AZURE_OPENAI_API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION')
AZURE_OPENAI_API_KEY = os.getenv('AZURE_OPENAI_API_KEY')
if not AZURE_OPENAI_API_BASE or not AZURE_OPENAI_API_VERSION or not AZURE_OPENAI_API_KEY:
    # fallback to official OpenAI base if Azure is not set up properly
    OPENAI_CHAT_API_TYPE = DEFAULT_OPENAI_API_TYPE
# request timeout in seconds
OPENAI_TIMEOUT = 60
# whisper api has 25MB of file size limit, set 20MB to maintain buffer
WHISPER_FILE_SIZE_LIMIT = 20 * 1000 * 1000
# in seconds
WHISPER_FREE_QUOTA = 10
# cost per second
WHISPER_TOKENS = 100
# TTS per second
COQUI_TOKENS = 200
# duration per character in second
TTS_ESTIMATED_DURATION_BASE = 0.05
STREAM_ENABLED = True
ALLOWED_TELEGRAM_USERNAMES = _env_parse_str_array('ALLOWED_TELEGRAM_USERNAMES')
DEFAULT_CHAT_MODE = "assistant"
NEW_DIALOG_TIMEOUT = _env_parse_int('NEW_DIALOG_TIMEOUT', 600)
API_ENDPOINT = os.getenv('API_ENDPOINT')
BUGREPORT_BOT_TOKEN = os.getenv('BUGREPORT_BOT_TOKEN')
BUGREPORT_CHAT_ID = os.getenv('BUGREPORT_CHAT_ID')