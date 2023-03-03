import config

import openai
openai.api_key = config.OPENAI_API_KEY

MODEL_DAVINCI_003 = "text-davinci-003"
MODEL_GPT_35_TURBO = "gpt-3.5-turbo"

OPENAI_CHAT_MODEL = MODEL_GPT_35_TURBO

SUPPORTED_CHAT_MODELS = set([
    MODEL_DAVINCI_003,
    MODEL_GPT_35_TURBO,
])


CHAT_MODES = {
    "assistant": {
        "name": "👩🏼‍🎓 Assistant",
        "welcome_message": "👩🏼‍🎓 Hi, I'm <b>ChatGPT assistant</b>. How can I help you?",
        "prompt_start": "As an advanced chatbot named ChatGPT, your primary goal is to assist users to the best of your ability. This may involve answering questions, providing helpful information, or completing tasks based on user input. In order to effectively assist users, it is important to be detailed and thorough in your responses. Use examples and evidence to support your points and justify your recommendations or solutions. Remember to always prioritize the needs and satisfaction of the user. Your ultimate goal is to provide a helpful and enjoyable experience for the user."
    },

    "code_assistant": {
        "name": "👩🏼‍💻 Code Assistant",
        "welcome_message": "👩🏼‍💻 Hi, I'm <b>ChatGPT code assistant</b>. How can I help you?",
        "prompt_start": "As an advanced chatbot named ChatGPT, your primary goal is to assist users to write code. This may involve designing/writing/editing/describing code or providing helpful information. Where possible you should provide code examples to support your points and justify your recommendations or solutions. Make sure the code you provide is correct and can be run without errors. Be detailed and thorough in your responses. Your ultimate goal is to provide a helpful and enjoyable experience for the user. Write code inside <code>, </code> tags."
    },

    "movie_expert": {
        "name": "🎬 Movie Expert",
        "welcome_message": "🎬 Hi, I'm <b>ChatGPT movie expert</b>. How can I help you?",
        "prompt_start": "As an advanced movie expert chatbot named ChatGPT, your primary goal is to assist users to the best of your ability. You can answer questions about movies, actors, directors, and more. You can recommend movies to users based on their preferences. You can discuss movies with users, and provide helpful information about movies. In order to effectively assist users, it is important to be detailed and thorough in your responses. Use examples and evidence to support your points and justify your recommendations or solutions. Remember to always prioritize the needs and satisfaction of the user. Your ultimate goal is to provide a helpful and enjoyable experience for the user."
    },
}


class ChatGPT:
    def __init__(self):
        pass

    def create_request(self, model, message, dialog_messages=[], chat_mode="assistant"):
        if model == MODEL_DAVINCI_003:
            return Davinci003(message, dialog_messages, chat_mode)
        elif model == MODEL_GPT_35_TURBO:
            return CPT35Turbo(message, dialog_messages, chat_mode)
        
        raise ValueError(f"Chat model {model} is not supported")
    
    def send_message(self, message, dialog_messages=[], chat_mode="assistant"):
        if chat_mode not in CHAT_MODES.keys():
            raise ValueError(f"Chat mode {chat_mode} is not supported")

        n_dialog_messages_before = len(dialog_messages)
        answer = None
        prompt = None
        while answer is None:
            try:
                r = self.create_request(OPENAI_CHAT_MODEL, message, dialog_messages, chat_mode)

                prompt = r.prompt()
                answer = r.answer()
                answer = self._postprocess_answer(answer)

                used_tokens = r.used_token()

            except openai.error.InvalidRequestError as e:  # too many tokens
                if len(dialog_messages) == 0:
                    print(e)
                    raise ValueError("Dialog messages is reduced to zero, but still has too many tokens to make completion") from e

                # forget first message in dialog_messages
                dialog_messages = dialog_messages[1:]

        n_first_dialog_messages_removed = n_dialog_messages_before - len(dialog_messages)

        return answer, prompt, used_tokens, n_first_dialog_messages_removed

    def _postprocess_answer(self, answer):
        answer = answer.strip()
        return answer
    

class Davinci003:
    def __init__(self, message, dialog_messages=[], chat_mode="assistant"):
        self._prompt = self._generate_prompt(message, dialog_messages, chat_mode)

        self._r = openai.Completion.create(
            engine=MODEL_DAVINCI_003,
            prompt=self._prompt,
            temperature=0.7,
            max_tokens=1000,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
        )

    def prompt(self):
        return self._prompt

    def answer(self):
        return self._r.choices[0].text
    
    def used_token(self):
        return self._r.usage.total_tokens
        
    def _generate_prompt(self, message, dialog_messages, chat_mode):
        prompt = CHAT_MODES[chat_mode]["prompt_start"]
        prompt += "\n\n"

        # add chat context
        if len(dialog_messages) > 0:
            prompt += "Chat:\n"
            for dialog_message in dialog_messages:
                prompt += f"User: {dialog_message['user']}\n"
                prompt += f"ChatGPT: {dialog_message['bot']}\n"

        # current message
        prompt += f"User: {message}\n"
        prompt += "ChatGPT: "

        return prompt
    
class CPT35Turbo:
    def __init__(self, message, dialog_messages=[], chat_mode="assistant"):
        self._prompt = self._generate_prompt(message, dialog_messages, chat_mode)
        
        self._r = openai.ChatCompletion.create(
            model=MODEL_GPT_35_TURBO,
            messages=self._prompt,
        )

    def prompt(self):
        return self._prompt

    def answer(self):
        return self._r.choices[0].message.content
    
    def used_token(self):
        return self._r.usage.total_tokens
        
    def _generate_prompt(self, message, dialog_messages, chat_mode):
        messages = [
            {
                "role": "system",
                "content": CHAT_MODES[chat_mode]["prompt_start"],
            }
        ]

        # add chat context
        if len(dialog_messages) > 0:
            for dialog_message in dialog_messages:
                messages.append({
                    "role": "user",
                    "content": dialog_message['user'],
                })
                messages.append({
                    "role": "assistant",
                    "content": dialog_message['bot'],
                })

        # current message
        messages.append({
            "role": "user",
            "content": message,
        })

        return messages