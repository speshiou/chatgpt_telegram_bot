import gettext

DEFAULT_LOCALE = "en"

SUPPORTED_LOCALES = set([
    'es',
    'fr',
    'zh_TW',
    'zh_CN',
    DEFAULT_LOCALE,
])

def mapping_tg_lang_code(code):
    if not code:
        return DEFAULT_LOCALE
    if code in SUPPORTED_LOCALES:
        return code
    if code == "zh-hant":
        return "zh_TW"
    elif code.startswith("zh"):
        return "zh_CN"
    return DEFAULT_LOCALE

def get_text_func(lang):
    locale = mapping_tg_lang_code(lang)
    if locale == DEFAULT_LOCALE:
        return gettext.gettext
    t = gettext.translation('mybot', localedir='locales', languages=[locale])
    return t.gettext