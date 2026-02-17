"""Utility modules for opentelemetry-instrumentation-re."""

from __future__ import annotations

# Re-export commonly used utilities if needed
from opentelemetry_instrumentation_re.utils.pattern import (
    RE_FUNCTION,
    RE_MATCH_COUNT,
    RE_PATTERN,
    RE_STRING_LENGTH,
    PatternLike,
    get_pattern_string,
)
from opentelemetry_instrumentation_re.utils.semconv import RE_LIBRARY_NAME
from opentelemetry_instrumentation_re.utils.tracer import create_tracer

__all__ = [
    "RE_FUNCTION",
    "RE_LIBRARY_NAME",
    "RE_MATCH_COUNT",
    "RE_PATTERN",
    "RE_STRING_LENGTH",
    "PatternLike",
    "create_tracer",
    "get_pattern_string",
]
