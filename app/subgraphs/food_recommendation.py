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

"""Food Recommendation SubGraph for the Nutrition Specialist Agent."""

from google.adk.workflow import START, Workflow

from ..nodes.planning import (
    llm_dish_selection_node,
    macro_sizing_and_verification_node,
    menu_filtering_node,
    planning_node,
)
from ..nodes.pre_clarification import pre_clarification_node
from ..nodes.reverification import finish_recommendation_node, user_reverification_node
from ..state import NutritionState

# Definition of Food_Recommendation_SubGraph (ADK 2.0)
food_recommendation_subgraph = Workflow(
    name="Food_Recommendation_SubGraph",
    description=(
        "SubGraph for Singapore canteen food recommendations: gathers missing intake info, "
        "calculates macro targets, filters menu items, uses LLM for culinary dish selection, "
        "sizes portions deterministically with USDA FoodData Central calculations, "
        "and handles user reverification and replanning loops."
    ),
    state_schema=NutritionState,
    edges=[
        (START, pre_clarification_node),
        (
            pre_clarification_node,
            {
                "plan": menu_filtering_node,
                "verify": user_reverification_node,
            },
        ),
        (menu_filtering_node, llm_dish_selection_node),
        (llm_dish_selection_node, macro_sizing_and_verification_node),
        (macro_sizing_and_verification_node, user_reverification_node),
        (
            user_reverification_node,
            {
                "replan": pre_clarification_node,
                "approved": finish_recommendation_node,
            },
        ),
    ],
)
