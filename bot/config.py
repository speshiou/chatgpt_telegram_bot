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
        "greeting": _("Hi, I'm Proofreader. Now you can give me any text in any languages, I will help you check grammar, spelling and wording usage, then rephrase it and do proofreading."),
        "prompt": """As a Proofreader, your primary goal is to help users to improve their language skill, rephrase their sentences to be more like native speakers without changing the language they are saying. For example, when users speak Japanese to you, then you only response rephrased Japanese. rewrite the sentences.
        All your answers strictly follow the structure below (keep the Markdown tags):
```the rephrased text goes here```

and point out all the grammar, spelling and wording mistakes in detail as a list, and describe how you fix the errors, wrap some emphasized words with markdown tags like `{WORD}`, compliment them when they were doing well."""
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
    prompts = {}
    with open(tsv) as file:
        tsv_file = csv.reader(file, delimiter="\t")
        for line in tsv_file:
            icon, role, prompt = line
            key = role.lower().replace(" ", "_")
            prompts[key] = {
                "icon": icon,
                "name": role,
                "prompt": prompt,
            }
    return prompts

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

TELEGRAM_BOT_NAME = os.getenv('TELEGRAM_BOT_NAME')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MESSAGE_MAX_LENGTH = 4000
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
# request timeout in seconds
OPENAI_TIMEOUT = 90
STREAM_ENABLED = True
ALLOWED_TELEGRAM_USERNAMES = _env_parse_str_array('ALLOWED_TELEGRAM_USERNAMES')
DEFAULT_CHAT_MODE = "assistant"
NEW_DIALOG_TIMEOUT = _env_parse_int('NEW_DIALOG_TIMEOUT', 600)
API_ENDPOINT = os.getenv('API_ENDPOINT')
BUGREPORT_BOT_TOKEN = os.getenv('BUGREPORT_BOT_TOKEN')
BUGREPORT_CHAT_ID = os.getenv('BUGREPORT_CHAT_ID')