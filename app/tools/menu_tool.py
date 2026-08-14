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

"""Singapore Corporate Canteen Menu Tool.

Parses and provides menu items for Singapore canteens ('Shiok' and 'StrEAT'),
with dietary filtering (Vegan, Vegetarian, Halal-friendly, allergen screening).
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

MENU_FILE_PATH = Path(__file__).resolve().parent.parent.parent / "menu.json"


def load_raw_menu() -> Dict[str, Any]:
    """Loads the raw menu JSON data from the file system."""
    if not MENU_FILE_PATH.exists():
        # Fallback to local search if executed in different relative root
        alt_path = Path("menu.json")
        if alt_path.exists():
            with open(alt_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"facilities": []}

    with open(MENU_FILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_available_canteens() -> List[str]:
    """Returns the names of all available corporate canteens in Singapore."""
    data = load_raw_menu()
    return [fac.get("canteen_name", "") for fac in data.get("facilities", []) if fac.get("canteen_name")]


def get_canteen_menu(canteen_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves all stations and menu items for a specific canteen or all canteens.

    Args:
        canteen_name: Optional filter for 'Shiok' (Floor 7) or 'StrEAT' (Floor 30).

    Returns:
        List of canteen facilities with their stations and dishes.
    """
    data = load_raw_menu()
    facilities = data.get("facilities", [])
    if not canteen_name or canteen_name.lower() in ["both", "all", "any"]:
        return facilities

    target_name = canteen_name.strip().lower()
    return [
        fac for fac in facilities
        if fac.get("canteen_name", "").strip().lower() == target_name
    ]


def filter_menu_items(
    canteen_name: Optional[str] = None,
    dietary_restrictions: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Filters dishes across stations to exclude specified allergens or restrictions.

    Args:
        canteen_name: Optional canteen name filter ('Shiok' or 'StrEAT').
        dietary_restrictions: Restrictions e.g. ['halal', 'no-pork', 'vegan', 'vegetarian', 'dairy-free', 'gluten-free'].

    Returns:
        Flattened list of eligible dishes with station and canteen info.
    """
    facilities = get_canteen_menu(canteen_name)
    eligible_items = []
    restrictions_lower = [r.lower() for r in (dietary_restrictions or [])]

    for fac in facilities:
        c_name = fac.get("canteen_name", "Unknown Canteen")
        for station in fac.get("stations", []):
            s_name = station.get("station_name", "General Station")
            for item in station.get("items", []):
                dish_name = item.get("name", "")
                allergens = item.get("allergens", "").lower()
                ingredients = item.get("ingredients", "").lower()
                dietary_tags = [t.lower() for t in item.get("dietary_tags", [])]

                # Check restrictions
                violates = False
                for r in restrictions_lower:
                    if "halal" in r or "no pork" in r or "no-pork" in r:
                        if "pork" in ingredients or "[pork]" in ingredients or "pork" in dish_name.lower():
                            violates = True
                            break
                        if "[alcohol]" in ingredients or "alcohol" in ingredients:
                            violates = True
                            break
                    if "vegan" in r and "vegan" not in dietary_tags:
                        violates = True
                        break
                    if "vegetarian" in r and not any(t in ["vegan", "vegetarian"] for t in dietary_tags):
                        violates = True
                        break
                    if "dairy" in r or "milk" in r or "lactose" in r:
                        if "milk" in allergens or "cheese" in ingredients or "butter" in ingredients or "milk" in ingredients:
                            violates = True
                            break
                    if "gluten" in r or "celiac" in r:
                        if "gluten" in allergens or "wheat" in ingredients or "spaghetti" in ingredients:
                            violates = True
                            break
                    if "seafood" in r or "shellfish" in r or "fish" in r or "crustacean" in r:
                        if "fish" in allergens or "crustaceans" in allergens or "fish" in ingredients or "octopus" in ingredients or "clam" in ingredients:
                            violates = True
                            break

                if not violates:
                    eligible_items.append({
                        "canteen_name": c_name,
                        "station_name": s_name,
                        "name": dish_name,
                        "dietary_tags": item.get("dietary_tags", []),
                        "allergens": item.get("allergens", "No declared allergens"),
                        "ingredients": item.get("ingredients", ""),
                    })

    return eligible_items
