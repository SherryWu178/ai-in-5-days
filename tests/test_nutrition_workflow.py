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

"""Unit and Graph Topology Tests for Nutrition Specialist Agent."""

import pytest
from pydantic import ValidationError

from app.agent import nutrition_specialist_workflow, root_agent
from app.nodes.classifier import decline_node, intent_classifier_node
from app.nodes.planning import _generate_fallback_combinations, planning_node
from app.nodes.pre_clarification import (
    compute_target_macros_for_goal,
    pre_clarification_node,
)
from app.nodes.reverification import finish_recommendation_node, user_reverification_node
from app.state import (
    DishItem,
    MealCombination,
    NutritionState,
    TargetMacros,
    VALID_CANTEENS,
    VALID_NUTRITION_GOALS,
)
from app.subgraphs.food_recommendation import food_recommendation_subgraph
from app.tools.menu_tool import filter_menu_items, get_available_canteens, get_canteen_menu
from app.tools.usda_tool import (
    download_usda_dataset_info,
    estimate_dish_nutrition,
    query_usda_nutrition,
)


class MockContext:
    """Mock ADK Context for testing workflow nodes."""

    def __init__(self, state=None):
        self.state = state or {}


def test_state_schema_defaults_and_validation():
    """Verify NutritionState schema enforces fields and types."""
    state = NutritionState()
    assert state.canteen_preference is None
    assert state.nutrition_goal is None
    assert state.target_macros is None
    assert state.dietary_restrictions is None
    assert state.suggested_meal_plans is None
    assert state.user_feedback is None

    # Valid goal
    valid_state = NutritionState(
        canteen_preference="Shiok",
        nutrition_goal="High Protein for Muscle Gain",
        dietary_restrictions=["halal"],
    )
    assert valid_state.canteen_preference == "Shiok"
    assert valid_state.nutrition_goal == "High Protein for Muscle Gain"

    # Invalid goal should raise ValidationError
    with pytest.raises(ValidationError):
        NutritionState(nutrition_goal="Invalid Nonexistent Goal")


def test_usda_tool_queries_and_calculations():
    """Verify USDA FoodData Central query tool and macro calculations."""
    info = download_usda_dataset_info()
    assert info["status"] == "success"
    assert "https://fdc.nal.usda.gov/download-datasets.html" in info["url"]

    # Test single ingredient query per portion
    chicken_nutr = query_usda_nutrition("chicken_breast", portion_grams=150.0)
    assert chicken_nutr["calories_kcal"] > 0
    assert chicken_nutr["protein_g"] > 0
    assert chicken_nutr["portion_grams"] == 150.0

    # Test dish estimation
    dish_nutr = estimate_dish_nutrition(
        "Preserved Radish Steamed Minced Pork with Steamed Rice",
        "Pork, Rice, Chye Sim",
        portion_grams=200.0,
    )
    assert dish_nutr["portion_grams"] == 200.0
    assert dish_nutr["calories_kcal"] > 0
    assert dish_nutr["protein_g"] > 0


def test_menu_tool_facilities_and_filtering():
    """Verify Singapore canteen menu loader and dietary filtering."""
    canteens = get_available_canteens()
    assert "Shiok" in canteens
    assert "StrEAT" in canteens

    # Filter halal / no pork
    halal_items = filter_menu_items("Shiok", dietary_restrictions=["halal"])
    for item in halal_items:
        assert "pork" not in item["name"].lower()
        assert "pork" not in item["ingredients"].lower()

    # Filter vegan
    vegan_items = filter_menu_items("Shiok", dietary_restrictions=["vegan"])
    for item in vegan_items:
        tags_lower = [t.lower() for t in item["dietary_tags"]]
        assert "vegan" in tags_lower


def test_target_macros_translation_for_all_four_goals():
    """Verify translation of all 4 required nutrition goals into target macros."""
    # 1. Cut Down Body Fat
    fat_loss = compute_target_macros_for_goal("Cut Down Body Fat")
    assert fat_loss.max_calories_kcal <= 600.0
    assert fat_loss.min_protein_g >= 30.0

    # 2. High Protein for Muscle Gain
    muscle = compute_target_macros_for_goal("High Protein for Muscle Gain")
    assert muscle.min_protein_g >= 50.0

    # 3. Low GI
    low_gi = compute_target_macros_for_goal("Low GI")
    assert low_gi.min_fiber_g >= 10.0

    # 4. No Specific
    no_spec = compute_target_macros_for_goal("No Specific")
    assert no_spec.max_calories_kcal is not None


def test_planning_combinations_structure():
    """Verify Planning node generates max 2 combinations per canteen with gram portions."""
    combos_shiok = _generate_fallback_combinations("Shiok", "High Protein for Muscle Gain", [])
    assert len(combos_shiok) <= 2
    for combo in combos_shiok:
        assert combo.canteen_name == "Shiok"
        assert combo.total_portion_grams > 0
        assert len(combo.dishes) > 0
        for dish in combo.dishes:
            assert dish.portion_grams > 0
            assert dish.calories_kcal > 0

    combos_both = _generate_fallback_combinations("Both", "Low GI", [])
    assert len(combos_both) <= 4


@pytest.mark.asyncio
async def test_reverification_routing():
    """Verify User-Reverification node routing for agreement vs disagreement."""
    ctx = MockContext()

    # Case 1: Agreement
    events_agreed = [e async for e in user_reverification_node("Looks delicious! I approve combination 1.", ctx)]
    assert len(events_agreed) > 0
    last_event = events_agreed[-1]
    assert last_event.actions.route == "approved"

    # Case 2: Disagreement / Modifications
    events_replan = [e async for e in user_reverification_node("I want smaller portions and no pork please", ctx)]
    assert len(events_replan) > 0
    last_replan_event = events_replan[-1]
    assert last_replan_event.actions.route == "replan"
    assert "user_feedback" in last_replan_event.actions.state_delta


def test_graph_topology_validation():
    """Verify graph workflows are correctly constructed in ADK 2.0."""
    assert root_agent.name == "nutrition_specialist_workflow"
    assert food_recommendation_subgraph.name == "Food_Recommendation_SubGraph"
    assert len(nutrition_specialist_workflow.edges) >= 2
    assert len(food_recommendation_subgraph.edges) >= 4
