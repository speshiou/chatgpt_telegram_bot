import openai_utils
import config
import asyncio

MIN_TOKENS = 30

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
    
def build_prompt(system_prompt, dialog_messages, new_message, model, max_tokens = None):
    n_dialog_messages_before = len(dialog_messages)
    n_first_dialog_messages_removed = 0
    prompt = None
    num_prompt_tokens = None
    max_tokens = _max_tokens(model) if max_tokens is None else min(max_tokens, _max_tokens(model))

    while num_prompt_tokens is None or num_prompt_tokens >= max_tokens:
        if prompt is not None:
            # forget first message in dialog_messages
            dialog_messages = dialog_messages[1:]
            n_first_dialog_messages_removed = n_dialog_messages_before - len(dialog_messages)
        prompt = openai_utils.prompt_from_chat_messages(system_prompt, dialog_messages, new_message, model)
        num_prompt_tokens = openai_utils.num_tokens_from_messages(prompt, model)
        if len(dialog_messages) == 0:
            break
    return prompt, n_first_dialog_messages_removed

def cost_factors(model):
    if model == openai_utils.MODEL_GPT_4:
        return config.GPT4_PRICE_FACTOR, config.GPT4_PRICE_FACTOR
    return 1, 1

async def send_message(prompt, model=openai_utils.MODEL_GPT_35_TURBO, max_tokens=None, stream=False, api_type=None):
    max_tokens = _max_tokens(model) if max_tokens is None else min(_max_tokens(model), max_tokens)

    answer = None
    finish_reason = None
    num_prompt_tokens = openai_utils.num_tokens_from_messages(prompt, model)
    max_tokens = max_tokens - num_prompt_tokens
    max_tokens = max(MIN_TOKENS, max_tokens)

    r = await openai_utils.create_request(prompt, _model_name(model, api_type), max_tokens=max_tokens, stream=stream, api_type=api_type)

    if stream:
        async for buffer in r:
            content_delta, finish_reason = openai_utils.reply_content(buffer, model, stream=True)
            if not content_delta:
                continue
            if answer is None:
                answer = content_delta
            else:
                answer += content_delta

            if model == openai_utils.MODEL_GPT_4:
                # WORKAROUND: avoid reaching rate limit
                await asyncio.sleep(0.1)
            yield False, answer, None
    else:
        answer = openai_utils.reply_content(r, model)

    num_completion_tokens = openai_utils.num_tokens_from_string(answer, model) if answer is not None else 0
    num_total_tokens = num_prompt_tokens + num_completion_tokens
    used_tokens = num_total_tokens 

    if answer is None:
        print(f"Invalid answer, num_prompt_tokens={num_prompt_tokens}, num_completion_tokens={num_completion_tokens}, finish_reason={finish_reason}")
        raise Exception(finish_reason)

    # TODO: handle finish_reason == "length"

    yield True, answer, used_tokens
        