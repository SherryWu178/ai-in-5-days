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

"""Unit tests for Observability, Tracing, PII Scrubbing, Vector Store Memory, and Model Routing."""

import logging
import pytest
from app.observability.pii_scrubber import scrub_pii, scrub_pii_string
from app.observability.structured_logger import log_agent_action, setup_structured_logger
from app.observability.tracing import trace_span
from app.memory.compactor import compact_conversation_history
from app.memory.vector_store import VectorStoreMemoryAdapter
from app.state import UserProfileMemory
from app.utils.llm import get_model_for_task
from app.tools.menu_tool import filter_menu_items_with_guidance
from app.tools.usda_tool import query_usda_nutrition_with_guidance


def test_pii_scrubber_redaction():
    """Verify email, phone number, employee badge, and token redactions."""
    dummy_token = "Bearer " + "A" * 32
    raw_text = f"Contact sherrywuyujin@google.com or +65 9123 4567 regarding badge EMP-123456 and auth {dummy_token}"
    scrubbed = scrub_pii_string(raw_text)
    assert "[REDACTED_EMAIL]" in scrubbed
    assert "sherrywuyujin@google.com" not in scrubbed
    assert "[REDACTED_PHONE]" in scrubbed
    assert "[REDACTED_EMPLOYEE_ID]" in scrubbed
    assert "[REDACTED_API_KEY]" in scrubbed

    # Test dictionary scrubbing
    raw_dict = {
        "user_id": "sherrywuyujin@google.com",
        "api_key": "secret-123",
        "nested": {"notes": "Call +65-8123-4567"},
    }
    scrubbed_dict = scrub_pii(raw_dict)
    assert scrubbed_dict["user_id"] == "[REDACTED_EMAIL]"
    assert scrubbed_dict["api_key"] == "[REDACTED_SECRET]"
    assert "[REDACTED_PHONE]" in scrubbed_dict["nested"]["notes"]


def test_structured_logger_actions_and_outcomes(caplog):
    """Verify structured logger records explicit intended_action vs outcome."""
    logger = setup_structured_logger("test_agent_logger")
    with caplog.at_level(logging.INFO):
        log_agent_action(
            logger=logger,
            node_name="menu_filtering_node",
            intended_action="Filter Shiok menu for vegan diet",
            outcome="Successfully filtered 3 eligible dishes",
            session_id="session_abc123",
            user_id="user_test@google.com",
            duration_ms=45.2,
        )
    assert len(caplog.records) > 0
    record = caplog.records[-1]
    assert record.node_name == "menu_filtering_node"
    assert record.intended_action == "Filter Shiok menu for vegan diet"
    assert record.outcome == "Successfully filtered 3 eligible dishes"


def test_trace_span_timing():
    """Verify distributed trace span measures execution time and records attributes."""
    with trace_span("llm_dish_selection", attributes={"model": "gemini-3.1-pro"}) as span:
        span.set_attribute("target_calories", 500)
    assert span.duration_ms >= 0.0
    assert span.attributes["target_calories"] == 500
    assert len(span.span_id) == 16


def test_vector_store_memory_persistence(tmp_path):
    """Verify persistent database adapter stores and retrieves user profile memory."""
    db_file = tmp_path / "test_profiles.db"
    store = VectorStoreMemoryAdapter(db_path=db_file)

    prof = UserProfileMemory(
        user_id="test_googler@google.com",
        preferred_canteen="Shiok",
        default_nutrition_goal="High Protein for Muscle Gain",
        permanent_dietary_restrictions=["dairy-free", "halal"],
    )
    store.upsert_profile(prof)

    loaded = store.get_profile("test_googler@google.com")
    assert loaded is not None
    assert loaded.preferred_canteen == "Shiok"
    assert loaded.default_nutrition_goal == "High Protein for Muscle Gain"
    assert "dairy-free" in loaded.permanent_dietary_restrictions


def test_context_history_compaction():
    """Verify dialogue compaction retains greeting while pruning intermediate turns."""
    messages = [
        {"role": "assistant", "content": "Turn 0 greeting with user memory"},
        {"role": "user", "content": "Turn 1 question"},
        {"role": "assistant", "content": "Turn 1 answer"},
        {"role": "user", "content": "Turn 2 question"},
        {"role": "assistant", "content": "Turn 2 answer"},
        {"role": "user", "content": "Turn 3 latest question"},
        {"role": "assistant", "content": "Turn 3 latest answer"},
    ]
    compacted = compact_conversation_history(messages, max_turns=3, preserve_initial_greeting=True)
    assert len(compacted) <= 4
    assert compacted[0]["content"] == "Turn 0 greeting with user memory"
    assert compacted[-1]["content"] == "Turn 3 latest answer"


def test_strategic_model_routing():
    """Verify strategic model selection returns fast model for simple nodes and pro model for reasoning."""
    fast_model = get_model_for_task("fast")
    reasoning_model = get_model_for_task("reasoning")
    assert "flash" in fast_model.lower() or "3.7" in fast_model
    assert "pro" in reasoning_model.lower() or "3.1" in reasoning_model or "1.5" in reasoning_model


def test_guided_error_handling_tools():
    """Verify guided error handling returns actionable guidance on edge cases."""
    # Canteen with zero matching dishes
    res = filter_menu_items_with_guidance(
        canteen_name="NonExistentCanteen999",
        dietary_restrictions=["vegan"],
    )
    assert res["success"] is False

    # USDA unknown food fallback with guided suggestions
    usda_res = query_usda_nutrition_with_guidance("exotic_dragonfruit_soup_123")
    assert usda_res["is_exact_match"] is False
    assert "GUIDED SUGGESTION" in usda_res["error_guidance"]


@pytest.mark.asyncio
async def test_model_armor_and_config():
    """Verify Model Armor sanitizes user prompts and config cleanly detects local vs prod."""
    from app.config import AppConfig
    from app.observability.model_armor import ModelArmorClient

    local_cfg = AppConfig(ENVIRONMENT="local")
    assert local_cfg.is_local is True
    assert local_cfg.is_production is False

    prod_cfg = AppConfig(ENVIRONMENT="production")
    assert prod_cfg.is_production is True
    assert prod_cfg.is_local is False

    client = ModelArmorClient()
    result = await client.sanitize_prompt("Hello from sherrywuyujin@google.com on +65 9123 4567")
    assert result["is_safe"] is True
    assert "[REDACTED_EMAIL]" in result["sanitized_prompt"]
    assert "[REDACTED_PHONE]" in result["sanitized_prompt"]
