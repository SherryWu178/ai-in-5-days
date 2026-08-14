# Nutrition Specialist Graph Workflow Agent (ADK 2.0)

A graph-based AI agent workflow developed with **Google ADK 2.0** for a corporate **Nutrition Specialist** in Singapore. The agent gathers user nutritional goals, queries the USDA FoodData Central database to compute precise caloric and macronutrient breakdowns, provides targeted dish recommendations across Singapore corporate canteens (**Shiok** and **StrEAT**), and iterates through human feedback via graph replanning loops.

---

## 🏗️ Graph Architecture & Workflow Topology

```mermaid
flowchart TD
    START([START]) --> Classifier[Intent Classifier Node]
    
    Classifier -- "route: decline (Unrelated)" --> Decline[Decline_Node\nPolitely Declines & Terminates]
    Classifier -- "route: food_recommendation (Related)" --> SubGraph[[Food_Recommendation_SubGraph]]
    
    subgraph SubGraph_Workflow [Food Recommendation SubGraph]
        SG_START([START]) --> PreClarification[1. Pre-Clarification Node\n- Validate intake\n- Translate goals to TargetMacros]
        PreClarification --> Planning[2. Planning Node\n- USDA FoodData Central query\n- Gram-level portions\n- Max 2 combos per canteen]
        Planning --> Reverification[3. User-Reverification Node\n- Present meal plans\n- Evaluate agreement/feedback]
        
        Reverification -- "route: replan (Disagreed / Modifications)" --> Planning
        Reverification -- "route: approved (Agreed)" --> Finish[Workflow Complete]
    end
```

---

## 📊 State Schema

The workflow state is defined in [`app/state.py`](file:///home/admin_sherrywuyujin_altostrat_co/ai-in-5-days/food-recomendation-agent/app/state.py) using Pydantic:

| State Variable | Type | Description |
| :--- | :--- | :--- |
| `canteen_preference` | `Optional[str]` | Preferred canteen: `'Shiok'` (Floor 7), `'StrEAT'` (Floor 30), or `'Both'`. |
| `nutrition_goal` | `Optional[NutritionGoalType]` | Must map to one of: `['No Specific', 'Low GI', 'Cut Down Body Fat', 'High Protein for Muscle Gain']`. |
| `target_macros` | `Optional[TargetMacros]` | Internal translation into max calories, min protein, carbs, fat, fiber. |
| `dietary_restrictions`| `Optional[List[str]]` | Dietary constraints (e.g. halal, no-pork, vegan, celiac/gluten-free). |
| `suggested_meal_plans`| `Optional[List[MealCombination]]` | Output from planning node (max 2 combinations per canteen with portion in grams). |
| `user_feedback` | `Optional[str]` | Any disagreement or modifications requested during reverification. |

---

## 🧩 Nodes & SubGraphs

### 1. Intent Classifier Node (`app/nodes/classifier.py`)
- Evaluates user query intent.
- If unrelated to food recommendations in Singapore: Routes to `Decline_Node`.
- If related: Routes to `Food_Recommendation_SubGraph`.

### 2. Decline Node (`app/nodes/classifier.py`)
- Politely explains that the specialist is exclusively dedicated to Singapore corporate canteen food and nutrition planning, then terminates the flow.

### 3. Pre-Clarification Node (`app/nodes/pre_clarification.py`)
- Gathers missing intake parameters (`canteen_preference`, `nutrition_goal`, `dietary_restrictions`).
- Translates `nutrition_goal` into precise target macros:
  - **Cut Down Body Fat:** $\le 550$ kcal, $\ge 35$g protein, $\le 45$g carbs, $\le 15$g fat.
  - **High Protein for Muscle Gain:** $\le 850$ kcal, $\ge 50$g protein, $\le 80$g carbs.
  - **Low GI:** $\le 600$ kcal, $\ge 30$g protein, $\ge 12$g fiber (low glycemic index whole grains/greens).
  - **No Specific:** Balanced HPB healthy plate standard ($\approx 650$ kcal, $\ge 25$g protein).

### 4. Planning Node (`app/nodes/planning.py`)
- Interfaces with the **USDA FoodData Central** tool ([`app/tools/usda_tool.py`](file:///home/admin_sherrywuyujin_altostrat_co/ai-in-5-days/food-recomendation-agent/app/tools/usda_tool.py)) referencing `https://fdc.nal.usda.gov/download-datasets.html`.
- Computes caloric and macronutrient values for each ingredient and dish based on exact weight in grams.
- Suggests at most 2 combinations per canteen with dish names and precise portion sizes (e.g., *Preserved Radish Steamed Minced Pork - 200g*, *Wok-fried Chye Sim - 120g*).
- Stores structured meal combinations in `suggested_meal_plans`.

### 5. User-Reverification Node (`app/nodes/reverification.py`)
- Presents the suggested meal plans to the user.
- **Routing Logic:**
  - **If the user agrees:** Concludes the workflow with route `'approved'`.
  - **If the user disagrees / has modifications:** Updates `user_feedback` in the state and routes to `'replan'`, directing execution back to the **Planning Node** to adjust portion sizes or dishes.

---

## 🧪 Testing

Run the automated test suite with `pytest`:

```bash
uv run pytest
```
