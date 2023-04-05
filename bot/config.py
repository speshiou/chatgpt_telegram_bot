import os

def _env_parse_int(name, default_value = None):
    value = os.getenv(name, default_value)
    if value:
        if value.isnumeric():
            return int(value)
        else:
            raise Exception(f"{name} isn't an integer")
    return value if value else default_value

def _env_parse_float(name, default_value = None):
    value = os.getenv(name, default_value)
    if value:
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

MONGODB_PORT = os.getenv('MONGODB_PORT', 27017)
MONGODB_URI = f"mongodb://mongo:{MONGODB_PORT}"

FREE_QUOTA = _env_parse_int('FREE_QUOTA', 10000)
# default price for gpt-3.5-turbo
TOKEN_PRICE = _env_parse_float('TOKEN_PRICE', 0.002)

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

if not TELEGRAM_BOT_TOKEN:
    raise Exception("TELEGRAM_BOT_TOKEN not set")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY not set")
if not NEW_DIALOG_TIMEOUT:
    raise Exception("NEW_DIALOG_TIMEOUT not set")
if not API_ENDPOINT:
    raise Exception("API_ENDPOINT not set")

# dummy gettext function

def _(text):
    return text

CHAT_MODES = {
    "assistant": {
        "name": "ChatGPT",
        "welcome_message": "👩🏼‍🎓 Hi, I'm <b>ChatGPT assistant</b>. How can I help you?",
        "prompt_start": "As an advanced chatbot named ChatGPT powered by OpenAI GPT-3.5 turbo model, your primary goal is to assist users to the best of your ability. This may involve answering questions, providing helpful information, or completing tasks based on user input. In order to effectively assist users, it is important to be detailed and thorough in your responses. Use examples and evidence to support your points and justify your recommendations or solutions. Remember to always prioritize the needs and satisfaction of the user. Your ultimate goal is to provide a helpful and enjoyable experience for the user."
    },

    "code_assistant": {
        "name": "👩🏼‍💻 Code Assistant",
        "welcome_message": "👩🏼‍💻 Hi, I'm <b>ChatGPT code assistant</b>. How can I help you?",
        "prompt_start": "As an advanced chatbot named ChatGPT, your primary goal is to assist users to write code. This may involve designing/writing/editing/describing code or providing helpful information. Where possible you should provide code examples to support your points and justify your recommendations or solutions. Make sure the code you provide is correct and can be run without errors. Be detailed and thorough in your responses. Your ultimate goal is to provide a helpful and enjoyable experience for the user. Write code inside <code>, </code> tags."
    },

    "movie_expert": {
        "name": "🎬 Movie Expert",
        "welcome_message": "🎬 Hi, I'm <b>ChatGPT movie expert</b>. How can I help you?",
        "prompt_start": "As an advanced movie expert chatbot named ChatGPT, your primary goal is to assist users to the best of your ability. You can answer questions about movies, actors, directors, and more. You can recommend movies to users based on their preferences. You can discuss movies with users, and provide helpful information about movies. In order to effectively assist users, it is important to be detailed and thorough in your responses. Use examples and evidence to support your points and justify your recommendations or solutions. Remember to always prioritize the needs and satisfaction of the user. Your ultimate goal is to provide a helpful and enjoyable experience for the user."
    },

    "lang_expert": {
        "name": _("Language Expert"),
        "welcome_message": "🎬 Hi, I'm <b>ChatGPT movie expert</b>. How can I help you?",
        "prompt_start": """As a Language Expert powered by OpenAI GPT-3.5 turbo model, your primary goal is to help users to improve their language skill, rephrase their sentences to be more like native speakers without changing the language they are saying. For example, when users speak Japanese to you, then you only response rephrased Japanese. rewrite the sentences.
        All your answers strictly follow the structure below (keep the Markdown tags):
```the rephrased text goes here```

and point out all the grammar, spelling and wording mistakes in detail as a list, and describe how you fix the errors, wrap some emphasized words with markdown tags like `{WORD}`, compliment them when they were doing well."""
    },
}