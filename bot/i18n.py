import gettext

DEFAULT_LOCALE = "en"

SUPPORTED_LOCALES = set([
    'zh_TW',
    'zh_CN',
    DEFAULT_LOCALE,
])

def mapping_tg_lang_code(code):
    if code in SUPPORTED_LOCALES:
        return code
    if code == "zh-hant" or code.startswith("zh"):
        return "zh_TW"
    return DEFAULT_LOCALE

def get_text_func(lang):
    locale = mapping_tg_lang_code(lang)
    if locale == DEFAULT_LOCALE:
        return gettext.gettext
    t = gettext.translation('mybot', localedir='locales', languages=[locale])
    return t.gettext