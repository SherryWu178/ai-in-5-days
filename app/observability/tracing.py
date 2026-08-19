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

"""Distributed Tracing wrapper supporting OpenTelemetry & Google Cloud Trace."""

from contextlib import contextmanager
import logging
import os
import time
from typing import Any, Dict, Generator, Optional
import uuid

logger = logging.getLogger(__name__)


class TraceSpanContext:
    """Lightweight span representation for timing and attribute injection."""

    def __init__(
        self,
        name: str,
        trace_id: str,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.trace_id = trace_id
        self.span_id = uuid.uuid4().hex[:16]
        self.parent_span_id = parent_span_id
        self.attributes: Dict[str, Any] = attributes or {}
        self.start_time = time.perf_counter()
        self.duration_ms: float = 0.0

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def finish(self) -> float:
        self.duration_ms = (time.perf_counter() - self.start_time) * 1000.0
        return self.duration_ms


@contextmanager
def trace_span(
    operation_name: str,
    trace_id: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> Generator[TraceSpanContext, None, None]:
    """Context manager for distributed span tracing across agent workflow steps."""
    tid = trace_id or os.environ.get("GCP_TRACE_ID") or uuid.uuid4().hex
    span = TraceSpanContext(name=operation_name, trace_id=tid, attributes=attributes)
    try:
        yield span
    finally:
        duration_ms = span.finish()
        logger.debug(
            "Span [%s] completed in %.2f ms (trace_id=%s, span_id=%s)",
            operation_name,
            duration_ms,
            span.trace_id,
            span.span_id,
        )
