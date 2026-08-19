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

"""Pydantic schemas for the Singapore Corporate Canteen Web Portal API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.state import MealCombination, NutritionGoalType, UserProfileMemory


class ConsultationRequest(BaseModel):
    """Payload for submitting a user query or verification confirmation turn."""

    user_id: str = Field(
        default="sherrywuyujin@google.com",
        description="Unique user identifier for multi-tenant isolation."
    )
    session_id: str = Field(
        default="default_session",
        description="Conversation session ID."
    )
    message: str = Field(
        description="The user's query text or response to a verification prompt."
    )


class ConsultationEventItem(BaseModel):
    """A single dialogue or state update event emitted during a turn."""

    event_type: str = Field(description="Type of event: 'message', 'meal_plans', 'request_input', 'memory_updated'")
    text: Optional[str] = Field(default=None, description="Human-readable assistant response text.")
    meal_plans: Optional[List[MealCombination]] = Field(default=None, description="Structured meal combinations generated.")
    request_input_message: Optional[str] = Field(default=None, description="Interactive confirmation prompt text if workflow paused.")
    target_macros: Optional[Dict[str, Any]] = Field(default=None, description="Calculated USDA macro budgets.")
    user_profile_memory: Optional[UserProfileMemory] = Field(default=None, description="Current stored profile memory.")


class ConsultationResponse(BaseModel):
    """Response payload containing turn events and session state summary."""

    user_id: str
    session_id: str
    events: List[ConsultationEventItem]
    waiting_for_confirmation: bool = Field(description="True if the agent paused for interactive human confirmation (RequestInput).")
    current_state: Dict[str, Any] = Field(description="Summary of current ADK state.")


class AdminMenuUploadRequest(BaseModel):
    """Payload for uploading or updating today's live canteen day-menu."""

    facilities: List[Dict[str, Any]] = Field(
        description="List of canteen facilities (Shiok, StrEAT) with stations and dishes."
    )
