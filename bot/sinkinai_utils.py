import helper
import config

BASE_TOKENS = 1600

DEFAULT_NUM_IMAGES = 2
DEFAULT_STEPS = 20

INFERENCE_ENDPOINT = "https://sinkin.ai/m/inference"

BASE_FORM_DATA = {
    "user_email": config.SINKIN_ACCOUNT,
    "use_default_neg": "false",
    "steps": DEFAULT_STEPS,
    "scale": "5",
    "num_images": DEFAULT_NUM_IMAGES,
    "seed": "-1",
    "scheduler": "K_EULER_ANCESTRAL",
    "lora": "none",
    "lora_scale": "0.75"
}

# dummy function for localization
def _(text):
    return text

# keep model key short to prevent callback_data from exceeding size limit
MODELS = {
    "majic": {
        "name": _("Realistic"),
        "model_id": "yBG2r9O",
        "version": "5",
        "negative_prompt": "ng_deepnegative_v1_75t, (badhandv4:1.2), (worst quality:2), (low quality:2), (normal quality:2), lowres, bad anatomy, bad hands, ((monochrome)), ((grayscale)) watermark, moles",
        "scheduler": "K_EULER_ANCESTRAL",
    }
}

SIZE_OPTIONS = [
    {
        "width": 512,
        "height": 512,
    },
    {
        "width": 512,
        "height": 768,
    },
    {
        "width": 768,
        "height": 512,
    },
]

def calc_credit_cost(width: int, height: int, num_images=DEFAULT_NUM_IMAGES, steps=DEFAULT_STEPS):
    base_time = 3

    num_images_factor = num_images
    steps_factor = steps / 30
    w_factor = width / 512
    h_factor = height / 512

    gen_time = base_time + num_images_factor * steps_factor * w_factor * h_factor

    credit_cost = gen_time / 2

    return round(credit_cost * 10) / 10    # round to 1 decimal place

async def inference(model, width, height, prompt):
    if model in MODELS:
        model_data = MODELS[model]
    else:
        print(f"invalid model: {model}")
        return None
    data = {
        **BASE_FORM_DATA,
        **model_data,
        "width": width,
        "height": height,
        "prompt": prompt,
    }

    result = await helper.http_post(INFERENCE_ENDPOINT, data)
    if "images" in result:
        print("credit_cost: {}".format(result["credit_cost"]))
        return result["images"]
    print("Error: {}, {}".format(result["error_code"], result["message"]))
    raise Exception("Error code: {}".format(result["error_code"]))

