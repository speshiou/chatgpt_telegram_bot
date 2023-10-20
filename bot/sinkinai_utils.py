import helper
import config

BASE_TOKENS = 1600

DEFAULT_NUM_IMAGES = 2

INFERENCE_ENDPOINT = "https://sinkin.ai/m/inference"
LORA_DETAILER_ID = "647944c3911a6fa8a2e2712b"

BASE_FORM_DATA = {
    "user_email": config.SINKIN_ACCOUNT,
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
    "real": {
        "name": _("Photorealistic"),
        "model_id": "mGYMaD5",
        "version": "1.6",
        "negative_prompt": "BadDream, (cgi render, 3d, cartoon, drawing, low quality, worst quality:1.2)",
        "steps": 30,
        "scale": "7.5",
        "scheduler": "DPMSolverMultistep",
        "use_default_neg": "false",
    },
    "dream": {
        "name": _("Unreal (2.5D)"),
        "model_id": "4zdwGOB",
        "version": "8",
        "prompt_template": "best quality, highly detailed, intricate, {}",
        "steps": 20,
        "scale": "7",
        "scheduler": "DPMSolverMultistep",
        "use_default_neg": "true",
        "lora": LORA_DETAILER_ID, 
        "lora_scale": "0.5",
    },
    "meina": {
        "name": _("Anime"),
        "model_id": "vln8Nwr",
        "version": "11",
        "negative_prompt": "(worst quality, low quality:1.4), (zombie, sketch, interlocked fingers, comic),",
        "steps": 20,
        "scale": "7",
        "scheduler": "K_EULER_ANCESTRAL",
        "use_default_neg": "false",
        "lora": LORA_DETAILER_ID, 
        "lora_scale": "0.3",
    },
    "sdxl": {
        "name": "Stable Diffusion XL",
        "model_id": "wozEgKm",
        "negative_prompt": "",
        "steps": 30,
        "scale": "7",
        "scheduler": "DPMSolverMultistep",
        "use_default_neg": "false",
    },
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

XL_SIZE_OPTIONS = [
    {
        "width": 1024,
        "height": 1024,
    },
    {
        "width": 768,
        "height": 1024,
    },
    {
        "width": 1024,
        "height": 768,
    },
]

def size_options(model):
    if model == "sdxl":
        return XL_SIZE_OPTIONS
    return SIZE_OPTIONS

def calc_credit_cost(width: int, height: int, steps: int, num_images=DEFAULT_NUM_IMAGES):
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
    
    if "prompt_template" in model_data:
        prompt = model_data["prompt_template"].format(prompt)
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

