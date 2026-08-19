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
    """Verify User-Reverification node Phase 1 confirmation pause, agreement route, and ingredient protest replanning."""
    ctx = MockContext(state={})

    from app.nodes.planning import macro_sizing_and_verification_node

    # 1. Verify Stage 3 planning emits RequestInput at the end
    stage3_evs = [e async for e in macro_sizing_and_verification_node(None, ctx)]
    assert type(stage3_evs[-1]).__name__ == "RequestInput"

    # 2. Case 1: Agreement -> route='approved'

    # Phase 2 Case 1: Agreement
    events_agreed = [e async for e in user_reverification_node("Looks delicious! I approve combination 1.", ctx)]
    assert len(events_agreed) > 0
    assert events_agreed[-1].actions.route == "approved"

    # Phase 2 Case 2: Ingredient Protest / Modifications ("remove fish")
    ctx2 = MockContext(state={"plan_presented_for_verification": True, "dietary_restrictions": []})
    events_replan = [e async for e in user_reverification_node("I don't want fish, remove fish please", ctx2)]
    assert len(events_replan) > 0
    last_replan = events_replan[-1]
    assert last_replan.actions.route == "replan"
    assert "user_feedback" in last_replan.actions.state_delta
    # Verify fish was extracted to dietary_restrictions so menu_filtering_node removes it
    assert "fish" in last_replan.actions.state_delta["dietary_restrictions"]
    # Verify entertaining customer-facing replanning message
    assert "Heard loud and clear!" in last_replan.content.parts[0].text
    assert "Excluding protested item(s): fish" in last_replan.content.parts[0].text

    


def test_graph_topology_validation():
    """Verify graph workflows are correctly constructed in ADK 2.0."""
    assert root_agent.name == "nutrition_specialist_workflow"
    assert food_recommendation_subgraph.name == "Food_Recommendation_SubGraph"
    assert len(nutrition_specialist_workflow.edges) >= 2
    assert len(food_recommendation_subgraph.edges) >= 4


@pytest.mark.asyncio
async def test_pre_clarification_node_typo_resilience():
    """Verify pre_clarification_node accurately extracts goals even with typos like 'pretain'."""
    # Test high protein typo from interactive session
    ctx1 = MockContext()
    events1 = [e async for e in pre_clarification_node("can you recomend me a high pretain diet", ctx1)]
    last_event1 = events1[-1]
    assert last_event1.output["nutrition_goal"] == "High Protein for Muscle Gain"
    assert last_event1.output["target_macros"]["min_protein_g"] >= 50.0

    # Test fat loss goal
    ctx2 = MockContext()
    events2 = [e async for e in pre_clarification_node("want to cut down fat and lose weight at Shiok", ctx2)]
    last_event2 = events2[-1]
    assert last_event2.output["nutrition_goal"] == "Cut Down Body Fat"
    assert last_event2.output["canteen_preference"] == "Shiok"


def test_deterministic_macro_verification_and_scaling():
    """Verify hybrid candidate dish scaling keeps total calories under ceiling and hits protein targets."""
    from app.nodes.planning import (
        CandidateCombination,
        CandidateDish,
        _verify_and_scale_candidate_combination,
    )

    menu_by_name = {
        "Steamed Firm Tofu with Olive Vegetable": {
            "name": "Steamed Firm Tofu with Olive Vegetable",
            "station": "Steamed Station",
            "ingredients": "Tau Kwa, Olive Vegetable, Garlic",
            "dietary_tags": ["Vegan"],
        }
    }

    cand = CandidateCombination(
        canteen_name="Shiok",
        combination_title="Candidate Protein Combo",
        dishes=[
            CandidateDish(
                name="Steamed Firm Tofu with Olive Vegetable",
                portion_grams=500.0,  # Deliberately huge to test calorie ceiling scaling
            )
        ],
        nutritional_rationale="Test candidate",
    )

    # When target calories ceiling is 300 kcal
    target_macros = {"max_calories_kcal": 300.0}
    scaled = _verify_and_scale_candidate_combination(1, cand, menu_by_name, target_macros)
    assert scaled is not None
    assert scaled.total_calories_kcal <= 300.0
    assert scaled.dishes[0].portion_grams < 500.0


@pytest.mark.asyncio
async def test_sequential_planning_pipeline_nodes():
    """Verify the 3 modular ADK planning nodes execute sequentially and update state accurately."""
    from app.nodes.planning import (
        llm_dish_selection_node,
        macro_sizing_and_verification_node,
        menu_filtering_node,
    )

    ctx = MockContext(
        state={
            "canteen_preference": "Shiok",
            "nutrition_goal": "High Protein for Muscle Gain",
            "dietary_restrictions": ["vegan"],
        }
    )

    # 1. Stage 1: menu_filtering_node
    ev1 = [e async for e in menu_filtering_node(None, ctx)][0]
    filtered = ev1.actions.state_delta["filtered_menu_items"]
    assert "Shiok" in filtered
    assert len(filtered["Shiok"]) > 0
    # Update mock context state for next stage
    ctx.state.update(ev1.actions.state_delta)

    # 2. Stage 2: llm_dish_selection_node
    ev2 = [e async for e in llm_dish_selection_node(None, ctx)][0]
    assert "llm_candidate_plans" in ev2.actions.state_delta
    ctx.state.update(ev2.actions.state_delta)

    # 3. Stage 3: macro_sizing_and_verification_node
    ev3_list = [e async for e in macro_sizing_and_verification_node(None, ctx)]
    ev3 = ev3_list[0]
    assert "suggested_meal_plans" in ev3.actions.state_delta
    plans = ev3.actions.state_delta["suggested_meal_plans"]
    assert len(plans) > 0
    assert "Shiok" in plans[0]["canteen_name"]

@pytest.mark.asyncio
async def test_classifier_greeting_routes_to_food_recommendation():
    """Verify saying 'hi' or 'start' routes directly to food_recommendation (greeting_node)."""
    from app.nodes.classifier import intent_classifier_node

    ev = await intent_classifier_node("hi", MockContext())
    assert ev.actions.route == "food_recommendation"

    ev_confirm = await intent_classifier_node(
        "looks good to me",
        MockContext(state={"suggested_meal_plans": [{"id": 1}]}),
    )
    assert ev_confirm.actions.route == "food_recommendation"
