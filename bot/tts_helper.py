import re, csv
from TTS.api import TTS

_models = TTS().list_models()

TTS_MODEL = _models[0]
MODELS = {}

_cache = {}

def load_models(tsv):
    models = {}
    with open(tsv) as file:
        tsv_file = csv.reader(file, delimiter="\t")
        for line in tsv_file:
            role, model = line
            key = role.lower().replace(" ", "_")
            models[key] = model
    return models

def _get_model(model):
    if model not in _cache:
        full_model_name = MODELS[model] if model in MODELS else TTS_MODEL
        tts = TTS(model_name=full_model_name, progress_bar=False, gpu=False)
        _cache[model] = tts
    return _cache[model]
    
def _remove_emojis(data):
    emoj = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
        u"\U00002500-\U00002BEF"  # chinese char
        u"\U00002702-\U000027B0"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        u"\U0001f926-\U0001f937"
        u"\U00010000-\U0010ffff"
        u"\u2640-\u2642" 
        u"\u2600-\u2B55"
        u"\u200d"
        u"\u23cf"
        u"\u23e9"
        u"\u231a"
        u"\ufe0f"  # dingbats
        u"\u3030"
                      "]+", re.UNICODE)
    return re.sub(emoj, '', data)
    
def tts(text, output, model=None):
    try:
        text = _remove_emojis(text)
        m = _get_model(model)
        if m:
            is_multi_dataset = "multi-dataset" in m.model_name
            is_multilingual = "multilingual" in m.model_name
            args = {}
            if is_multi_dataset:
                args['speaker'] = m.speakers[0]
            if is_multilingual:
                args['language'] = m.languages[0]
            m.tts_to_file(
                text=text, 
                file_path=output, 
                emotion="Happy", 
                speed=1, 
                **args)
            return output
    except Exception as e:
        print(e)
    return None

