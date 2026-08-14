# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""State schema and data models for the Nutrition Specialist Graph Workflow."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

# The four valid nutrition goal categories
NutritionGoalType = Literal[
    "No Specific",
    "Low GI",
    "Cut Down Body Fat",
    "High Protein for Muscle Gain",
]

VALID_NUTRITION_GOALS: list[str] = [
    "No Specific",
    "Low GI",
    "Cut Down Body Fat",
    "High Protein for Muscle Gain",
]

# The two available corporate canteens in Singapore
VALID_CANTEENS: list[str] = ["Shiok", "StrEAT"]


class TargetMacros(BaseModel):
    """Translation of nutrition goals into concrete macronutrient targets."""

    max_calories_kcal: Optional[float] = Field(
        default=None,
        description="Target maximum calories in kcal (e.g., 550.0).",
    )
    min_protein_g: Optional[float] = Field(
        default=None,
        description="Target minimum protein in grams (e.g., 40.0).",
    )
    max_carbs_g: Optional[float] = Field(
        default=None,
        description="Target maximum carbohydrates in grams (e.g., 50.0).",
    )
    max_fat_g: Optional[float] = Field(
        default=None,
        description="Target maximum dietary fat in grams (e.g., 18.0).",
    )
    min_fiber_g: Optional[float] = Field(
        default=None,
        description="Target minimum dietary fiber in grams (e.g., 10.0).",
    )
    guideline_notes: Optional[str] = Field(
        default=None,
        description="Clinical or nutritional rationale behind these target macros.",
    )


class DishItem(BaseModel):
    """An individual dish item within a recommended meal plan."""

    name: str = Field(description="Exact dish name as listed in canteen menu.")
    station_name: str = Field(description="Canteen station name serving the dish.")
    portion_grams: float = Field(
        description="Precise recommended portion size in grams (e.g. 150.0g)."
    )
    calories_kcal: float = Field(
        description="Estimated calories in kcal based on USDA FoodData Central."
    )
    protein_g: float = Field(
        description="Estimated protein in grams based on USDA FoodData Central."
    )
    carbs_g: float = Field(
        description="Estimated carbohydrates in grams based on USDA FoodData Central."
    )
    fat_g: float = Field(
        description="Estimated fat in grams based on USDA FoodData Central."
    )
    fiber_g: Optional[float] = Field(
        default=0.0,
        description="Estimated dietary fiber in grams based on USDA FoodData Central.",
    )
    dietary_tags: List[str] = Field(
        default_factory=list,
        description="Dietary tags such as Vegan, Vegetarian, Halal-friendly.",
    )


class MealCombination(BaseModel):
    """A complete meal plan combination for a specific canteen."""

    combination_id: int = Field(
        description="Combination index for this canteen (1 or 2)."
    )
    canteen_name: str = Field(
        description="Canteen name: 'Shiok' (Floor 7) or 'StrEAT' (Floor 30)."
    )
    combination_title: str = Field(
        description="Short title, e.g. 'High-Protein Steamed Minced Pork & Chye Sim Combo'."
    )
    dishes: List[DishItem] = Field(
        description="List of dishes with exact names and portion sizes in grams."
    )
    total_portion_grams: float = Field(
        description="Total meal weight in grams."
    )
    total_calories_kcal: float = Field(
        description="Total calories in kcal."
    )
    total_protein_g: float = Field(
        description="Total protein in grams."
    )
    total_carbs_g: float = Field(
        description="Total carbohydrates in grams."
    )
    total_fat_g: float = Field(
        description="Total dietary fat in grams."
    )
    total_fiber_g: float = Field(
        default=0.0,
        description="Total dietary fiber in grams."
    )
    nutritional_rationale: str = Field(
        description="Explanation of how this combination satisfies the user's goal and macros."
    )


class NutritionState(BaseModel):
    """State schema tracking the user's nutrition consultation workflow."""

    canteen_preference: Optional[str] = Field(
        default=None,
        description="Which of the two available canteens the user prefers ('Shiok', 'StrEAT', or both).",
    )
    nutrition_goal: Optional[NutritionGoalType] = Field(
        default=None,
        description="Must map to one of: 'No Specific', 'Low GI', 'Cut Down Body Fat', 'High Protein for Muscle Gain'.",
    )
    target_macros: Optional[TargetMacros] = Field(
        default=None,
        description="Optional translation of the goal into max calories, minimum protein, etc.",
    )
    dietary_restrictions: Optional[List[str]] = Field(
        default=None,
        description="Items the user cannot eat (e.g. non-halal, specific allergies, vegetarian, dairy-free).",
    )
    suggested_meal_plans: Optional[List[MealCombination]] = Field(
        default=None,
        description="The output from the planning node (max 2 combinations per canteen).",
    )
    user_feedback: Optional[str] = Field(
        default=None,
        description="Any disagreement or modifications requested by the user during reverification.",
    )
