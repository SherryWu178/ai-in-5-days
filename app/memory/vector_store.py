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

"""Persistent Vector Store & Cloud SQL / SQLite Adapter for Long-Term Profile Memory."""

import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from app.config import config
from app.state import UserProfileMemory

logger = logging.getLogger(__name__)

LOCAL_SQLITE_PATH = Path(__file__).resolve().parent.parent.parent / "user_profiles.db"


class VectorStoreMemoryAdapter:
    """Enterprise persistent memory adapter supporting Google Cloud SQL (Postgres / pgvector) with local SQLite fallback."""

    def __init__(self, db_path: Path = LOCAL_SQLITE_PATH):
        self.db_path = db_path
        self.database_url = os.getenv("DATABASE_URL") or config.DATABASE_URL
        self._is_postgres = self.database_url.startswith("postgres")
        self._init_db()

    def _init_db(self) -> None:
        """Initializes database schema in PostgreSQL or SQLite."""
        if self._is_postgres:
            try:
                import psycopg2
                with psycopg2.connect(self.database_url) as conn:
                    with conn.cursor() as cur:
                        # Enable pgvector extension if available
                        try:
                            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                        except Exception:
                            conn.rollback()
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS user_profiles (
                                user_id VARCHAR(255) PRIMARY KEY,
                                preferred_canteen VARCHAR(100),
                                default_nutrition_goal VARCHAR(100),
                                permanent_dietary_restrictions TEXT,
                                embedding_vector TEXT,
                                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            );
                        """)
                    conn.commit()
                logger.info("Connected to Google Cloud SQL PostgreSQL database.")
                return
            except Exception as e:
                logger.warning("Cloud SQL Postgres connection failed (%s); falling back to local SQLite.", e)
                self._is_postgres = False

        # SQLite Schema Initialization (Local Dev & Fallback)
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
            logger.warning("Failed to initialize SQLite schema: %s", e)

    def get_profile(self, user_id: str) -> Optional[UserProfileMemory]:
        """Queries user profile from Google Cloud SQL or SQLite."""
        if self._is_postgres:
            try:
                import psycopg2
                with psycopg2.connect(self.database_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT preferred_canteen, default_nutrition_goal, permanent_dietary_restrictions FROM user_profiles WHERE user_id = %s",
                            (user_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            canteen, goal, restr_str = row
                            restr_list = json.loads(restr_str) if restr_str else []
                            return UserProfileMemory(
                                user_id=user_id,
                                preferred_canteen=canteen,
                                default_nutrition_goal=goal,
                                permanent_dietary_restrictions=restr_list,
                            )
            except Exception as e:
                logger.warning("Cloud SQL query failed for %s: %s", user_id, e)

        # SQLite Query Fallback
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
        """Upserts user profile to Google Cloud SQL or SQLite."""
        restr_str = json.dumps(memory.permanent_dietary_restrictions or [])

        if self._is_postgres:
            try:
                import psycopg2
                with psycopg2.connect(self.database_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO user_profiles (user_id, preferred_canteen, default_nutrition_goal, permanent_dietary_restrictions)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT(user_id) DO UPDATE SET
                                preferred_canteen = EXCLUDED.preferred_canteen,
                                default_nutrition_goal = EXCLUDED.default_nutrition_goal,
                                permanent_dietary_restrictions = EXCLUDED.permanent_dietary_restrictions,
                                updated_at = CURRENT_TIMESTAMP;
                            """,
                            (
                                memory.user_id,
                                memory.preferred_canteen,
                                memory.default_nutrition_goal,
                                restr_str,
                            ),
                        )
                    conn.commit()
                return
            except Exception as e:
                logger.warning("Cloud SQL upsert failed for %s: %s", memory.user_id, e)

        # SQLite Upsert Fallback
        try:
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
            logger.warning("Error upserting profile to SQLite: %s", e)


vector_memory_store = VectorStoreMemoryAdapter()
