import openai_utils

MODEL_MIN_LIMITED_TOKENS = 4096
MIN_TOKENS = 50

def _model_name(model, api_type):
    if api_type == "azure":
        return model.replace(".", "")
    return model

def _max_tokens(model):
    if model == openai_utils.MODEL_GPT_35_TURBO:
        return 4096
    elif model == openai_utils.MODEL_GPT_35_TURBO_16K:
        return 16384
    elif model == openai_utils.MODEL_GPT_4:
        return 8000

async def send_message(message, dialog_messages=[], system_prompt=None, model=openai_utils.MODEL_GPT_35_TURBO, max_tokens=None, stream=False, api_type=None):
    if max_tokens is None:
        max_tokens = _max_tokens(model)

    n_dialog_messages_before = len(dialog_messages)
    n_first_dialog_messages_removed = 0
    num_prompt_tokens = 0

    answer = None
    finish_reason = None
    while answer is None:
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

        r = await openai_utils.create_request(prompt, _model_name(model, api_type), max_tokens=max_tokens, stream=stream, api_type=api_type)

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

    num_completion_tokens = openai_utils.num_tokens_from_string(answer, model) if answer is not None else 0
    num_total_tokens = num_prompt_tokens + num_completion_tokens
    used_tokens = num_total_tokens 

    if answer is None:
        print(f"Invalid answer, num_prompt_tokens={num_prompt_tokens}, num_completion_tokens={num_completion_tokens}, finish_reason={finish_reason}")
        print(message)
        raise Exception(finish_reason)

    yield True, answer, used_tokens, n_first_dialog_messages_removed
        