
import abc
import openai
import config
import openai_utils

openai.api_key = config.OPENAI_API_KEY

MODEL_GPT_35_TURBO = "gpt-3.5-turbo"

OPENAI_CHAT_MODEL = MODEL_GPT_35_TURBO

SUPPORTED_CHAT_MODELS = set([
    MODEL_GPT_35_TURBO,
])

async def send_message(message, dialog_messages=[], chat_mode="assistant", stream=False):
    if chat_mode not in config.CHAT_MODES.keys():
        raise ValueError(f"Chat mode {chat_mode} is not supported")
    
    model = OPENAI_CHAT_MODEL

    system_prompt = config.CHAT_MODES[chat_mode]["prompt_start"]
    prompt = openai_utils.prompt_from_chat_messages(system_prompt, dialog_messages, message, model)
    num_prompt_tokens = openai_utils.num_tokens_from_messages(prompt, model)

    n_dialog_messages_before = len(dialog_messages)
    n_first_dialog_messages_removed = 0

    answer = None
    while answer is None:
        try:
            r = await openai_utils.create_request(prompt, model, stream=stream)

            if stream:
                async for buffer in r:
                    content_delta, finish_reason = openai_utils.reply_content(buffer, model, stream=True)
                    if finish_reason == "length":
                        n_first_dialog_messages_removed += 1

                    if not content_delta:
                        continue
                    if answer is None:
                        answer = content_delta
                    else:
                        answer += content_delta
                    yield False, answer, None, n_first_dialog_messages_removed

                    # reset removed-messages counter
                    n_first_dialog_messages_removed = 0
                break
            else:
                answer = openai_utils.reply_content(r, model)

        except openai.error.InvalidRequestError as e:  # too many tokens
            print(e)
            if len(dialog_messages) == 0:
                raise ValueError("Input text length exceeds OpenAI's limit.") from e

            # forget first message in dialog_messages
            dialog_messages = dialog_messages[1:]

            # rebuild prompt
            prompt = openai_utils.prompt_from_chat_messages(system_prompt, dialog_messages, message, model)
            num_prompt_tokens = openai_utils.num_tokens_from_messages(prompt, model)

            n_first_dialog_messages_removed = n_dialog_messages_before - len(dialog_messages)

    num_completion_tokens = openai_utils.num_tokens_from_string(answer, model) if answer is not None else 0
    num_total_tokens = num_prompt_tokens + num_completion_tokens
    used_tokens = num_total_tokens 

    yield True, answer, used_tokens, n_first_dialog_messages_removed
        