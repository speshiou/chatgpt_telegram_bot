import os
import re, csv
import functools
import operator
from TTS.api import TTS
from pydub import AudioSegment

TEXT_MAX_LENGTH = 250

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
        if len(text) > TEXT_MAX_LENGTH:
            chunks = []
            chunk = ""
            # TODO: consider question mark as well
            sentences = text.split(".")
            for s in sentences:
                if len(chunk) + len(s) + 1 > TEXT_MAX_LENGTH:
                    chunks.append(chunk)
                    chunk = ""
                chunk += s + "."
            if chunk:
                chunks.append(chunk)
                
            print(f"text length exceeds coqui limit, split it into {len(chunks)} chunks")
        else:
            chunks = [text]
        m = _get_model(model)
        if m:
            is_multi_dataset = "multi-dataset" in m.model_name
            is_multilingual = "multilingual" in m.model_name
            args = {}
            if is_multi_dataset:
                args['speaker'] = m.speakers[0]
            if is_multilingual:
                args['language'] = m.languages[0]

            if len(chunks) == 1:
                print(f"tts_to_file len: {len(text)}")
                m.tts_to_file(
                    text=text, 
                    file_path=output, 
                    emotion="Happy", 
                    speed=1, 
                    **args)
            else:
                basename, ext = os.path.splitext(output)
                format = ext[1:]
                filenames = []
                for i, chunk in enumerate(chunks):
                    print(f"tts_to_file len: {len(chunk)}")
                    filename = f"{basename}{i}{ext}"
                    m.tts_to_file(
                        text=chunk, 
                        file_path=filename, 
                        emotion="Happy", 
                        speed=1, 
                        **args)
                    filenames.append(filename)
                    print(f"tts_to_file {filename}")

                print(f"combine {len(filenames)} audios")
                segments = [AudioSegment.from_file(filename, format=format) for filename in filenames]
                combined = functools.reduce(operator.add, segments)
                combined.export(output, format=format)

                # cleanup
                for filename in filenames:
                    os.remove(filename)
            return output
    except Exception as e:
        print(e)
    return None

