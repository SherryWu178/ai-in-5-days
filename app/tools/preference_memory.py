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

"""Multi-tenant User Preference Memory store for the Singapore Corporate Canteen Agent."""

import json
from pathlib import Path
from typing import Dict, Optional

from ..state import UserProfileMemory

PROFILES_FILE_PATH = Path(__file__).resolve().parent.parent.parent / "user_profiles.json"

_MEMORY_STORE: Dict[str, UserProfileMemory] = {
    "sherrywuyujin@google.com": UserProfileMemory(
        user_id="sherrywuyujin@google.com",
        preferred_canteen="StrEAT",
        default_nutrition_goal="High Protein for Muscle Gain",
        permanent_dietary_restrictions=["fish"],
    ),
    "sherrywuyujin": UserProfileMemory(
        user_id="sherrywuyujin",
        preferred_canteen="StrEAT",
        default_nutrition_goal="High Protein for Muscle Gain",
        permanent_dietary_restrictions=["fish"],
    ),
    "alex.vegan@google.com": UserProfileMemory(
        user_id="alex.vegan@google.com",
        preferred_canteen="Shiok",
        default_nutrition_goal="Low GI",
        permanent_dietary_restrictions=["vegan"],
    ),
    "new.googler@google.com": UserProfileMemory(
        user_id="new.googler@google.com",
        preferred_canteen="Both",
        default_nutrition_goal="No Specific",
        permanent_dietary_restrictions=[],
    ),
}


def _load_profiles_from_disk() -> None:
    if PROFILES_FILE_PATH.exists():
        try:
            with open(PROFILES_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                for uid, prof_dict in data.items():
                    _MEMORY_STORE[uid] = UserProfileMemory.model_validate(prof_dict)
        except Exception:
            pass


def _save_profiles_to_disk() -> None:
    try:
        dump = {uid: prof.model_dump() for uid, prof in _MEMORY_STORE.items()}
        with open(PROFILES_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(dump, f, indent=2)
    except Exception as e:
        print(f"Warning: could not write user_profiles.json: {e}")


_load_profiles_from_disk()
_save_profiles_to_disk()


def get_user_profile_memory(user_id: str) -> Optional[UserProfileMemory]:
    _load_profiles_from_disk()
    return _MEMORY_STORE.get(user_id)


def save_user_profile_memory(memory: UserProfileMemory) -> None:
    _MEMORY_STORE[memory.user_id] = memory
    _save_profiles_to_disk()
