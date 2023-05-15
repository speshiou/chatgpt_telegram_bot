
import sys, os, argparse
sys.path.append('bot')
import asyncio
import time
import config
import openai_utils
import chatgpt
import tts_helper
from pygame import mixer
import openai

parser = argparse.ArgumentParser(prog='prompt tester')
parser.add_argument('-p', '--prompts')
parser.add_argument('-t', '--tts')
parser.add_argument('--azure', action='store_true')
args = parser.parse_args()

if args.prompts:
    config.CHAT_MODES = { **config.CHAT_MODES, **config.load_prompts(args.prompts) }

if args.tts:
    tts_helper.MODELS = tts_helper.load_models(args.tts)

if args.azure:
    openai.api_type = "azure"
    openai.api_base = config.AZURE_OPENAI_API_BASE
    openai.api_version = config.AZURE_OPENAI_API_VERSION
    openai.api_key = config.AZURE_OPENAI_API_KEY

WAV_OUTPUT_PATH = "tmp.wav"

LINE_LENGTH = 60

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
    role = list(config.CHAT_MODES.keys())[0]
    while True:
        if not dialog:
            print("Now you're talking to {}\n".format(config.CHAT_MODES[role]["name"]))
        text = input("You: ")
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

        system_prompt = config.CHAT_MODES[role]["prompt"]
        stream = chatgpt.send_message(text, dialog, system_prompt, stream=True)
        answer = None
        current_line_index = 0
        async for buffer in stream:
            finished, answer, used_tokens, n_first_dialog_messages_removed = buffer
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
            if args.tts:
                output = tts_helper.tts(answer, output=WAV_OUTPUT_PATH, model=role)
                if output:
                    play_audio(output)
            # add messages to context
            dialog.append({"user": text, "bot": answer})

if __name__ == "__main__":
    openai_utils.print_gpt_models()
    print()
    print_roles()
    try:
        asyncio.run(test())
    except KeyboardInterrupt:
        pass