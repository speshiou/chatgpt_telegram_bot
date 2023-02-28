import os

def _env_parse_int(name, default_value = None):
    value = os.getenv(name, default_value)
    if value:
        if value.isnumeric():
            return int(value)
        else:
            raise Exception(f"{name} isn't an integer")
    return value

def _env_parse_str_array(name, default_value = None):
    value = os.getenv(name, default_value)
    if value:
        return value.split(",")
    return value

MONGODB_PORT = os.getenv('MONGODB_PORT', 27017)
MONGODB_URI = f"mongodb://mongo:{MONGODB_PORT}"

FREE_QUOTA = 3000

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ALLOWED_TELEGRAM_USERNAMES = _env_parse_str_array('ALLOWED_TELEGRAM_USERNAMES')
NEW_DIALOG_TIMEOUT = _env_parse_int('NEW_DIALOG_TIMEOUT', 600)
PAYMENT_ENDPOINT = os.getenv('PAYMENT_ENDPOINT')

if not TELEGRAM_BOT_TOKEN:
    raise Exception("TELEGRAM_BOT_TOKEN not set")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY not set")
if not NEW_DIALOG_TIMEOUT:
    raise Exception("NEW_DIALOG_TIMEOUT not set")
if not PAYMENT_ENDPOINT:
    raise Exception("PAYMENT_ENDPOINT not set")
