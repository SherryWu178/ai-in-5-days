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

"""Nutrition Specialist Graph Workflow Agent for Singapore Canteens using ADK 2.0."""

import logging

from google.adk.apps import App
from google.adk.workflow import START, Workflow

from .nodes.classifier import decline_node, intent_classifier_node
from .nodes.greeting import greeting_node
from .state import NutritionState
from .subgraphs.food_recommendation import food_recommendation_subgraph

logger = logging.getLogger(__name__)

# Main Root Graph Workflow (ADK 2.0)
nutrition_specialist_workflow = Workflow(
    name="nutrition_specialist_workflow",
    description=(
        "Expert Nutrition Specialist Graph Workflow Agent for Singapore corporate canteens. "
        "Starts with Turn 0 greeting & memory display, evaluates query intent, declines non-Singapore "
        "food queries, and executes the Food Recommendation SubGraph with USDA FoodData Central calculations."
    ),
    state_schema=NutritionState,
    edges=[
        (START, greeting_node),
        (greeting_node, intent_classifier_node),
        (
            intent_classifier_node,
            {
                "decline": decline_node,
                "food_recommendation": food_recommendation_subgraph,
            },
        ),
    ],
)

root_agent = nutrition_specialist_workflow

app = App(
    root_agent=root_agent,
    name="nutrition_specialist_app",
)
