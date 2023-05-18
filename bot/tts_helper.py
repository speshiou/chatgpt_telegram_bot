import os
import re
import functools
import operator
from TTS.api import TTS
from pydub import AudioSegment

TEXT_MAX_LENGTH = 250

_models = TTS().list_models()
[print(model) for model in _models]

_cache = {}

def _get_model(model):
    if model not in _cache:
        full_model_name = model if model in _models else None
        if full_model_name is None:
            return None
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

def _split_text(text, sep, max_length):
    result = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_length)
        if end == len(text):
            result.append(text[start:end])
            break
        elif text[end-1] in sep:
            result.append(text[start:end])
            start = end
        else:
            found = False
            for i in range(end-1, start-1, -1):
                if text[i] in sep:
                    result.append(text[start:i+1])
                    start = i+1
                    found = True
                    break
            if not found:
                result.append(text[start:end])
                start = end
    return result

    
def tts(text, output, model=None):
    try:
        text = _remove_emojis(text)
        chunks = _split_text(text, ['.', '?', '!'], TEXT_MAX_LENGTH)
        m = _get_model(model)
        if not m:
            return None
        is_multi_dataset = "multi-dataset" in m.model_name
        is_multilingual = "multilingual" in m.model_name
        args = {}
        if is_multi_dataset:
            args['speaker'] = m.speakers[0]
        if is_multilingual:
            args['language'] = m.languages[0]

        basename, ext = os.path.splitext(output)
        format = ext[1:]

        if len(chunks) == 1:
            print(f"tts_to_file len: {len(text)}")
            m.tts_to_file(
                text=text, 
                file_path=output, 
                emotion="Happy", 
                speed=1, 
                **args)
            final_seg = AudioSegment.from_file(output, format=format)
        else:
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
            final_seg = combined

            # cleanup
            for filename in filenames:
                os.remove(filename)

        print(f"tts_to_file len: {len(text)}, duration: {final_seg.duration_seconds}s")
        return output
    except Exception as e:
        print(e)
    return None

