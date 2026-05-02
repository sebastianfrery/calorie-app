import hashlib
import os
from datetime import date

from dotenv import load_dotenv
from supabase import create_client, Client

from models import FoodAnalysis, Macronutrients

load_dotenv()

TABLE = "food_analyses"
USERS = "users"

_supabase_client: Client | None = None


def _client() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )
    return _supabase_client


def hash_image(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def get_cached_analysis(image_hash: str) -> FoodAnalysis | None:
    response = (
        _client()
        .table(TABLE)
        .select("*")
        .eq("image_hash", image_hash)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    row = response.data[0]
    return FoodAnalysis(
        food_name=row["food_name"],
        estimated_calories=row["estimated_calories"],
        macronutrients=Macronutrients(
            protein_g=row["protein_g"],
            carbs_g=row["carbs_g"],
            fat_g=row["fat_g"],
            fiber_g=row["fiber_g"],
        ),
        model_used=row["model_used"],
        confidence=row["confidence"],
        cache_hit=True,
    )


def get_today_entries(email: str | None = None) -> list[dict]:
    if not email:
        return []
    today = date.today().isoformat()
    return (
        _client()
        .table(TABLE)
        .select("food_name, estimated_calories, protein_g, carbs_g, fat_g, fiber_g")
        .eq("analyzed_date", today)
        .eq("email", email)
        .order("created_at")
        .execute()
        .data or []
    )


def get_user(email: str) -> dict | None:
    res = _client().table(USERS).select("*").eq("email", email).limit(1).execute()
    return res.data[0] if res.data else None


def set_user_vip(email: str) -> None:
    _client().table(USERS).upsert(
        {"email": email, "is_vip": True},
        on_conflict="email",
    ).execute()


def save_analysis(result: FoodAnalysis, image_hash: str, tier: str, email: str | None = None) -> None:
    if not email:
        return

    today = date.today().isoformat()

    existing = (
        _client()
        .table(TABLE)
        .select("id")
        .eq("email", email)
        .eq("image_hash", image_hash)
        .eq("analyzed_date", today)
        .execute()
    )
    if existing.data:
        return

    _client().table(TABLE).insert({
             "image_hash": image_hash,
            "email": email,
            "food_name": result.food_name,
            "estimated_calories": result.estimated_calories,
            "protein_g": result.macronutrients.protein_g,
            "carbs_g": result.macronutrients.carbs_g,
            "fat_g": result.macronutrients.fat_g,
            "fiber_g": result.macronutrients.fiber_g,
            "model_used": result.model_used,
            "confidence": result.confidence,
            "tier": tier,
            "analyzed_date": today,
        }
    ).execute()
