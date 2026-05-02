import base64
import io
import json
import os
import re
from typing import Literal

import anthropic
from dotenv import load_dotenv
from groq import Groq
from PIL import Image

from models import FoodAnalysis, Macronutrients

load_dotenv()

_PROMPT = """Analyze the food in this image and respond ONLY with a valid JSON object in this exact format:
{
  "food_name": "name of the food or dish",
  "estimated_calories": <integer>,
  "macronutrients": {
    "protein_g": <float>,
    "carbs_g": <float>,
    "fat_g": <float>,
    "fiber_g": <float>
  },
  "confidence": "high" | "medium" | "low"
}
If no food is visible, set food_name to "No food detected" and all numeric values to 0."""

_PIL_FORMAT = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/gif": "PNG",  # flatten GIF to PNG
}


def _resize(image_bytes: bytes, media_type: str, max_px: int = 1024) -> bytes:
    """Downscale to max_px on the longest side. No-op if already within bounds."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if max(img.width, img.height) <= max_px:
            return image_bytes
        scale = max_px / max(img.width, img.height)
        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)
        fmt = _PIL_FORMAT.get(media_type, "JPEG")
        if fmt == "JPEG" and img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        result_bytes = buf.getvalue()
        orig_kb = len(image_bytes) / 1024
        new_kb = len(result_bytes) / 1024
        saving = (1 - new_kb / orig_kb) * 100
        print(f"[RESIZE] Tamaño original: {orig_kb:.1f} KB | Tamaño optimizado: {new_kb:.1f} KB | Ahorro: {saving:.0f}%")
        return result_bytes
    except Exception:
        return image_bytes


def _parse_response(raw: str, model_used: str) -> FoodAnalysis:
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
        data = json.loads(raw)
        return FoodAnalysis(
            food_name=data["food_name"],
            estimated_calories=int(data["estimated_calories"]),
            macronutrients=Macronutrients(**data["macronutrients"]),
            model_used=model_used,
            confidence=data.get("confidence", "medium"),
        )
    except Exception:
        return FoodAnalysis(
            food_name="Error al procesar",
            estimated_calories=0,
            macronutrients=Macronutrients(protein_g=0, carbs_g=0, fat_g=0, fiber_g=0),
            model_used=model_used,
            confidence="low",
        )


def _analyze_basic(image_bytes: bytes, media_type: str) -> FoodAnalysis:
    """Llama 4 Scout via Groq — free tier."""
    image_bytes = _resize(image_bytes, media_type)
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}"},
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
        max_tokens=512,
        temperature=0.1,
    )

    raw = response.choices[0].message.content
    return _parse_response(raw, model_used="meta-llama/llama-4-scout-17b-16e-instruct")


def _analyze_pro(image_bytes: bytes, media_type: str) -> FoodAnalysis:
    """Claude Sonnet via Anthropic — Pro tier."""
    image_bytes = _resize(image_bytes, media_type)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )

    raw = response.content[0].text
    return _parse_response(raw, model_used="claude-sonnet-4-6")


def analyze_food(
    image_bytes: bytes,
    media_type: str,
    user_tier: Literal["Basic", "Pro"],
) -> FoodAnalysis:
    if user_tier == "Pro":
        return _analyze_pro(image_bytes, media_type)
    return _analyze_basic(image_bytes, media_type)
