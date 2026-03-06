import base64
import os
import requests
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO


OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"


def generate_image_pil(prompt: str) -> Image.Image:
    """
    Generates an image with the OpenAI Images API and returns it as a PIL Image (RGBA).
    Uses b64_json since GPT image models return base64 data.
    """
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in .env")

    model = (os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1-mini").strip()
    size = (os.getenv("OPENAI_IMAGE_SIZE") or "1024x1536").strip()
    quality = (os.getenv("OPENAI_IMAGE_QUALITY") or "medium").strip()
    background = (os.getenv("OPENAI_IMAGE_BACKGROUND") or "transparent").strip()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
    "model": model,
    "prompt": prompt,
    "size": size,                 # e.g. 1024x1536
    "quality": quality,           # low|medium|high
    "background": background,      # transparent|opaque|auto
    "output_format": "png",        # png|webp|jpeg
}

    resp = requests.post(OPENAI_IMAGES_URL, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI image generation failed ({resp.status_code}): {resp.text}")

    data = resp.json()
    b64 = data["data"][0]["b64_json"]
    img_bytes = base64.b64decode(b64)
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
    return img