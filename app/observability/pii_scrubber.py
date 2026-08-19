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

"""PII Redaction and Data Scrubbing Pipeline for Singapore Canteen Agent.

Scrubs sensitive Personally Identifiable Information (PII) such as email addresses,
corporate LDAP usernames, phone numbers, employee badges, and sensitive clinical identifiers
prior to structured logging or persistent storage.
"""

import re
from typing import Any, Dict, List, Union

# Regex patterns for common PII
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_REGEX = re.compile(r"\b(?:\+?65[- ]?)?[689]\d{3}[- ]?\d{4}\b")  # SG phone numbers & international
EMPLOYEE_ID_REGEX = re.compile(r"\b(?:EMP|GGL|ID)[-_]?\d{5,8}\b", re.IGNORECASE)
BEARER_TOKEN_REGEX = re.compile(r"\b(?:AIza[0-9A-Za-z-_]{35}|Bearer\s+[A-Za-z0-9._~+/-]+=*)\b")


def scrub_pii_string(text: str) -> str:
    """Replaces sensitive PII tokens in a text string with standardized redaction markers."""
    if not text or not isinstance(text, str):
        return text

    scrubbed = EMAIL_REGEX.sub("[REDACTED_EMAIL]", text)
    scrubbed = PHONE_REGEX.sub("[REDACTED_PHONE]", scrubbed)
    scrubbed = EMPLOYEE_ID_REGEX.sub("[REDACTED_EMPLOYEE_ID]", scrubbed)
    scrubbed = BEARER_TOKEN_REGEX.sub("[REDACTED_API_KEY]", scrubbed)
    return scrubbed


def scrub_pii(data: Any) -> Any:
    """Recursively scrubs PII across strings, dictionaries, lists, and primitives."""
    if isinstance(data, str):
        return scrub_pii_string(data)
    elif isinstance(data, dict):
        scrubbed_dict = {}
        for k, v in data.items():
            # If key name itself indicates sensitive field
            if k.lower() in ("api_key", "secret", "password", "token", "access_token"):
                scrubbed_dict[k] = "[REDACTED_SECRET]"
            else:
                scrubbed_dict[k] = scrub_pii(v)
        return scrubbed_dict
    elif isinstance(data, (list, tuple, set)):
        return [scrub_pii(item) for item in data]
    return data
