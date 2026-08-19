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

"""FastAPI Web Server & Admin Portal for the Singapore Corporate Canteen Nutrition Agent."""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from google.adk.events.request_input import RequestInput
from google.adk.sessions.state import State
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from app.agent import app as adk_app, nutrition_specialist_workflow
from app.state import MealCombination, NutritionState, UserProfileMemory
from app.tools.menu_tool import get_canteen_menu, load_raw_menu, save_live_menu
from app.tools.preference_memory import get_user_profile_memory, save_user_profile_memory
from app.utils.llm import load_env_file

load_env_file()

from web.schemas import (
    AdminMenuUploadRequest,
    ConsultationEventItem,
    ConsultationRequest,
    ConsultationResponse,
)

app = FastAPI(
    title="Singapore Corporate Canteen Nutrition Specialist API",
    description="ADK 2.0 Web Portal API & Admin Canteen Menu Manager for Shiok (Floor 7) & StrEAT (Floor 30).",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

adk_runner = Runner(
    app=adk_app,
    session_service=InMemorySessionService(),
    auto_create_session=True,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _get_state_dict(session: Any) -> dict[str, Any]:
    if not session or not session.state:
        return {}
    if isinstance(session.state, dict):
        return session.state
    return getattr(session.state, "data", {})


@app.post("/api/consultation", response_model=ConsultationResponse)
async def consult_agent(req: ConsultationRequest) -> ConsultationResponse:
    """Executes a dialogue or interactive confirmation turn with the Singapore Canteen Agent."""
    events: List[ConsultationEventItem] = []
    waiting_for_confirmation = False

    prof = get_user_profile_memory(req.user_id)
    state_delta: dict[str, Any] = {"user_id": req.user_id}
    if prof:
        state_delta["user_profile_memory"] = prof.model_dump()

    new_msg = types.Content(
        role="user",
        parts=[types.Part.from_text(text=req.message)],
    )

    current_state = {}
    try:
        async for event in adk_runner.run_async(
            user_id=req.user_id,
            session_id=req.session_id,
            new_message=new_msg,
            state_delta=state_delta,
        ):
            if isinstance(event, RequestInput) or getattr(event, "long_running_tool_ids", None) or hasattr(event, "interrupt_id"):
                waiting_for_confirmation = True
                part_msg = None
                if event.content and event.content.parts:
                    for p in event.content.parts:
                        if getattr(p, "text", None):
                            part_msg = p.text
                events.append(
                    ConsultationEventItem(
                        event_type="request_input",
                        request_input_message=part_msg or "Please confirm your meal plan:",
                    )
                )
                continue

            if event.content and event.content.parts:
                text_parts = [p.text for p in event.content.parts if getattr(p, "text", None)]
                if text_parts:
                    combined_text = "\n\n".join(text_parts)
                    session = await adk_runner._get_or_create_session(user_id=req.user_id, session_id=req.session_id)
                    current_state = _get_state_dict(session)
                    meal_plans_raw = current_state.get("suggested_meal_plans") or []
                    events.append(
                        ConsultationEventItem(
                            event_type="message",
                            text=combined_text,
                            meal_plans=[MealCombination.model_validate(p) for p in meal_plans_raw] if meal_plans_raw else [],
                            target_macros=current_state.get("target_macros"),
                            user_profile_memory=get_user_profile_memory(req.user_id),
                        )
                    )
    except Exception as e:
        events.append(
            ConsultationEventItem(
                event_type="message",
                text=f"⚠️ **Consultation Error:** {str(e)}",
            )
        )

    session = await adk_runner._get_or_create_session(user_id=req.user_id, session_id=req.session_id)
    current_state = _get_state_dict(session)

    return ConsultationResponse(
        user_id=req.user_id,
        session_id=req.session_id,
        events=events,
        waiting_for_confirmation=waiting_for_confirmation,
        current_state=current_state,
    )


@app.get("/api/user/profile")
async def get_user_profile(user_id: str = "sherrywuyujin@google.com") -> Dict[str, Any]:
    """Retrieves long-term user preference memory for a specific Googler."""
    prof = get_user_profile_memory(user_id)
    if not prof:
        return {"user_id": user_id, "profile": None}
    return {"user_id": user_id, "profile": prof.model_dump()}


@app.post("/api/user/profile")
async def update_user_profile(prof: UserProfileMemory) -> Dict[str, Any]:
    """Updates or preloads long-term user preference memory."""
    save_user_profile_memory(prof)
    return {"status": "success", "profile": prof.model_dump()}


@app.get("/api/admin/menu")
async def get_live_menu(canteen_name: Optional[str] = None) -> Dict[str, Any]:
    """Admin endpoint: fetches today's live day-menu data."""
    raw = load_raw_menu()
    facilities = get_canteen_menu(canteen_name)
    return {
        "raw_menu": raw,
        "facilities": facilities,
    }


@app.post("/api/admin/menu")
async def update_live_menu(upload: AdminMenuUploadRequest) -> Dict[str, Any]:
    """Admin endpoint: validates and saves uploaded today_menu.json data."""
    try:
        save_live_menu({"facilities": upload.facilities})
        return {
            "status": "success",
            "message": f"Updated live canteen menu with {len(upload.facilities)} facilities.",
            "facilities_count": len(upload.facilities),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Menu upload validation error: {str(e)}")


@app.get("/api/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint for GCP Cloud Run / GKE deployment target."""
    return {"status": "healthy", "service": "singapore_canteen_nutrition_agent"}


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
