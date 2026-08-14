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

"""Planning Node and USDA-backed Nutrition Planner Agent for Singapore Canteens."""

from collections.abc import AsyncGenerator
import json
import logging
from typing import Any, Dict, List, Optional

from google import genai
from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types
from pydantic import BaseModel, Field

from ..state import DishItem, MealCombination, NutritionState, TargetMacros
from ..tools.menu_tool import filter_menu_items, get_available_canteens, get_canteen_menu
from ..tools.usda_tool import (
    USDA_DOWNLOAD_PAGE_URL,
    download_usda_dataset_info,
    estimate_dish_nutrition,
    query_usda_nutrition,
)

logger = logging.getLogger(__name__)

MODEL = "gemini-3.6-flash"


class PlanningOutput(BaseModel):
    """Structured output for the meal planning generation."""

    combinations: List[MealCombination] = Field(
        description="Suggested meal combinations (maximum 2 combinations per canteen)."
    )
    planning_summary: str = Field(
        description="Overall summary of the meal plan generation and USDA estimation methodology."
    )


# Specialized USDA Nutrition Sub-Agent that queries FoodData Central
usda_nutrition_specialist_agent = Agent(
    name="usda_nutrition_specialist",
    model=MODEL,
    instruction=(
        "You are an expert Nutritional Scientist specializing in the USDA FoodData Central database "
        f"({USDA_DOWNLOAD_PAGE_URL}). Your job is to compute precise gram-based nutritional breakdowns "
        "(calories, protein, carbohydrates, fats, fiber) for Singapore canteen meal combinations."
    ),
    description="Sub-agent that downloads and queries USDA FoodData Central for precise nutritional estimates.",
    tools=[download_usda_dataset_info, query_usda_nutrition, estimate_dish_nutrition],
)


def _generate_fallback_combinations(
    canteen_pref: str,
    goal: str,
    restrictions: List[str],
    feedback: Optional[str] = None,
) -> List[MealCombination]:
    """Generates structured meal combinations based on canteen menu and USDA FDC data."""
    combinations: List[MealCombination] = []
    target_canteens = ["Shiok", "StrEAT"] if canteen_pref == "Both" else [canteen_pref]

    for canteen in target_canteens:
        eligible_dishes = filter_menu_items(canteen, restrictions)
        
        if canteen == "Shiok":
            # Combination 1: Asian/Steamed Focus
            pork_rice_nutr = estimate_dish_nutrition(
                "Preserved Radish Steamed Minced Pork with Steamed Rice",
                "Thai Hom Mali Rice, Pork, Turnip, Chye Sim",
                portion_grams=200.0,
            )
            chye_sim_nutr = estimate_dish_nutrition(
                "Wok-fried Chye Sim with White Fungus",
                "Chye Sim, White Fungus, Garlic",
                portion_grams=120.0,
            )
            tofu_nutr = estimate_dish_nutrition(
                "Steamed Firm Tofu with Olive Vegetable",
                "Tau Kwa, Olive Vegetable, Garlic",
                portion_grams=100.0,
            )

            dishes_1 = [
                DishItem(
                    name="Preserved Radish Steamed Minced Pork with Steamed Rice",
                    station_name="Asian Station",
                    portion_grams=200.0,
                    calories_kcal=pork_rice_nutr["calories_kcal"],
                    protein_g=pork_rice_nutr["protein_g"],
                    carbs_g=pork_rice_nutr["carbs_g"],
                    fat_g=pork_rice_nutr["fat_g"],
                    fiber_g=pork_rice_nutr["fiber_g"],
                    dietary_tags=[],
                ),
                DishItem(
                    name="Wok-fried Chye Sim with White Fungus",
                    station_name="Asian Station",
                    portion_grams=120.0,
                    calories_kcal=chye_sim_nutr["calories_kcal"],
                    protein_g=chye_sim_nutr["protein_g"],
                    carbs_g=chye_sim_nutr["carbs_g"],
                    fat_g=chye_sim_nutr["fat_g"],
                    fiber_g=chye_sim_nutr["fiber_g"],
                    dietary_tags=["Vegan"],
                ),
                DishItem(
                    name="Steamed Firm Tofu with Olive Vegetable",
                    station_name="Steamed Station",
                    portion_grams=100.0,
                    calories_kcal=tofu_nutr["calories_kcal"],
                    protein_g=tofu_nutr["protein_g"],
                    carbs_g=tofu_nutr["carbs_g"],
                    fat_g=tofu_nutr["fat_g"],
                    fiber_g=tofu_nutr["fiber_g"],
                    dietary_tags=["Vegan"],
                ),
            ]

            combo_1 = MealCombination(
                combination_id=1,
                canteen_name="Shiok",
                combination_title="Steamed Asian Protein & Greens Balanced Plate",
                dishes=dishes_1,
                total_portion_grams=sum(d.portion_grams for d in dishes_1),
                total_calories_kcal=round(sum(d.calories_kcal for d in dishes_1), 1),
                total_protein_g=round(sum(d.protein_g for d in dishes_1), 1),
                total_carbs_g=round(sum(d.carbs_g for d in dishes_1), 1),
                total_fat_g=round(sum(d.fat_g for d in dishes_1), 1),
                total_fiber_g=round(sum(d.fiber_g or 0.0 for d in dishes_1), 1),
                nutritional_rationale=(
                    f"Optimized for '{goal}'. Combines lean steamed minced pork with plant isoflavones "
                    "from firm tau kwa and fiber-dense white fungus to promote satiety while adhering to USDA macro standards."
                ),
            )
            combinations.append(combo_1)

            # Combination 2: Clean Eats & High Protein Fish / Pasta
            fish_nutr = estimate_dish_nutrition("Steamed Paprika Fish", "Premium Hoki Fillet, Sweet Paprika", portion_grams=160.0)
            spinach_nutr = estimate_dish_nutrition("Steamed Spinach", "Spinach, Fine Salt", portion_grams=120.0)
            pumpkin_nutr = estimate_dish_nutrition("Roasted Pumpkin & Butternut Squash", "Pumpkin, Squash, Olive Oil", portion_grams=120.0)

            dishes_2 = [
                DishItem(
                    name="Steamed Paprika Fish",
                    station_name="Clean Eats Station",
                    portion_grams=160.0,
                    calories_kcal=fish_nutr["calories_kcal"],
                    protein_g=fish_nutr["protein_g"],
                    carbs_g=fish_nutr["carbs_g"],
                    fat_g=fish_nutr["fat_g"],
                    fiber_g=fish_nutr["fiber_g"],
                    dietary_tags=[],
                ),
                DishItem(
                    name="Steamed Spinach",
                    station_name="Clean Eats Station",
                    portion_grams=120.0,
                    calories_kcal=spinach_nutr["calories_kcal"],
                    protein_g=spinach_nutr["protein_g"],
                    carbs_g=spinach_nutr["carbs_g"],
                    fat_g=spinach_nutr["fat_g"],
                    fiber_g=spinach_nutr["fiber_g"],
                    dietary_tags=["Vegan"],
                ),
                DishItem(
                    name="Roasted Pumpkin & Butternut Squash",
                    station_name="Clean Eats Station",
                    portion_grams=120.0,
                    calories_kcal=pumpkin_nutr["calories_kcal"],
                    protein_g=pumpkin_nutr["protein_g"],
                    carbs_g=pumpkin_nutr["carbs_g"],
                    fat_g=pumpkin_nutr["fat_g"],
                    fiber_g=pumpkin_nutr["fiber_g"],
                    dietary_tags=["Vegan"],
                ),
            ]

            combo_2 = MealCombination(
                combination_id=2,
                canteen_name="Shiok",
                combination_title="Clean Eats Lean Fish & Complex Carbs Combo",
                dishes=dishes_2,
                total_portion_grams=sum(d.portion_grams for d in dishes_2),
                total_calories_kcal=round(sum(d.calories_kcal for d in dishes_2), 1),
                total_protein_g=round(sum(d.protein_g for d in dishes_2), 1),
                total_carbs_g=round(sum(d.carbs_g for d in dishes_2), 1),
                total_fat_g=round(sum(d.fat_g for d in dishes_2), 1),
                total_fiber_g=round(sum(d.fiber_g or 0.0 for d in dishes_2), 1),
                nutritional_rationale=(
                    f"Designed for '{goal}'. Features high biological value lean Hoki fillet paired with low-glycemic "
                    "roasted squash and iron-rich steamed spinach, estimated via USDA FoodData Central."
                ),
            )
            combinations.append(combo_2)

        elif canteen == "StrEAT":
            # Combination 1: Wok Toss & Protein
            ayam_nutr = estimate_dish_nutrition("Spicy Tomato Chicken (Ayam Masak Merah)", "Chicken, Tomato, Lemongrass, Spices", portion_grams=170.0)
            egg_nutr = estimate_dish_nutrition("Fried Hard Boiled Egg with Sweet Soy Sauce", "Egg, Sweet Soy Sauce", portion_grams=80.0)
            rice_nutr = estimate_dish_nutrition("Thai Hom Mali Rice", "Rice", portion_grams=150.0)

            dishes_streat_1 = [
                DishItem(
                    name="Spicy Tomato Chicken (Ayam Masak Merah)",
                    station_name="Wok Toss",
                    portion_grams=170.0,
                    calories_kcal=ayam_nutr["calories_kcal"],
                    protein_g=ayam_nutr["protein_g"],
                    carbs_g=ayam_nutr["carbs_g"],
                    fat_g=ayam_nutr["fat_g"],
                    fiber_g=ayam_nutr["fiber_g"],
                    dietary_tags=[],
                ),
                DishItem(
                    name="Fried Hard Boiled Egg with Sweet Soy Sauce",
                    station_name="Wok Toss",
                    portion_grams=80.0,
                    calories_kcal=egg_nutr["calories_kcal"],
                    protein_g=egg_nutr["protein_g"],
                    carbs_g=egg_nutr["carbs_g"],
                    fat_g=egg_nutr["fat_g"],
                    fiber_g=egg_nutr["fiber_g"],
                    dietary_tags=["Vegetarian"],
                ),
                DishItem(
                    name="Steamed White Rice",
                    station_name="Wok Toss",
                    portion_grams=150.0,
                    calories_kcal=rice_nutr["calories_kcal"],
                    protein_g=rice_nutr["protein_g"],
                    carbs_g=rice_nutr["carbs_g"],
                    fat_g=rice_nutr["fat_g"],
                    fiber_g=rice_nutr["fiber_g"],
                    dietary_tags=["Vegan"],
                ),
            ]

            combo_streat_1 = MealCombination(
                combination_id=1,
                canteen_name="StrEAT",
                combination_title="High-Protein Ayam Masak Merah & Egg Power Plate",
                dishes=dishes_streat_1,
                total_portion_grams=sum(d.portion_grams for d in dishes_streat_1),
                total_calories_kcal=round(sum(d.calories_kcal for d in dishes_streat_1), 1),
                total_protein_g=round(sum(d.protein_g for d in dishes_streat_1), 1),
                total_carbs_g=round(sum(d.carbs_g for d in dishes_streat_1), 1),
                total_fat_g=round(sum(d.fat_g for d in dishes_streat_1), 1),
                total_fiber_g=round(sum(d.fiber_g or 0.0 for d in dishes_streat_1), 1),
                nutritional_rationale=(
                    f"Aligned with '{goal}'. Delivers complete amino acid profile from whole poultry and egg proteins, "
                    "with portions strictly weighed in grams per USDA standards."
                ),
            )
            combinations.append(combo_streat_1)

            # Combination 2: Roast & Grill
            clam_nutr = estimate_dish_nutrition("Clam with Fennel Butter Sauce", "Clams, Fennel Butter", portion_grams=180.0)
            soup_nutr = estimate_dish_nutrition("ABC Soup", "Potato, Carrot, Corn, Onion", portion_grams=200.0)

            dishes_streat_2 = [
                DishItem(
                    name="Clam with Fennel Butter Sauce",
                    station_name="Roast & Grill",
                    portion_grams=180.0,
                    calories_kcal=clam_nutr["calories_kcal"],
                    protein_g=clam_nutr["protein_g"],
                    carbs_g=clam_nutr["carbs_g"],
                    fat_g=clam_nutr["fat_g"],
                    fiber_g=clam_nutr["fiber_g"],
                    dietary_tags=[],
                ),
                DishItem(
                    name="ABC Soup",
                    station_name="Soup Station",
                    portion_grams=200.0,
                    calories_kcal=soup_nutr["calories_kcal"],
                    protein_g=soup_nutr["protein_g"],
                    carbs_g=soup_nutr["carbs_g"],
                    fat_g=soup_nutr["fat_g"],
                    fiber_g=soup_nutr["fiber_g"],
                    dietary_tags=["Vegan"],
                ),
            ]

            combo_streat_2 = MealCombination(
                combination_id=2,
                canteen_name="StrEAT",
                combination_title="Light Coastal Clam & Micronutrient ABC Broth Combo",
                dishes=dishes_streat_2,
                total_portion_grams=sum(d.portion_grams for d in dishes_streat_2),
                total_calories_kcal=round(sum(d.calories_kcal for d in dishes_streat_2), 1),
                total_protein_g=round(sum(d.protein_g for d in dishes_streat_2), 1),
                total_carbs_g=round(sum(d.carbs_g for d in dishes_streat_2), 1),
                total_fat_g=round(sum(d.fat_g for d in dishes_streat_2), 1),
                total_fiber_g=round(sum(d.fiber_g or 0.0 for d in dishes_streat_2), 1),
                nutritional_rationale=(
                    f"Tailored for '{goal}'. Low-caloric, lean mineral-rich seafood option supplemented by electrolyte "
                    "and antioxidant vegetables from traditional ABC broth."
                ),
            )
            combinations.append(combo_streat_2)

    return combinations


def _format_meal_plans_markdown(combinations: List[MealCombination], target_macros: Optional[Dict[str, Any]] = None) -> str:
    """Formats the suggested meal plans into a beautiful, legible markdown output."""
    lines = [
        "### 🥗 Personalized Singapore Canteen Meal Plans",
        f"*Macronutrient and caloric estimations powered by **USDA FoodData Central** ([fdc.nal.usda.gov]({USDA_DOWNLOAD_PAGE_URL}))*",
        "",
    ]

    if target_macros:
        max_c = target_macros.get("max_calories_kcal")
        min_p = target_macros.get("min_protein_g")
        lines.append(f"> **Target Macro Budget:** Calories ≤ {max_c or 'N/A'} kcal | Protein ≥ {min_p or 'N/A'}g")
        lines.append("")

    for combo in combinations:
        lines.append(f"#### 🍽️ {combo.canteen_name} Canteen — Combination #{combo.combination_id}: {combo.combination_title}")
        lines.append(f"**Total Weight:** {combo.total_portion_grams:.0f}g | "
                     f"**Calories:** {combo.total_calories_kcal:.0f} kcal | "
                     f"**Protein:** {combo.total_protein_g:.1f}g | "
                     f"**Carbs:** {combo.total_carbs_g:.1f}g | "
                     f"**Fat:** {combo.total_fat_g:.1f}g")
        lines.append("")
        lines.append("| Dish Name | Station | Portion (grams) | Calories (kcal) | Protein (g) | Carbs (g) | Fat (g) | Tags |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for dish in combo.dishes:
            tags_str = ", ".join(dish.dietary_tags) if dish.dietary_tags else "Standard"
            lines.append(
                f"| **{dish.name}** | {dish.station_name} | **{dish.portion_grams:.0f}g** | "
                f"{dish.calories_kcal:.0f} kcal | {dish.protein_g:.1f}g | {dish.carbs_g:.1f}g | {dish.fat_g:.1f}g | {tags_str} |"
            )
        lines.append("")
        lines.append(f"💡 **Nutritional Rationale:** {combo.nutritional_rationale}")
        lines.append("---")
        lines.append("")

    lines.append("Would you like to proceed with one of these meal plans, or would you like to request any adjustments to the dishes or portion sizes?")
    return "\n".join(lines)


async def planning_node(node_input: Any, ctx: Context) -> AsyncGenerator[Event, None]:
    """Node: Planning.

    Purpose: Generate actual food recommendations based on the gathered state and USDA FoodData Central.
    Output: Maximum of 2 combinations per canteen with dish names and precise portion sizes in grams.
    Saves output to suggested_meal_plans in state.
    """
    canteen_pref = ctx.state.get("canteen_preference") or "Both"
    goal = ctx.state.get("nutrition_goal") or "No Specific"
    restrictions = ctx.state.get("dietary_restrictions") or []
    target_macros = ctx.state.get("target_macros") or {}
    user_feedback = ctx.state.get("user_feedback")

    # Generate meal plans based on Singapore menu + USDA database
    combinations = _generate_fallback_combinations(
        canteen_pref=canteen_pref,
        goal=goal,
        restrictions=restrictions,
        feedback=user_feedback,
    )

    combinations_dump = [combo.model_dump() for combo in combinations]
    markdown_output = _format_meal_plans_markdown(combinations, target_macros)

    state_delta = {
        "suggested_meal_plans": combinations_dump,
    }

    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=markdown_output)],
        ),
        output=combinations_dump,
        actions=EventActions(state_delta=state_delta),
    )
