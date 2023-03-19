
import abc

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

    async def create_request(self, model, message, dialog_messages=[], chat_mode="assistant"):
        r = None
        if model == MODEL_DAVINCI_003:
            r = Davinci003(message, dialog_messages, chat_mode)
        elif model == MODEL_GPT_35_TURBO:
            r = CPT35Turbo(message, dialog_messages, chat_mode)
        else:
            raise ValueError(f"Chat model {model} is not supported")
        
        if not isinstance(r, OpenAIRequest):
            raise TypeError(f"{r} is not a subclass of OpenAIRequest")
        
        return await r.create()
    
    async def send_message(self, message, dialog_messages=[], chat_mode="assistant"):
        if chat_mode not in CHAT_MODES.keys():
            raise ValueError(f"Chat mode {chat_mode} is not supported")

        n_dialog_messages_before = len(dialog_messages)
        answer = None
        prompt = None
        while answer is None:
            try:
                prompt, answer, used_tokens = await self.create_request(OPENAI_CHAT_MODEL, message, dialog_messages, chat_mode)

                answer = self._postprocess_answer(answer)

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

class OpenAIRequest(metaclass=abc.ABCMeta):
    def __init__(self, message, dialog_messages=[], chat_mode="assistant"):
        self.message = message
        self.dialog_messages = dialog_messages
        self.chat_mode = chat_mode
        self._prompt = None

    @abc.abstractmethod
    async def create(self):
        raise NotImplementedError

    @abc.abstractmethod
    def prompt(self):
        raise NotImplementedError

    @abc.abstractmethod
    def answer(self):
        raise NotImplementedError

    @abc.abstractmethod
    def used_token(self):
        raise NotImplementedError

class Davinci003(OpenAIRequest):
    def __init__(self, message, dialog_messages=[], chat_mode="assistant"):
        OpenAIRequest.__init__(self, message, dialog_messages, chat_mode)

    async def create(self):
        self._r = await openai.Completion.acreate(
            engine=MODEL_DAVINCI_003,
            prompt=self.prompt(),
            request_timeout=config.OPENAI_TIMEOUT,
            temperature=0.7,
            max_tokens=1000,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
        )

        return self.prompt(), self.answer(), self.used_token()

    def prompt(self):
        if self._prompt:
            return self._prompt
        
        prompt = CHAT_MODES[self.chat_mode]["prompt_start"]
        prompt += "\n\n"

        # add chat context
        if len(self.dialog_messages) > 0:
            prompt += "Chat:\n"
            for dialog_message in self.dialog_messages:
                prompt += f"User: {dialog_message['user']}\n"
                prompt += f"ChatGPT: {dialog_message['bot']}\n"

        # current message
        prompt += f"User: {self.message}\n"
        prompt += "ChatGPT: "

        self._prompt = prompt
        return self._prompt

    def answer(self):
        return self._r.choices[0].text
    
    def used_token(self):
        return self._r.usage.total_tokens
    
class CPT35Turbo(OpenAIRequest):
    def __init__(self, message, dialog_messages=[], chat_mode="assistant"):
        OpenAIRequest.__init__(self, message, dialog_messages, chat_mode)

    async def create(self):
        self._r = await openai.ChatCompletion.acreate(
            model=MODEL_GPT_35_TURBO,
            messages=self.prompt(),
            request_timeout=config.OPENAI_TIMEOUT,
        )

        return self.prompt(), self.answer(), self.used_token()

    def prompt(self):
        if self._prompt:
            return self._prompt
        
        messages = [
            {
                "role": "system",
                "content": CHAT_MODES[self.chat_mode]["prompt_start"],
            }
        ]

        # add chat context
        if len(self.dialog_messages) > 0:
            for dialog_message in self.dialog_messages:
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
            "content": self.message,
        })

        self._prompt = messages
        return self._prompt

    def answer(self):
        return self._r.choices[0].message.content
    
    def used_token(self):
        return self._r.usage.total_tokens
        