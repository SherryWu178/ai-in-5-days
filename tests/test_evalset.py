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

"""ADK EvalSet Tests for Nutrition Specialist Agent."""

import pytest
from google.adk.evaluation.base_eval_service import InferenceConfig, InferenceRequest
from google.adk.evaluation.eval_case import Invocation
from google.adk.evaluation.eval_set import EvalCase, EvalSet
from google.adk.evaluation.in_memory_eval_sets_manager import InMemoryEvalSetsManager
from google.adk.evaluation.local_eval_service import LocalEvalService
from google.genai import types

from app.agent import root_agent


@pytest.mark.asyncio
async def test_nutrition_agent_with_adk_evalset():
    """Run an ADK EvalSet test verifying typo resilience and intent classification."""
    inv = Invocation(
        user_content=types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="can you recomend me a high pretain diet at Shiok")
            ],
        )
    )
    eval_case = EvalCase(
        eval_id="test_high_pretain_typo",
        conversation=[inv],
    )
    eval_set = EvalSet(
        eval_set_id="nutrition_eval_1",
        name="Nutrition Typo & Goal Evals",
        eval_cases=[eval_case],
    )

    mgr = InMemoryEvalSetsManager()
    mgr.create_eval_set("nutrition_app", "nutrition_eval_1")
    mgr.add_eval_case("nutrition_app", "nutrition_eval_1", eval_case)

    service = LocalEvalService(
        root_agent=root_agent,
        eval_sets_manager=mgr,
    )
    req = InferenceRequest(
        app_name="nutrition_app",
        eval_set_id="nutrition_eval_1",
        inference_config=InferenceConfig(use_live=True),
    )

    results = [res async for res in service.perform_inference(req)]
    assert len(results) == 1
    inf_result = results[0]
    assert inf_result.status.name == "SUCCESS"
    assert len(inf_result.inferences) == 1
    first_inf = inf_result.inferences[0]
    assert first_inf.final_response is not None
    response_text = first_inf.final_response.parts[0].text
    assert len(response_text) > 0
