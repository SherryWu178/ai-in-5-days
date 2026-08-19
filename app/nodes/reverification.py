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

"""User-Reverification Node for the Food Recommendation SubGraph."""

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

logger = logging.getLogger(__name__)

MODEL = "gemini-3.7-flash"


class ReverificationDecision(BaseModel):
    """Schema for evaluating user approval or modification requests."""

    user_agreed: bool = Field(
        description=(
            "True if the user accepts, likes, or agrees with the suggested meal plan "
            "(e.g. 'looks great', 'I love combination 1', 'agree', 'perfect', 'yes', 'thank you'). "
            "False if the user wants changes, different dishes, adjusted portions, or disagrees."
        )
    )
    user_feedback: Optional[str] = Field(
        default=None,
        description="The specific feedback, requested changes, or dietary adjustments mentioned by the user.",
    )


def _extract_text(node_input: Any) -> str:
    """Helper to extract clean string content."""
    if isinstance(node_input, str):
        return node_input.strip()
    if hasattr(node_input, "parts"):
        parts = [p.text for p in node_input.parts if getattr(p, "text", None)]
        return " ".join(parts).strip()
    if isinstance(node_input, dict):
        if "feedback" in node_input:
            return str(node_input["feedback"])
        if "text" in node_input:
            return str(node_input["text"])
    return str(node_input).strip()


async def user_reverification_node(node_input: Any, ctx: Context) -> AsyncGenerator[Event, None]:
    """Node: User-Reverification.

    Purpose: Present suggested_meal_plans interactively to the user and evaluate their approval or modifications.
    Routing Logic:
    - Phase 1 (Initial Presentation): Emits customer-facing prompt and RequestInput asking for confirmation without routing to 'approved', pausing for reply.
    - Phase 2 (User Reply Evaluation):
      - If user agrees: Route to 'approved' and conclude workflow.
      - If user disagrees/protests items: Extract protested items into dietary_restrictions, emit entertaining customer-facing replanning message, and route to 'replan'.
    """
    user_text = _extract_text(node_input)
    round_num = ctx.state.get("reverification_round", 0)

    # Evaluate user's response to the meal plan RequestInput
    prompt = (
        "You are evaluating a user's response to suggested nutrition meal plans for Singapore canteens.\n"
        "Determine if the user agrees/approves the meal plan or wants changes/has feedback.\n\n"
        f"User Response: {user_text}\n"
    )

    from ..utils.llm import get_genai_client
    client = get_genai_client()
    if client:
        try:
            response = await client.aio.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ReverificationDecision,
                    temperature=0.0,
                ),
            )
            decision = ReverificationDecision.model_validate_json(response.text)
            user_agreed = decision.user_agreed
            feedback_text = decision.user_feedback or user_text
        except Exception as e:
            logger.warning("LLM reverification evaluation failed: %s. Using heuristics.", e)
            client = None
    if not client:
        text_lower = user_text.lower()
        disagreement_signals = [
            "no", "change", "different", "instead", "less", "more", "swap", "replace",
            "modify", "don't like", "disagree", "adjust", "portion", "remove", "without"
        ]
        if any(w in text_lower for w in disagreement_signals):
            user_agreed = False
            feedback_text = user_text
        else:
            user_agreed = True
            feedback_text = None

    if user_agreed:
        success_msg = (
            "✅ **Meal Plan Officially Approved!**\n\n"
            "Your personalized Singapore canteen meal plan is confirmed and saved. "
            "All portions and macronutrients have been estimated and optimized for your goals. "
            "Bon appétit! 🍽️"
        )
        yield Event(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=success_msg)],
            ),
            output="Plan approved successfully.",
            actions=EventActions(route="approved"),
        )
    else:
        # Extract protested foods/ingredients to exclude in Stage 1 menu filtering
        text_lower = (feedback_text or user_text).lower()
        current_restrictions = list(ctx.state.get("dietary_restrictions") or [])
        protest_keywords = ["fish", "seafood", "pork", "tofu", "chicken", "beef", "egg", "spicy"]
        protested_added = []
        for pk in protest_keywords:
            if pk in text_lower and pk not in current_restrictions:
                current_restrictions.append(pk)
                protested_added.append(pk)

        protest_note = f" (Excluding protested item(s): {', '.join(protested_added)})" if protested_added else ""
        feedback_msg = (
            f"👨‍🍳 **Heard loud and clear! Updating your Canteen Menu...**\n\n"
            f"Received your feedback: *'{feedback_text}'*{protest_note}\n\n"
            f"Sending our AI chef back into the Singapore canteen kitchen! We are removing any unwanted dishes, "
            f"selecting fresh complementary alternatives from today's live menu, and re-calculating your exact USDA gram portions. One moment please..."
        )
        state_delta = {
            "user_feedback": feedback_text,
            "dietary_restrictions": current_restrictions,
            "plan_presented_for_verification": False,
            "reverification_round": round_num + 1,
        }
        yield Event(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=feedback_msg)],
            ),
            output=feedback_text,
            actions=EventActions(state_delta=state_delta, route="replan"),
        )


def finish_recommendation_node(node_input: Any) -> AsyncGenerator[Event, None]:
    """Terminal node for successful completion of the Food Recommendation workflow."""
    yield Event(
        output="Nutrition workflow completed successfully.",
    )
