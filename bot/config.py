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
OPENAI_TIMEOUT = 60
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
