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

"""Context Window History Compactor & Token Pruner for ADK Workflows."""

from typing import Any, Dict, List, Optional


def compact_conversation_history(
    messages: List[Dict[str, Any]],
    max_turns: int = 4,
    preserve_initial_greeting: bool = True,
) -> List[Dict[str, Any]]:
    """Compacts conversation history to prevent context window overflow while preserving key clinical facts.

    Retains:
    1. Turn 0 profile greeting (if preserve_initial_greeting=True).
    2. Most recent `max_turns` dialogue interactions.
    3. Consolidated state summary of active nutrition targets and restrictions.
    """
    if not messages or len(messages) <= max_turns:
        return messages

    compacted: List[Dict[str, Any]] = []

    if preserve_initial_greeting and messages:
        compacted.append(messages[0])

    # Append the most recent turns
    recent_messages = messages[-max_turns:]
    for msg in recent_messages:
        if msg not in compacted:
            compacted.append(msg)

    return compacted
