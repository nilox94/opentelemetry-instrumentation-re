"""Pattern extraction and protocol for re instrumentation.

Attribute names are defined in _semconv (semantic conventions). This module
re-exports them for backward compatibility and provides pattern extraction.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from opentelemetry_instrumentation_re.utils.semconv import (
    RE_FUNCTION,
    RE_MATCH_COUNT,
    RE_PATTERN,
    RE_STRING_LENGTH,
)

__all__ = [
    "RE_FUNCTION",
    "RE_MATCH_COUNT",
    "RE_PATTERN",
    "RE_STRING_LENGTH",
    "PatternLike",
    "get_pattern_string",
]


@runtime_checkable
class PatternLike(Protocol):
    """Protocol for compiled pattern objects (re.Pattern, regex.Pattern, google-re2)."""

    @property
    def pattern(self) -> str | bytes: ...


def get_pattern_string(pattern: str | bytes | PatternLike) -> str:
    """Extract pattern string from pattern (str, bytes, or compiled Pattern-like).

    Returns:
        The pattern as a string. Bytes patterns are decoded using UTF-8.
    """
    if isinstance(pattern, PatternLike):
        unwrapped: str | bytes = pattern.pattern
    else:
        unwrapped = pattern

    if isinstance(unwrapped, bytes):
        return unwrapped.decode("utf-8", errors="replace")
    return unwrapped
