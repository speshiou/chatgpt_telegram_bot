import gettext

def mapping_tg_lang_code(code):
    if code == "zh-hant" or code.startswith("zh"):
        return "zh_TW"
    return "en"

def get_text_func(lang):
    locale = mapping_tg_lang_code(lang)
    t = gettext.translation('mybot', localedir='locales', languages=[locale])
    return t.gettext