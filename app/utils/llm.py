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

"""LLM Client utility with automatic .env loading and error handling."""

import logging
import os
from pathlib import Path
from typing import Optional

from google import genai

logger = logging.getLogger(__name__)


def load_env_file() -> None:
    """Loads environment variables from .env file if present."""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'").strip('"')
                        if k and not os.environ.get(k):
                            os.environ[k] = v
        except Exception as e:
            logger.warning("Failed to parse .env file: %s", e)


def get_genai_client() -> Optional[genai.Client]:
    """Returns an initialized genai.Client if API credentials are available, else None."""
    load_env_file()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") in ("1", "true", "True")

    if not api_key and not use_vertex:
        logger.debug("No GEMINI_API_KEY or GOOGLE_GENAI_USE_VERTEXAI found; falling back to non-LLM mode.")
        return None

    try:
        if api_key:
            return genai.Client(api_key=api_key)
        return genai.Client()
    except Exception as e:
        logger.warning("Failed to initialize genai.Client: %s", e)
        return None
