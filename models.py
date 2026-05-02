from pydantic import BaseModel
from typing import Literal


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
