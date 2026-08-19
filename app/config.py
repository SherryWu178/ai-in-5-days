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

"""Application configuration differentiating Local Development vs Production GCP."""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Centralized configuration for Singapore Canteen Specialist Agent."""

    # Environment
    ENVIRONMENT: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "local"))
    
    # GCP & Project Settings
    GOOGLE_CLOUD_PROJECT: Optional[str] = Field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT"))
    GOOGLE_CLOUD_REGION: str = Field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_REGION", "asia-southeast1"))
    
    # Telemetry & Observability
    ENABLE_AGENT_ENGINE_TELEMETRY: bool = Field(
        default_factory=lambda: os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "false").lower() in ("true", "1")
    )
    ENABLE_MODEL_ARMOR_SAFETY: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_MODEL_ARMOR_SAFETY", "false").lower() in ("true", "1")
    )
    
    # Model Routing
    FAST_MODEL: str = Field(default_factory=lambda: os.getenv("FAST_MODEL", "gemini-3.7-flash"))
    REASONING_PRO_MODEL: str = Field(default_factory=lambda: os.getenv("REASONING_PRO_MODEL", "gemini-3.1-pro"))
    
    # Storage & Persistence
    DATABASE_URL: str = Field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./user_profiles.db"))
    MENU_GCS_BUCKET: Optional[str] = Field(default_factory=lambda: os.getenv("MENU_GCS_BUCKET"))

    @property
    def is_local(self) -> bool:
        return self.ENVIRONMENT.lower() in ("local", "dev", "test")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in ("production", "prod")


# Global config singleton
config = AppConfig()
