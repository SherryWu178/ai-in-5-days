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

"""Intent Classifier Node and Decline Node for the Nutrition Specialist agent."""

from collections.abc import AsyncGenerator
import logging
from typing import Any

from google import genai
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MODEL = "gemini-3.7-flash"


class IntentClassification(BaseModel):
    """Schema for classifying incoming user queries."""

    is_singapore_food_recommendation: bool = Field(
        description=(
            "True if the user's query relates to food recommendations, nutrition, "
            "meal planning, diet goals, macros, or menus for corporate canteens in Singapore "
            "(Shiok, StrEAT, Singapore food choices, hawker/canteen nutrition). "
            "False if the query is unrelated (e.g. software coding, general non-food chit-chat, "
            "weather, financial advice, math, international travel non-food topics)."
        )
    )
    detected_intent: str = Field(
        default="",
        description="Brief summary of the detected intent.",
    )


def extract_text_from_node_input(node_input: Any) -> str:
    """Safely extracts plain string from various input types."""
    if isinstance(node_input, str):
        return node_input.strip()
    if hasattr(node_input, "parts"):
        parts = [
            part.text for part in node_input.parts if getattr(part, "text", None)
        ]
        return " ".join(parts).strip()
    if isinstance(node_input, dict):
        if "text" in node_input:
            return str(node_input["text"]).strip()
        if "content" in node_input:
            return str(node_input["content"]).strip()
        return str(node_input).strip()
    return str(node_input).strip()


async def intent_classifier_node(node_input: Any, ctx: Context) -> Event:
    """Evaluates whether the user's query is related to food recommendations in Singapore.

    Routes to:
    - 'food_recommendation': if related to Singapore food / canteen nutrition planning.
    - 'decline': if unrelated to Singapore food recommendations.
    """
    user_query = extract_text_from_node_input(node_input)

    # Empty prompt check
    if not user_query:
        return Event(
            output="",
            actions=EventActions(route="decline"),
        )

    # If the user already has an active meal plan consultation in progress
    if ctx.state.get("suggested_meal_plans") or ctx.state.get("canteen_preference"):
        return Event(
            output=user_query,
            actions=EventActions(route="food_recommendation"),
        )

    # Route greetings and confirmation/feedback signals directly to food_recommendation
    query_lower = user_query.lower()
    if query_lower in ["hi", "hello", "hey", "start", "greeting", "hi!", "hello!", "hey!"] or any(
        w in query_lower for w in ["looks good", "approve", "confirm", "yes", "ok", "okay", "sure", "great", "fine", "swap", "remove", "prefer"]
    ):
        return Event(
            output=user_query,
            actions=EventActions(route="food_recommendation"),
        )

    prompt = (
        "You are an Intent Classifier for an expert Nutrition Specialist AI dedicated to "
        "corporate canteen food recommendations in Singapore (e.g. Shiok and StrEAT canteens).\n\n"
        "Analyze the user's message and determine if it is related to food recommendations, "
        "diet, nutrition goals, calories/macros, canteen dishes, or eating in Singapore.\n\n"
        f"User Message: {user_query}"
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
                    response_schema=IntentClassification,
                    temperature=0.0,
                ),
            )
            classification = IntentClassification.model_validate_json(response.text)
            is_related = classification.is_singapore_food_recommendation
        except Exception as e:
            logger.warning("LLM intent classification failed (%s), using keyword fallback.", e)
            client = None
    if not client:
        # Fallback keywords
        query_lower = user_query.lower()
        food_keywords = [
            "food", "eat", "meal", "diet", "nutrition", "calorie", "macro", "protein",
            "pretain", "protain", "prtain", "protin", "canteen", "shiok", "streat",
            "lunch", "dinner", "breakfast", "dish", "menu", "low gi", "glycemic", "diabetes",
            "fat", "cut", "weight", "loss", "muscle", "bulk", "gain", "gains", "hypertrophy",
            "halal", "vegan", "vegetarian", "singapore", "healthy"
        ]
        is_related = any(k in query_lower for k in food_keywords)

    if is_related:
        return Event(
            output=user_query,
            actions=EventActions(route="food_recommendation"),
        )
    else:
        return Event(
            output=user_query,
            actions=EventActions(route="decline"),
        )


def decline_node(node_input: Any) -> AsyncGenerator[Event, None]:
    """Politely declines inquiries unrelated to food recommendations in Singapore and terminates."""
    message = (
        "Hello! I am your Nutrition Specialist dedicated exclusively to food recommendations, "
        "dietary planning, and macro tracking for corporate canteens in Singapore (Shiok & StrEAT).\n\n"
        "I cannot assist with general inquiries outside of food and nutrition planning in Singapore. "
        "Please let me know if you would like meal recommendations based on your nutritional goals!"
    )

    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=message)],
        ),
        output=message,
    )
