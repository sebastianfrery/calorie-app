from typing import Literal, Optional

from pydantic import BaseModel


class Macronutrients(BaseModel):
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float


class FoodAnalysis(BaseModel):
    food_name: str
    estimated_calories: int
    macronutrients: Macronutrients
    model_used: str
    confidence: Literal["high", "medium", "low"]
    cache_hit: bool = False
    # Pro-only fields
    portion_size_g: Optional[int] = None
    allergens: Optional[list[str]] = None
    health_score: Optional[int] = None
    health_score_reason: Optional[str] = None
