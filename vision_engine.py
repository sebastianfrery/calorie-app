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

_PROMPT_BASIC = """Analyze the food in this image and respond ONLY with a valid JSON object in this exact format:
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

_PROMPT_PRO = """Analyze the food in this image and respond ONLY with a valid JSON object in this exact format:
{
  "food_name": "name of the food or dish",
  "estimated_calories": <integer>,
  "macronutrients": {
    "protein_g": <float>,
    "carbs_g": <float>,
    "fat_g": <float>,
    "fiber_g": <float>
  },
  "confidence": "high" | "medium" | "low",
  "portion_size_g": <integer, estimated total weight or volume in grams or ml>,
  "allergens": ["list only allergens clearly present or highly likely, e.g. gluten, dairy, eggs, nuts, soy, fish, shellfish"],
  "health_score": <integer 1-10>,
  "health_score_reason": "one sentence nutritional justification for the score"
}
Scoring guide: 1-3 = highly processed/high sugar-fat/low nutrition; 4-6 = moderate; 7-10 = whole foods, balanced macros, high micronutrients.
If no food is visible, set food_name to "No food detected", all numeric values to 0, allergens to [], health_score to 0, health_score_reason to ""."""

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
            portion_size_g=data.get("portion_size_g"),
            allergens=data.get("allergens") or None,
            health_score=data.get("health_score") or None,
            health_score_reason=data.get("health_score_reason") or None,
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
                    {"type": "text", "text": _PROMPT_BASIC},
                ],
            }
        ],
        max_tokens=512,
        temperature=0.1,
    )

    raw = response.choices[0].message.content
    return _parse_response(raw, model_used="meta-llama/llama-4-scout-17b-16e-instruct")


def _analyze_pro(image_bytes: bytes, media_type: str) -> FoodAnalysis:
    """Claude 3.5 Sonnet via Anthropic — Pro tier."""
    image_bytes = _resize(image_bytes, media_type)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
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
                    {"type": "text", "text": _PROMPT_PRO},
                ],
            }
        ],
    )

    raw = response.content[0].text
    return _parse_response(raw, model_used="claude-3-5-sonnet-20241022")


def analyze_food(
    image_bytes: bytes,
    media_type: str,
    user_tier: Literal["Basic", "Pro"],
) -> FoodAnalysis:
    if user_tier == "Pro":
        return _analyze_pro(image_bytes, media_type)
    return _analyze_basic(image_bytes, media_type)
