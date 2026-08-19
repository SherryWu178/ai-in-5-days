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

"""Cloud-Native Structured JSON Logger capturing Intended Action vs Outcome."""

import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional

from app.observability.pii_scrubber import scrub_pii


class CloudStructuredJsonFormatter(logging.Formatter):
    """Formats log records as GCP Cloud Logging structured JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "severity": record.levelname,
            "logger": record.name,
            "message": scrub_pii(record.getMessage()),
        }

        # Include custom observability structured fields if attached
        custom_attrs = [
            "trace_id",
            "span_id",
            "session_id",
            "user_id",
            "node_name",
            "intended_action",
            "outcome",
            "duration_ms",
            "model_name",
            "prompt_tokens",
            "completion_tokens",
            "error_code",
        ]
        for attr in custom_attrs:
            if hasattr(record, attr):
                val = getattr(record, attr)
                if val is not None:
                    payload[attr] = scrub_pii(val)

        # Include GCP Cloud Trace correlation if GOOGLE_CLOUD_PROJECT is active
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        trace_id = payload.get("trace_id")
        if project_id and trace_id:
            payload["logging.googleapis.com/trace"] = f"projects/{project_id}/traces/{trace_id}"

        return json.dumps(payload, ensure_ascii=False)


def setup_structured_logger(logger_name: str = "app") -> logging.Logger:
    """Configures structured JSON logging for agent actions and outcomes."""
    logger = logging.getLogger(logger_name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(CloudStructuredJsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def log_agent_action(
    logger: logging.Logger,
    node_name: str,
    intended_action: str,
    outcome: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    duration_ms: Optional[float] = None,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    severity: int = logging.INFO,
) -> None:
    """Logs an explicit Intended Action vs Outcome record for ADK Agent nodes."""
    extra: Dict[str, Any] = {
        "node_name": node_name,
        "intended_action": intended_action,
        "outcome": outcome,
    }
    if session_id:
        extra["session_id"] = session_id
    if user_id:
        extra["user_id"] = user_id
    if duration_ms is not None:
        extra["duration_ms"] = round(duration_ms, 2)
    if trace_id:
        extra["trace_id"] = trace_id
    if span_id:
        extra["span_id"] = span_id
    if metadata:
        extra["metadata"] = scrub_pii(metadata)

    msg = f"[{node_name}] Action: '{intended_action}' -> Outcome: '{outcome}'"
    logger.log(severity, msg, extra=extra)
