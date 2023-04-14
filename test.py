
import sys, os, argparse
sys.path.append('bot')
import asyncio
import config

parser = argparse.ArgumentParser(prog='prompt tester')
parser.add_argument('key')
parser.add_argument('-p', '--prompts')
args = parser.parse_args()

config.OPENAI_API_KEY = args.key
if args.prompts:
    config.CHAT_MODES = config.load_prompts(args.prompts)

import chatgpt

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
        print("- " + config.CHAT_MODES[key]["name"])
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
            answer = "{}: {}".format(config.CHAT_MODES[role]["name"], answer)

            # prevent terminal from printing duplicate lines
            lines = break_long_lines(answer, 60)
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
            dialog.append({"user": text, "bot": answer})

if __name__ == "__main__":
    print_roles()
    asyncio.run(test())