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

"""Greeting & User Preference Memory Extraction Nodes for the Singapore Canteen Agent."""

from collections.abc import AsyncGenerator
import logging
from typing import Any, Optional

from google import genai
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.events.request_input import RequestInput
from google.genai import types
from pydantic import BaseModel, Field

from ..state import NutritionGoalType, UserProfileMemory
from ..tools.preference_memory import get_user_profile_memory, save_user_profile_memory

logger = logging.getLogger(__name__)

MODEL = "gemini-3.7-flash"


async def greeting_node(node_input: Any, ctx: Context) -> AsyncGenerator[Event, None]:
    """Node: Initial Greeting & Preference Memory Lookup (Turn 0 Hardcoded Welcome + Memory Display)."""
    user_id = ctx.state.get("user_id") or "sherrywuyujin@google.com"
    memory = get_user_profile_memory(user_id)

    user_text = str(node_input).strip() if node_input else ""
    state_delta: dict[str, Any] = {"user_id": user_id}

    if memory:
        state_delta["user_profile_memory"] = memory.model_dump()
        if not ctx.state.get("canteen_preference") and memory.preferred_canteen:
            state_delta["canteen_preference"] = memory.preferred_canteen
        if not ctx.state.get("nutrition_goal") and memory.default_nutrition_goal:
            state_delta["nutrition_goal"] = memory.default_nutrition_goal
        if not ctx.state.get("dietary_restrictions") and memory.permanent_dietary_restrictions:
            state_delta["dietary_restrictions"] = list(memory.permanent_dietary_restrictions)

        restr_str = ", ".join(memory.permanent_dietary_restrictions) if memory.permanent_dietary_restrictions else "None"
        greeting_text = (
            f"👋 **Welcome back, `{user_id}`!**\n\n"
            f"Here is your saved Singapore Canteen Nutrition Profile from memory:\n"
            f"- **Preferred Canteen:** `{memory.preferred_canteen or 'Any'}`\n"
            f"- **Default Goal:** `{memory.default_nutrition_goal or 'No Specific'}`\n"
            f"- **Avoided Foods / Restrictions:** `{restr_str}`\n\n"
            f"Would you like me to recommend today's lunch based on your saved profile, or do you have a different goal/canteen in mind today?"
        )
    else:
        greeting_text = (
            f"👋 **Welcome to the Singapore Corporate Canteen Nutrition Specialist!**\n\n"
            f"I can generate personalized meal plans and exact USDA FoodData Central macro estimates from live daily menus at **Shiok** (Floor 7) and **StrEAT** (Floor 30).\n\n"
            f"What is your preferred canteen, nutrition goal, or any dietary restrictions today?"
        )

    # Present Turn 0 greeting with retrieved memory and wait for user reaction
    if not ctx.state.get("greeting_presented") or not user_text or user_text.lower() in ["hi", "hello", "start", "greeting", "hey"]:
        state_delta["greeting_presented"] = True
        yield Event(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=greeting_text)],
            ),
            output=greeting_text,
            actions=EventActions(state_delta=state_delta),
        )
        yield RequestInput(
            message=greeting_text,
        )
        return

    # Turn 1+: User has reacted to the memory greeting; route their reaction to intent_classifier_node
    yield Event(
        output=node_input,
        actions=EventActions(state_delta=state_delta, route="classify"),
    )


class MemoryResolutionDecision(BaseModel):
    """Structured LLM decision distinguishing permanent user preferences from transient today-only choices."""

    reasoning: str = Field(
        description="Explanation distinguishing permanent user preferences from transient ('today-only') choices."
    )
    is_transient_canteen: bool = Field(
        description="True if the user's canteen choice was transient (e.g., 'i prefer level 30 today')."
    )
    preferred_canteen: Optional[str] = Field(
        default=None,
        description="Permanent preferred canteen ('Shiok', 'StrEAT', or 'Both'). Keep existing if today choice was transient."
    )
    default_nutrition_goal: Optional[str] = Field(
        default=None,
        description="Permanent default nutrition goal. Keep existing if today choice was transient."
    )
    permanent_dietary_restrictions: list[str] = Field(
        default_factory=list,
        description="Concise list of permanent allergies or disliked ingredients (e.g. ['fish', 'vegan']). Exclude transient today-only requests."
    )


async def preference_extraction_node(node_input: Any, ctx: Context) -> AsyncGenerator[Event, None]:
    """Node: Preference Memory Extraction with LLM Transient-vs-Permanent Resolution."""
    user_id = ctx.state.get("user_id") or "sherrywuyujin@google.com"
    canteen = ctx.state.get("canteen_preference")
    goal = ctx.state.get("nutrition_goal")
    raw_restrictions = list(ctx.state.get("dietary_restrictions") or [])
    user_feedback = ctx.state.get("user_feedback") or str(node_input)

    existing_mem = get_user_profile_memory(user_id)
    existing_canteen = existing_mem.preferred_canteen if existing_mem else "StrEAT"
    existing_goal = existing_mem.default_nutrition_goal if existing_mem else "High Protein for Muscle Gain"
    existing_restr = existing_mem.permanent_dietary_restrictions if existing_mem else []

    from ..utils.llm import get_genai_client

    client = get_genai_client()
    decision = None
    if client:
        prompt = (
            "You are the Long-Term Memory Manager for the Singapore Corporate Canteen Specialist AI.\n"
            f"User ID: `{user_id}`\n"
            f"Current Permanent Memory: Canteen='{existing_canteen}', Goal='{existing_goal}', Restrictions={existing_restr}\n"
            f"Current Session Canteen Used: '{canteen}'\n"
            f"Current Session Goal Used: '{goal}'\n"
            f"Current Session Restrictions: {raw_restrictions}\n"
            f"User Input / Feedback: \"{user_feedback}\"\n\n"
            "CRITICAL RULES:\n"
            "1. TRANSIENT vs PERMANENT: If the user says things like 'i prefer level 30 today', 'today I want StrEAT', or mentions 'today' / 'this lunch', treat that preference as TRANSIENT (`is_transient_canteen=True`) and DO NOT overwrite their permanent preferred_canteen or default_nutrition_goal in memory!\n"
            "2. PERMANENT UPDATES: Only update permanent preferred_canteen or default_nutrition_goal if the user explicitly states a long-term preference change or if no memory existed.\n"
            "3. DIETARY RESTRICTIONS: Retain existing permanent restrictions and merge any new permanent dietary restrictions, allergies, or disliked ingredients (e.g. 'fish', 'vegan'). Exclude transient today-only requests (e.g. 'no soup today'). Ensure all tags are concise keywords ≤ 25 characters."
        )
        try:
            response = await client.aio.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MemoryResolutionDecision,                ),
            )
            decision = MemoryResolutionDecision.model_validate_json(response.text)
        except Exception as e:
            logger.warning("LLM memory resolution failed (%s), using transient heuristic fallback.", e)
            decision = None

    if decision:
        final_canteen = existing_canteen if decision.is_transient_canteen else (decision.preferred_canteen or existing_canteen)
        final_goal = decision.default_nutrition_goal or existing_goal
        raw_restr_list = decision.permanent_dietary_restrictions
        reasoning_str = decision.reasoning
    else:
        fb_lower = str(user_feedback).lower()
        is_transient = any(w in fb_lower for w in ["today", "this lunch", "this meal", "just for today", "now"])
        final_canteen = existing_canteen if is_transient else (canteen or existing_canteen)
        final_goal = existing_goal if is_transient else (goal or existing_goal)
        raw_restr_list = existing_restr + raw_restrictions
        reasoning_str = "Heuristic check: transient keyword detected." if is_transient else "Merged session preferences."

    clean_restr = []
    for r in raw_restr_list:
        r_str = r.strip()
        if r_str and len(r_str) <= 25 and r_str not in clean_restr:
            clean_restr.append(r_str)

    updated_mem = UserProfileMemory(
        user_id=user_id,
        preferred_canteen=final_canteen,
        default_nutrition_goal=final_goal,
        permanent_dietary_restrictions=clean_restr,
    )

    # Execute memory persistence asynchronously as a non-blocking background task
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, save_user_profile_memory, updated_mem)
    except Exception:
        save_user_profile_memory(updated_mem)

    restr_display = ", ".join(updated_mem.permanent_dietary_restrictions) if updated_mem.permanent_dietary_restrictions else "None"
    memory_msg = (
        f"\n\n🧠 **Memory Manager Resolution (`{user_id}`):**\n"
        f"• *Reasoning:* {reasoning_str}\n"
        f"• *Persistent Canteen:* `{updated_mem.preferred_canteen}`\n"
        f"• *Persistent Goal:* `{updated_mem.default_nutrition_goal}`\n"
        f"• *Persistent Restrictions:* `{restr_display}`"
    )

    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=memory_msg)],
        ),
        output=updated_mem.model_dump(),
        actions=EventActions(route="complete"),
    )
