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

"""Persistent Vector Store / SQL Adapter for Long-Term Multi-Tenant Profile Memory."""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from app.state import UserProfileMemory

logger = logging.getLogger(__name__)

VECTOR_DB_PATH = Path(__file__).resolve().parent.parent.parent / "user_profiles.db"


class VectorStoreMemoryAdapter:
    """Persistent database & vector memory store for Singapore Corporate Canteen users."""

    def __init__(self, db_path: Path = VECTOR_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initializes persistent SQL / Vector table schemas."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        user_id TEXT PRIMARY KEY,
                        preferred_canteen TEXT,
                        default_nutrition_goal TEXT,
                        permanent_dietary_restrictions TEXT,
                        embedding_vector TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning("Failed to initialize VectorStoreMemoryAdapter DB: %s", e)

    def get_profile(self, user_id: str) -> Optional[UserProfileMemory]:
        """Queries persistent database for a Googler's multi-tenant memory."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT preferred_canteen, default_nutrition_goal, permanent_dietary_restrictions FROM user_profiles WHERE user_id = ?",
                    (user_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                canteen, goal, restr_str = row
                restr_list = json.loads(restr_str) if restr_str else []
                return UserProfileMemory(
                    user_id=user_id,
                    preferred_canteen=canteen,
                    default_nutrition_goal=goal,
                    permanent_dietary_restrictions=restr_list,
                )
        except Exception as e:
            logger.warning("Error querying VectorStoreMemoryAdapter for %s: %s", user_id, e)
            return None

    def upsert_profile(self, memory: UserProfileMemory) -> None:
        """Upserts a user's persistent profile into database storage."""
        try:
            restr_str = json.dumps(memory.permanent_dietary_restrictions or [])
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO user_profiles (user_id, preferred_canteen, default_nutrition_goal, permanent_dietary_restrictions)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        preferred_canteen = excluded.preferred_canteen,
                        default_nutrition_goal = excluded.default_nutrition_goal,
                        permanent_dietary_restrictions = excluded.permanent_dietary_restrictions,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        memory.user_id,
                        memory.preferred_canteen,
                        memory.default_nutrition_goal,
                        restr_str,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.warning("Error upserting profile to VectorStoreMemoryAdapter: %s", e)


vector_memory_store = VectorStoreMemoryAdapter()
