
import sys, os, argparse
sys.path.append('bot')
import asyncio
import time
import config
import openai_utils
import chatgpt
import tts_helper
from pygame import mixer
from youtube_transcript_api import YouTubeTranscriptApi, _errors
import trafilatura
import helper

parser = argparse.ArgumentParser(prog='prompt tester')
parser.add_argument('-p', '--prompts')
parser.add_argument('-t', '--tts')
parser.add_argument('-r', '--role')
parser.add_argument('--azure', action='store_true')
args = parser.parse_args()

if args.prompts:
    config.CHAT_MODES = { **config.CHAT_MODES, **config.load_prompts(args.prompts) }

if args.tts:
    config.TTS_MODELS = config.load_tts_models(args.tts)

WAV_OUTPUT_PATH = "tmp.wav"

LINE_LENGTH = 60

# test youtube urls
YOUTUBE_URLS = [
    'http://youtu.be/SA2iWivDJiE',
    'http://www.youtube.com/watch?v=_oPAwA_Udwc&feature=feedu',
    'http://www.youtube.com/embed/SA2iWivDJiE',
    'http://www.youtube.com/v/SA2iWivDJiE?version=3&amp;hl=en_US',
    'https://www.youtube.com/watch?v=rTHlyTphWP0&index=6&list=PLjeDyYvG6-40qawYNR4juzvSOg-ezZ2a6',
    'youtube.com/watch?v=_lOT2p_FCvA',
    'youtu.be/watch?v=_lOT2p_FCvA',
    'https://www.youtube.com/watch?time_continue=9&v=n0g-Y0oo5Qs&feature=emb_logo'
]

def test_parse_youtube():
    for url in YOUTUBE_URLS:
        is_youtube_url = helper.is_youtube_url(url)
        video_id = helper.parse_youtube_id(url) if is_youtube_url else None
        print(f"is_youtube_url={is_youtube_url}, video_id={video_id}, url={url}")

def play_audio(file):
    mixer.init()
    mixer.music.load(file)
    mixer.music.play()
    while mixer.music.get_busy():
        time.sleep(0.01)

def break_long_lines(text, max_length):
    lines = []
    
    for para in text.split("\n"):
        current_line = ""
        for word in para.split():
            if len(current_line) + len(word) + 1 > max_length:
                lines.append(current_line.strip())
                current_line = word
            else:
                if len(current_line) == 0:
                    current_line = word
                else:
                    current_line = current_line + " " + word
        if len(current_line.strip()) > 0:
            lines.append(current_line.strip())

    return lines

def print_roles():
    print("Available roles:")
    for key in config.CHAT_MODES:
        print("{} {}".format(config.CHAT_MODES[key]["icon"], config.CHAT_MODES[key]["name"]))
    print()

async def test():
    dialog = []
    if args.role and args.role in config.CHAT_MODES:
        role = args.role
    else:
        role = config.DEFAULT_CHAT_MODE
    while True:
        if not dialog:
            print("Now you're talking to {}\n".format(config.CHAT_MODES[role]["name"]))
        text = input("You: ").strip()
        # handle /role command
        if text.startswith("/role "):
            role_name = text[len("/role "):]
            key = role_name.lower().replace(" ", "_")
            if key in config.CHAT_MODES:
                role = key
                dialog = []
                continue
            else:
                print("Warning: {} not exists".format(role_name))
                continue
        elif helper.is_uri(text):
            url = text
            if helper.is_youtube_url(text):
                video_id = helper.parse_youtube_id(text)
                print(f"parsing youtube {video_id} transcript ...")
                try:
                    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                    print(transcript_list)
                    for transcript in transcript_list:
                        # the Transcript object provides metadata properties
                        print(
                            transcript.video_id,
                            transcript.language,
                            transcript.language_code,
                            # whether it has been manually created or generated by YouTube
                            transcript.is_generated,
                            # whether this transcript can be translated or not
                            transcript.is_translatable,
                            # a list of languages the transcript can be translated to
                            # transcript.translation_languages,
                        )

                        transcript_json = transcript.fetch()
                        text = f"summarize the transcript from {url} containing abstract, list of key points and the summary, all responses in Chinese\n\ntranscript:\n{transcript_json}"
                        break
                except _errors.TranscriptsDisabled as e:
                    print("Youtube error: transcripts are disabled")
                except Exception as e:
                    print(e)
            else:
                downloaded = trafilatura.fetch_url(url)
                result = trafilatura.extract(downloaded, include_comments=False)
                text = f"summarize the content from {url} containing abstract, list of key points and the summary, all responses in Chinese\n\ntranscript:\n{result}"

        system_prompt = config.CHAT_MODES[role]["prompt"]
        model = openai_utils.MODEL_GPT_4 if role == "gpt4" else openai_utils.MODEL_GPT_35_TURBO

        api_type = "azure" if args.azure else config.DEFAULT_OPENAI_API_TYPE
        if api_type != config.DEFAULT_OPENAI_API_TYPE and "api_type" in config.CHAT_MODES[role]:
            api_type = config.CHAT_MODES[role]["api_type"]
        
        prompt, removed = chatgpt.build_prompt(system_prompt, dialog, text, model)
        stream = chatgpt.send_message(prompt, model=model, stream=True, api_type=api_type)
        answer = None
        current_line_index = 0
        async for buffer in stream:
            finished, answer, used_tokens = buffer
            if not answer:
                continue

            # prevent terminal from printing duplicate lines
            lines = break_long_lines(config.CHAT_MODES[role]["name"] + ": " + answer, LINE_LENGTH)
            num_lines = len(lines)
            for i in range(current_line_index, num_lines):
                if i < num_lines - 1:
                    print(lines[i])
                else:
                    print(lines[i], end='\r')
                current_line_index = i
        # wrap the last line
        print()

        if answer is not None:
            if args.tts and role in config.TTS_MODELS:
                tts_model = config.TTS_MODELS[role]
                output = await tts_helper.tts(answer, output=WAV_OUTPUT_PATH, model=tts_model)
                if output:
                    play_audio(output)
            if "disable_history" not in config.CHAT_MODES[role]:
                # add messages to context
                dialog.append({"user": text, "bot": answer})

if __name__ == "__main__":
    test_parse_youtube()
    openai_utils.print_gpt_models()
    print()
    print_roles()
    try:
        asyncio.run(test())
    except KeyboardInterrupt:
        pass