import hashlib
import logging
import os
import time
from datetime import date
from functools import wraps

from dotenv import load_dotenv
from supabase import create_client, Client

from models import FoodAnalysis, Macronutrients

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

TABLE = "food_analyses"
USERS = "users"

_supabase_client: Client | None = None


def _client() -> Client:
    global _supabase_client
    if _supabase_client is None:
        url = os.environ.get("SUPABASE_URL", "").strip()
        api_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

        if not url:
            raise ValueError("CRÍTICO: Variable SUPABASE_URL no encontrada en el entorno de Render")
        if not api_key:
            raise ValueError("CRÍTICO: Variable SUPABASE_SERVICE_ROLE_KEY no encontrada en el entorno de Render")

        if url.endswith("/rest/v1/"):
            url = url[:-9]

        print(f"DEBUG: Iniciando cliente Supabase con URL que empieza por: {url[:15]}")
        logger.info("Conectando a Supabase: %s", url[:15])

        _supabase_client = create_client(url, api_key)
    return _supabase_client


def _retry(max_attempts: int = 3, delay: float = 1.0):
    """Decorator: retries a function up to max_attempts times on any exception."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            fn.__name__, max_attempts, exc,
                            exc_info=True,
                        )
                        raise
                    logger.warning(
                        "%s attempt %d/%d failed: %s. Retrying in %.1fs…",
                        fn.__name__, attempt, max_attempts, exc, delay,
                    )
                    time.sleep(delay)
        return wrapper
    return decorator


def hash_image(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


@_retry()
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
    logger.debug("get_cached_analysis: cache hit hash=%s", image_hash[:12])
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
        portion_size_g=row.get("portion_size_g"),
        allergens=row.get("allergens"),
        health_score=row.get("health_score"),
        health_score_reason=row.get("health_score_reason"),
    )


@_retry()
def get_today_entries(email: str | None = None) -> list[dict]:
    if not email:
        return []
    today = date.today().isoformat()
    return (
        _client()
        .table(TABLE)
        .select("food_name, estimated_calories, protein_g, carbs_g, fat_g, fiber_g, created_at")
        .eq("analyzed_date", today)
        .eq("email", email)
        .order("created_at")
        .execute()
        .data or []
    )


@_retry()
def get_user(email: str) -> dict | None:
    res = _client().table(USERS).select("*").eq("email", email).limit(1).execute()
    return res.data[0] if res.data else None


@_retry()
def set_user_vip(email: str) -> None:
    logger.info("set_user_vip: email=%s", email)
    _client().table(USERS).upsert(
        {"email": email, "is_vip": True},
        on_conflict="email",
    ).execute()


@_retry()
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
        logger.debug("save_analysis: duplicate skipped email=%s hash=%s", email, image_hash[:12])
        return

    row: dict = {
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
    if result.portion_size_g is not None:
        row["portion_size_g"] = result.portion_size_g
    if result.allergens is not None:
        row["allergens"] = result.allergens
    if result.health_score is not None:
        row["health_score"] = result.health_score
    if result.health_score_reason is not None:
        row["health_score_reason"] = result.health_score_reason

    _client().table(TABLE).insert(row).execute()
    logger.info("save_analysis: saved email=%s food=%s tier=%s", email, result.food_name, tier)
