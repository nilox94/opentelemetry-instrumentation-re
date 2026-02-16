"""Helpers for re instrumentation: attribute names and pattern extraction."""

from __future__ import annotations

import re

RE_PATTERN = "re.pattern"
RE_FUNCTION = "re.function"
RE_STRING_LENGTH = "re.string_length"
RE_MATCH_COUNT = "re.match_count"


def get_pattern_string(pattern: str | bytes | re.Pattern[str] | re.Pattern[bytes]) -> str:
    """Extract pattern string from pattern (str, bytes, or Pattern).

    Returns:
        The pattern as a string. Bytes patterns are decoded using UTF-8.
    """
    if isinstance(pattern, re.Pattern):
        unwrapped: str | bytes = pattern.pattern
    else:
        unwrapped = pattern

    if isinstance(unwrapped, bytes):
        return unwrapped.decode("utf-8", errors="replace")
    return unwrapped
