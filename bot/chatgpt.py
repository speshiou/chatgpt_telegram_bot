
import openai
import config
import openai_utils

openai.api_key = config.OPENAI_API_KEY

MODEL_GPT_35_TURBO = "gpt-3.5-turbo"
MODEL_MAX_TOKENS = 4096
MIN_TOKENS = 50

OPENAI_CHAT_MODEL = MODEL_GPT_35_TURBO

SUPPORTED_CHAT_MODELS = set([
    MODEL_GPT_35_TURBO,
])

async def send_message(message, dialog_messages=[], system_prompt=None, max_tokens=MODEL_MAX_TOKENS, stream=False):
    model = OPENAI_CHAT_MODEL
    if max_tokens is None:
        max_tokens = MODEL_MAX_TOKENS

    n_dialog_messages_before = len(dialog_messages)
    n_first_dialog_messages_removed = 0
    num_prompt_tokens = 0

    answer = None
    while answer is None:
        try:
            prompt = openai_utils.prompt_from_chat_messages(system_prompt, dialog_messages, message, model)
            num_prompt_tokens = openai_utils.num_tokens_from_messages(prompt, model)
            if num_prompt_tokens > max_tokens:
                if len(dialog_messages) == 0:
                    raise ValueError("Not enough tokens", num_prompt_tokens)
                # forget first message in dialog_messages
                dialog_messages = dialog_messages[1:]
                n_first_dialog_messages_removed = n_dialog_messages_before - len(dialog_messages)
                continue

            max_tokens = max_tokens - num_prompt_tokens
            max_tokens = max(MIN_TOKENS, max_tokens)

            r = await openai_utils.create_request(prompt, model, max_tokens=max_tokens, stream=stream)

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
            n_first_dialog_messages_removed = n_dialog_messages_before - len(dialog_messages)
            continue

    num_completion_tokens = openai_utils.num_tokens_from_string(answer, model) if answer is not None else 0
    num_total_tokens = num_prompt_tokens + num_completion_tokens
    used_tokens = num_total_tokens 

    yield True, answer, used_tokens, n_first_dialog_messages_removed
        