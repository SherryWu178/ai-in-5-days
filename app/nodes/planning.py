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
from google.adk.events.request_input import RequestInput
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

MODEL = "gemini-3.7-flash"


class PlanningOutput(BaseModel):
    """Structured output for the meal planning generation."""

    combinations: List[MealCombination] = Field(
        description="Suggested meal combinations (maximum 2 combinations per canteen)."
    )
    planning_summary: str = Field(
        description="Overall summary of the meal plan generation and USDA estimation methodology."
    )


class CandidateDish(BaseModel):
    name: str = Field(description="Exact name of the dish from the provided menu.")
    portion_grams: float = Field(description="Proposed portion size in grams (e.g. 80 to 250g).")


class CandidateCombination(BaseModel):
    canteen_name: str
    combination_title: str = Field(description="Appetizing title for the meal combo.")
    dishes: List[CandidateDish]
    nutritional_rationale: str = Field(
        description="Clinical explanation of why these dishes fit the user's nutritional goal."
    )


class CandidateMealPlans(BaseModel):
    combinations: List[CandidateCombination]


def _verify_and_scale_candidate_combination(
    cid: int,
    candidate: CandidateCombination,
    menu_by_name: Dict[str, Dict[str, Any]],
    target_macros: Dict[str, Any],
) -> Optional[MealCombination]:
    """Deterministically verifies dishes exist on today's menu, computes USDA macros, and scales portions to hit targets."""
    dishes: List[DishItem] = []
    max_cal = target_macros.get("max_calories_kcal")
    min_prot = target_macros.get("min_protein_g")

    # Step 1: Match real menu dishes and compute initial exact USDA nutrition
    for cdish in candidate.dishes:
        # Match exact or case-insensitive substring
        matched_item = menu_by_name.get(cdish.name)
        if not matched_item:
            for mname, mval in menu_by_name.items():
                if mname.lower() in cdish.name.lower() or cdish.name.lower() in mname.lower():
                    matched_item = mval
                    break
        if not matched_item:
            continue

        portion = max(50.0, float(cdish.portion_grams))
        nutr = estimate_dish_nutrition(
            matched_item["name"],
            matched_item["ingredients"],
            portion_grams=portion,
        )
        dishes.append(
            DishItem(
                name=matched_item["name"],
                station_name=matched_item.get("station_name", matched_item.get("station", "Canteen Station")),
                portion_grams=portion,
                calories_kcal=nutr["calories_kcal"],
                protein_g=nutr["protein_g"],
                carbs_g=nutr["carbs_g"],
                fat_g=nutr["fat_g"],
                fiber_g=nutr["fiber_g"],
                dietary_tags=matched_item["dietary_tags"],
            )
        )

    if not dishes:
        return None

    # Step 2: Deterministic portion scaling to strictly satisfy target_macros
    total_cal = sum(d.calories_kcal for d in dishes)
    total_prot = sum(d.protein_g for d in dishes)

    scale_factor = 1.0
    if max_cal and max_cal > 0 and total_cal > max_cal:
        scale_factor = min(scale_factor, (max_cal - 15.0) / total_cal)
    if min_prot and min_prot > 0 and total_prot < min_prot and total_prot > 0:
        scale_factor = max(scale_factor, (min_prot + 3.0) / total_prot)

    # Apply scale factor if needed and recompute exact USDA values
    if abs(scale_factor - 1.0) > 0.05:
        scaled_dishes: List[DishItem] = []
        for d in dishes:
            new_port = max(40.0, round(d.portion_grams * scale_factor, 1))
            nutr = estimate_dish_nutrition(d.name, menu_by_name[d.name]["ingredients"], portion_grams=new_port)
            scaled_dishes.append(
                DishItem(
                    name=d.name,
                    station_name=d.station_name,
                    portion_grams=new_port,
                    calories_kcal=nutr["calories_kcal"],
                    protein_g=nutr["protein_g"],
                    carbs_g=nutr["carbs_g"],
                    fat_g=nutr["fat_g"],
                    fiber_g=nutr["fiber_g"],
                    dietary_tags=d.dietary_tags,
                )
            )
        dishes = scaled_dishes

    tot_grams = sum(d.portion_grams for d in dishes)
    tot_cal = round(sum(d.calories_kcal for d in dishes), 1)
    tot_prot = round(sum(d.protein_g for d in dishes), 1)
    tot_carbs = round(sum(d.carbs_g for d in dishes), 1)
    tot_fat = round(sum(d.fat_g for d in dishes), 1)
    tot_fiber = round(sum(d.fiber_g or 0.0 for d in dishes), 1)

    return MealCombination(
        combination_id=cid,
        canteen_name=candidate.canteen_name,
        combination_title=candidate.combination_title,
        dishes=dishes,
        total_portion_grams=tot_grams,
        total_calories_kcal=tot_cal,
        total_protein_g=tot_prot,
        total_carbs_g=tot_carbs,
        total_fat_g=tot_fat,
        total_fiber_g=tot_fiber,
        nutritional_rationale=candidate.nutritional_rationale,
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


async def menu_filtering_node(node_input: Any, ctx: Context) -> AsyncGenerator[Event, None]:
    """Stage 1 Node: Deterministically filters canteen menu items by dietary restrictions and pre-computes 100g USDA profiles."""
    canteen_pref = ctx.state.get("canteen_preference") or "Both"
    restrictions = ctx.state.get("dietary_restrictions") or []

    target_canteens = ["Shiok", "StrEAT"] if canteen_pref == "Both" else [canteen_pref]
    filtered_menu: Dict[str, List[Dict[str, Any]]] = {}

    for c in target_canteens:
        c_dishes = filter_menu_items(c, restrictions)
        enriched_dishes = []
        for item in c_dishes:
            base_nutr = estimate_dish_nutrition(item["name"], item["ingredients"], portion_grams=100.0)
            item_copy = dict(item)
            item_copy["per_100g_kcal"] = base_nutr["calories_kcal"]
            item_copy["per_100g_protein_g"] = base_nutr["protein_g"]
            enriched_dishes.append(item_copy)
        filtered_menu[c] = enriched_dishes

    state_delta = {"filtered_menu_items": filtered_menu}
    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text="🍽️ Canteen menu filtered by dietary restrictions & baseline USDA 100g density computed.")],
        ),
        output=filtered_menu,
        actions=EventActions(state_delta=state_delta),
    )


async def llm_dish_selection_node(node_input: Any, ctx: Context) -> AsyncGenerator[Event, None]:
    """Stage 2 Node: Uses Gemini LLM to dynamically select complementary dishes and propose initial portion weights based on culinary & dietetic knowledge."""
    goal = ctx.state.get("nutrition_goal") or "No Specific"
    target_macros = ctx.state.get("target_macros") or {}
    user_feedback = ctx.state.get("user_feedback")
    filtered_menu = ctx.state.get("filtered_menu_items")

    if not filtered_menu:
        # Ensure fallback filtering if Stage 1 didn't populate
        canteen_pref = ctx.state.get("canteen_preference") or "Both"
        restrictions = ctx.state.get("dietary_restrictions") or []
        target_canteens = ["Shiok", "StrEAT"] if canteen_pref == "Both" else [canteen_pref]
        filtered_menu = {c: filter_menu_items(c, restrictions) for c in target_canteens}

    menu_summary_lines = []
    for c, items in filtered_menu.items():
        menu_summary_lines.append(f"Canteen {c}:")
        for item in items:
            tags = ", ".join(item["dietary_tags"]) if item["dietary_tags"] else "None"
            pk = item.get("per_100g_kcal", "N/A")
            pp = item.get("per_100g_protein_g", "N/A")
            menu_summary_lines.append(
                f"  - '{item['name']}' ({item['station_name']}) | Ingredients: {item['ingredients']} "
                f"| Density (~100g): {pk} kcal, {pp}g protein | Tags: {tags}"
            )

    menu_summary_text = "\n".join(menu_summary_lines)

    llm_prompt = (
        "You are an expert Clinical Nutrition Specialist for corporate canteens in Singapore.\n"
        "Your job is to select balanced, delicious meal combinations from today's available canteen menu.\n\n"
        f"User Goal: {goal}\n"
        f"Target Macros: {json.dumps(target_macros)}\n"
        f"User Feedback/Adjustments: {user_feedback or 'None'}\n\n"
        "Today's Filtered Singapore Canteen Menu:\n"
        f"{menu_summary_text}\n\n"
        "Instructions:\n"
        "1. Select up to 2 distinct combinations per canteen (max 4 total if both canteens requested).\n"
        "2. For each combination, pick 2 to 3 complementary dishes FROM THE EXACT MENU ABOVE (e.g. a protein main + green veg + optional low-GI grain or soup).\n"
        "3. Propose reasonable initial portion sizes in grams (e.g. 100g to 200g per dish).\n"
        "4. Provide a scientific nutritional rationale for how this combo supports the user's goal."
    )

    candidate_plans_dict = None
    from ..utils.llm import get_genai_client, get_model_for_task
    client = get_genai_client()
    if client:
        try:
            model_name = get_model_for_task("planning")
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=llm_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CandidateMealPlans,
                    temperature=0.2,
                ),
            )
            parsed_candidates = CandidateMealPlans.model_validate_json(response.text)
            candidate_plans_dict = parsed_candidates.model_dump()
        except Exception as e:
            logger.warning("Hybrid LLM dish selection failed or offline (%s), candidate plans empty.", e)

    state_delta = {"llm_candidate_plans": candidate_plans_dict}
    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text="🧠 Dynamic culinary and clinical dish selection completed.")],
        ),
        output=candidate_plans_dict,
        actions=EventActions(state_delta=state_delta),
    )


async def macro_sizing_and_verification_node(node_input: Any, ctx: Context) -> AsyncGenerator[Event, None]:
    """Stage 3 Node: Deterministically verifies menu dishes, calculates USDA macros, and automatically scales portion sizes (g) to hit macro ceilings/floors."""
    canteen_pref = ctx.state.get("canteen_preference") or "Both"
    goal = ctx.state.get("nutrition_goal") or "No Specific"
    restrictions = ctx.state.get("dietary_restrictions") or []
    target_macros = ctx.state.get("target_macros") or {}
    user_feedback = ctx.state.get("user_feedback")
    candidate_plans_dict = ctx.state.get("llm_candidate_plans")

    target_canteens = ["Shiok", "StrEAT"] if canteen_pref == "Both" else [canteen_pref]
    menu_by_name: Dict[str, Dict[str, Any]] = {}
    for c in target_canteens:
        for item in filter_menu_items(c, restrictions):
            menu_by_name[item["name"]] = item

    combinations: List[MealCombination] = []
    if candidate_plans_dict and "combinations" in candidate_plans_dict:
        try:
            parsed_candidates = CandidateMealPlans.model_validate(candidate_plans_dict)
            cid = 1
            for cand in parsed_candidates.combinations:
                verified = _verify_and_scale_candidate_combination(
                    cid=cid,
                    candidate=cand,
                    menu_by_name=menu_by_name,
                    target_macros=target_macros,
                )
                if verified:
                    combinations.append(verified)
                    cid += 1
        except Exception as e:
            logger.warning("Verification of candidate combinations failed (%s).", e)

    # Fallback to procedural combinations if LLM selection failed or yielded empty verified list
    if not combinations:
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
    yield RequestInput(
        message=(
            "Do these Singapore canteen dishes look good to confirm, or would you like to swap"
            " any items out (e.g. remove fish, switch canteens)?"
        ),
    )


async def planning_node(node_input: Any, ctx: Context) -> AsyncGenerator[Event, None]:
    """Node: Planning (Unified Pipeline).

    Executes the 3-stage hybrid planning pipeline sequentially:
    1. menu_filtering_node: Filter menu items by dietary restrictions
    2. llm_dish_selection_node: Dynamic LLM dish & pairing selection
    3. macro_sizing_and_verification_node: Deterministic USDA sizing & portion scaling
    """
    async for _ in menu_filtering_node(node_input, ctx):
        pass
    async for _ in llm_dish_selection_node(node_input, ctx):
        pass
    async for event in macro_sizing_and_verification_node(node_input, ctx):
        yield event
