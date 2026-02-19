"""Semantic convention attributes for regex instrumentation.

These attribute names follow OpenTelemetry naming: lowercase, dot-delimited
namespacing, snake_case within components. They are intended to be reusable
for any regex-like library (any language) when documenting pattern operations.
"""

from __future__ import annotations

# Span attributes for regex operations (stable)
RE_PATTERN = "re.pattern"
"""The regex pattern string (or bytes decoded to string)."""

RE_OPERATION = "re.operation"
"""The operation name: search, match, fullmatch, split, finditer, findall, sub, subn."""

RE_STRING_LENGTH = "re.string_length"
"""Length of the string being searched/substituted (for cost/volume hints)."""

RE_MATCH_COUNT = "re.match_count"
"""Number of matches (for findall and subn result attributes)."""

RE_LIBRARY_NAME = "re.library.name"
"""Name of the instrumented regex implementation: re, regex, or google_re2."""
