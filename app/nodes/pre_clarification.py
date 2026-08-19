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

"""Pre-Clarification Node for the Food Recommendation SubGraph."""

from collections.abc import AsyncGenerator
import json
import logging
from typing import Any, Dict, List, Optional

from google import genai
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types
from pydantic import BaseModel, Field

from ..state import (
    NutritionGoalType,
    NutritionState,
    TargetMacros,
    VALID_CANTEENS,
    VALID_NUTRITION_GOALS,
)

logger = logging.getLogger(__name__)

MODEL = "gemini-3.7-flash"


class ClarificationExtraction(BaseModel):
    """Structured extraction of nutrition consultation parameters."""

    canteen_preference: Optional[str] = Field(
        default=None,
        description="Extracted canteen: 'Shiok' (Floor 7), 'StrEAT' (Floor 30), or 'Both'. Null if unknown.",
    )
    nutrition_goal: Optional[str] = Field(
        default=None,
        description=(
            "Must be mapped strictly to one of: 'No Specific', 'Low GI', "
            "'Cut Down Body Fat', 'High Protein for Muscle Gain'. Null if unspecified."
        ),
    )
    dietary_restrictions: Optional[List[str]] = Field(
        default=None,
        description="List of dietary restrictions/allergies (e.g. ['halal', 'vegan', 'dairy allergy', 'gluten-free']).",
    )
    custom_target_macros: Optional[TargetMacros] = Field(
        default=None,
        description="Optional specific macro targets translated from user goals.",
    )


def compute_target_macros_for_goal(goal: Optional[str]) -> TargetMacros:
    """Translates a nutrition goal category into concrete macronutrient targets."""
    if goal == "Cut Down Body Fat":
        return TargetMacros(
            max_calories_kcal=550.0,
            min_protein_g=35.0,
            max_carbs_g=45.0,
            max_fat_g=15.0,
            min_fiber_g=8.0,
            guideline_notes="Caloric deficit target focusing on high protein satiety and lean green vegetables.",
        )
    elif goal == "High Protein for Muscle Gain":
        return TargetMacros(
            max_calories_kcal=850.0,
            min_protein_g=50.0,
            max_carbs_g=80.0,
            max_fat_g=22.0,
            min_fiber_g=6.0,
            guideline_notes="High-protein hypertrophy plan (>=50g protein) with substantial complex carbohydrates.",
        )
    elif goal == "Low GI":
        return TargetMacros(
            max_calories_kcal=600.0,
            min_protein_g=30.0,
            max_carbs_g=50.0,
            max_fat_g=18.0,
            min_fiber_g=12.0,
            guideline_notes="Low Glycemic Index focus with high-fiber grains, legumes, and non-starchy vegetables to avoid glucose spikes.",
        )
    else:  # "No Specific" or default
        return TargetMacros(
            max_calories_kcal=650.0,
            min_protein_g=25.0,
            max_carbs_g=70.0,
            max_fat_g=20.0,
            min_fiber_g=6.0,
            guideline_notes="Balanced daily nutritional profile meeting Singapore HPB healthy plate guidelines.",
        )


async def pre_clarification_node(node_input: Any, ctx: Context) -> AsyncGenerator[Event, None]:
    """Node: Pre-Clarification.

    Purpose: Gather missing information from the user (canteen_preference, nutrition_goal, dietary_restrictions).
    Behavior: Check current state. If information is missing, extract from the query or prompt the user.
    Translates the nutrition_goal into target_macros before passing state forward.
    """
    user_text = str(node_input).strip() if node_input else ""

    # If the user is replying to our verification prompt, fast-forward straight to user_reverification_node
    if ctx.state.get("plan_presented_for_verification"):
        yield Event(
            output=node_input,
            actions=EventActions(route="verify"),
        )
        return

    # Current state values
    current_canteen = ctx.state.get("canteen_preference")
    current_goal = ctx.state.get("nutrition_goal")
    current_restrictions = ctx.state.get("dietary_restrictions")
    current_macros = ctx.state.get("target_macros")

    # LLM extraction prompt
    extraction_prompt = (
        "You are an expert clinical nutrition intake specialist for Singapore corporate canteens.\n"
        "Your task is to parse the user's message and extract their canteen preference, "
        "nutrition goal, and dietary restrictions.\n\n"
        "Rules:\n"
        "1. canteen_preference: Available canteens are 'Shiok' (Floor 7) and 'StrEAT' (Floor 30). "
        "If the user mentions both or doesn't mind, use 'Both'.\n"
        "2. nutrition_goal: MUST map strictly to one of:\n"
        "   - 'No Specific'\n"
        "   - 'Low GI'\n"
        "   - 'Cut Down Body Fat'\n"
        "   - 'High Protein for Muscle Gain'\n"
        "3. dietary_restrictions: Identify any allergies or restrictions (e.g. halal, no-pork, vegan, vegetarian, celiac, lactose intolerant).\n\n"
        f"User Message: {user_text}\n"
        f"Current State - Canteen: {current_canteen}, Goal: {current_goal}, Restrictions: {current_restrictions}"
    )

    extracted_canteen = current_canteen
    extracted_goal = current_goal
    extracted_restrictions = current_restrictions or []
    extracted_macros = current_macros

    from ..utils.llm import get_genai_client
    client = get_genai_client()
    if client:
        try:
            response = await client.aio.models.generate_content(
                model=MODEL,
                contents=extraction_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ClarificationExtraction,
                    temperature=0.0,
                ),
            )
            parsed = ClarificationExtraction.model_validate_json(response.text)
            if parsed.canteen_preference and not extracted_canteen:
                extracted_canteen = parsed.canteen_preference
            if parsed.nutrition_goal and not extracted_goal:
                goal_lower = parsed.nutrition_goal.lower()
                for g in VALID_NUTRITION_GOALS:
                    if g.lower() == goal_lower:
                        extracted_goal = g
                        break
                if not extracted_goal:
                    if any(w in goal_lower for w in ["protein", "pretain", "protain", "muscle", "bulk", "gain"]):
                        extracted_goal = "High Protein for Muscle Gain"
                    elif any(w in goal_lower for w in ["fat", "cut", "loss", "lose", "weight", "calorie", "lean"]):
                        extracted_goal = "Cut Down Body Fat"
                    elif any(w in goal_lower for w in ["gi", "glycemic", "sugar", "diabetes"]):
                        extracted_goal = "Low GI"
            if parsed.dietary_restrictions:
                extracted_restrictions = list(set(extracted_restrictions + parsed.dietary_restrictions))
            if parsed.custom_target_macros:
                extracted_macros = parsed.custom_target_macros.model_dump()
        except Exception as e:
            logger.warning("LLM extraction encountered an error: %s. Using heuristics.", e)

    text_lower = user_text.lower()
    if not extracted_canteen:
        if "shiok" in text_lower and "streat" not in text_lower:
            extracted_canteen = "Shiok"
        elif "streat" in text_lower and "shiok" not in text_lower:
            extracted_canteen = "StrEAT"
        elif "both" in text_lower or ("shiok" in text_lower and "streat" in text_lower):
            extracted_canteen = "Both"

    if not extracted_goal:
        if any(w in text_lower for w in ["protein", "pretain", "protain", "prtain", "protin", "muscle", "bulk", "gain", "hypertrophy", "strength"]):
            extracted_goal = "High Protein for Muscle Gain"
        elif any(w in text_lower for w in ["fat", "cut", "weight loss", "lose weight", "low calorie", "lean", "slim", "shred"]):
            extracted_goal = "Cut Down Body Fat"
        elif any(w in text_lower for w in ["low gi", "glycemic", "diabetes", "diabetic", "sugar", "insulin"]):
            extracted_goal = "Low GI"
        elif any(w in text_lower for w in ["no specific", "general"]):
            extracted_goal = "No Specific"

    if "halal" in text_lower or "no pork" in text_lower:
        if "halal" not in extracted_restrictions:
            extracted_restrictions.append("halal")
    if "vegan" in text_lower:
        if "vegan" not in extracted_restrictions:
            extracted_restrictions.append("vegan")
    if "vegetarian" in text_lower:
        if "vegetarian" not in extracted_restrictions:
            extracted_restrictions.append("vegetarian")

    # Default fallback if still not specified
    if not extracted_canteen:
        extracted_canteen = "Both"
    if not extracted_goal:
        extracted_goal = "No Specific"
    if extracted_restrictions is None:
        extracted_restrictions = []

    calculated_macros = compute_target_macros_for_goal(extracted_goal)
    target_macros_dict = calculated_macros.model_dump()

    state_delta = {
        "canteen_preference": extracted_canteen,
        "nutrition_goal": extracted_goal,
        "dietary_restrictions": extracted_restrictions,
        "target_macros": target_macros_dict,
    }

    # Emit informational intake summary
    summary_message = (
        f"📋 **Nutrition Consultation Intake Confirmed**\n\n"
        f"- **Canteen Preference:** {extracted_canteen}\n"
        f"- **Nutrition Goal:** {extracted_goal}\n"
        f"- **Target Macros:** ≤{calculated_macros.max_calories_kcal:.0f} kcal, "
        f"≥{calculated_macros.min_protein_g:.0f}g Protein, "
        f"≤{calculated_macros.max_carbs_g:.0f}g Carbs, "
        f"≤{calculated_macros.max_fat_g:.0f}g Fat\n"
        f"- **Dietary Restrictions:** {', '.join(extracted_restrictions) if extracted_restrictions else 'None declared'}\n\n"
        f"Proceeding to formulate tailored meal plans based on Singapore canteen menu & USDA FoodData Central..."
    )

    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=summary_message)],
        ),
        output=state_delta,
        actions=EventActions(state_delta=state_delta, route="plan"),
    )
