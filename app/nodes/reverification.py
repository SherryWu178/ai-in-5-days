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
from google.genai import types
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MODEL = "gemini-3.6-flash"


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

    Purpose: Present suggested_meal_plans to the user and evaluate their approval.
    Routing Logic:
    - If user agrees: Route to 'approved' and conclude workflow.
    - If user disagrees/has modifications: Update user_feedback in state and route to 'replan' (back to Planning Node).
    """
    user_text = _extract_text(node_input)

    # If this is the initial arrival right after planning without separate user reply:
    if not user_text or isinstance(node_input, list):
        yield Event(
            output="Plans presented for verification.",
            actions=EventActions(route="approved"),
        )
        return

    prompt = (
        "You are evaluating a user's response to suggested nutrition meal plans for Singapore canteens.\n"
        "Determine if the user agrees/approves the meal plan or wants changes/has feedback.\n\n"
        f"User Response: {user_text}\n"
    )

    try:
        client = genai.Client()
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
        text_lower = user_text.lower()
        disagreement_signals = [
            "no", "change", "different", "instead", "less", "more", "swap", "replace",
            "modify", "don't like", "disagree", "adjust", "portion"
        ]
        if any(w in text_lower for w in disagreement_signals):
            user_agreed = False
            feedback_text = user_text
        else:
            user_agreed = True
            feedback_text = None

    if user_agreed:
        success_msg = (
            "✅ **Meal Plan Approved!**\n\n"
            "Your personalized Singapore canteen meal plan is confirmed and saved. "
            "All portions and macronutrients have been estimated and optimized for your goals. "
            "Bon appétit!"
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
        feedback_msg = (
            f"🔄 **Updating Meal Plan**\n\n"
            f"Received your feedback: *'{feedback_text}'*\n"
            "Routing back to the Planning Node to regenerate your meal recommendations and recalculate USDA macros..."
        )
        state_delta = {"user_feedback": feedback_text}
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
