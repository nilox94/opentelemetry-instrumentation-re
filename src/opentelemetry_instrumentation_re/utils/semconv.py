"""Attribute names for regex instrumentation.

The ``re.*`` names are defined by this package. They are not part of the
OpenTelemetry semantic conventions and may change between releases. They follow
OpenTelemetry naming: lowercase, dot-delimited, snake_case within components.
``error.type`` is the semantic-convention attribute.
"""

from __future__ import annotations

# Span and metric attributes for regex operations
RE_PATTERN = "re.pattern"
"""The regex pattern string when capture is explicitly enabled."""

RE_PATTERN_LENGTH = "re.pattern_length"
"""Length of the pattern string (non-sensitive)."""

RE_OPERATION = "re.operation"
"""The operation name: search, match, fullmatch, split, finditer, findall, sub, subn."""

RE_STRING_LENGTH = "re.string_length"
"""Length of the string being searched/substituted (for cost/volume hints)."""

RE_MATCH_COUNT = "re.match_count"
"""Number of matches (for findall and subn result attributes)."""

RE_LIBRARY_NAME = "re.library.name"
"""Name of the instrumented regex implementation: re, regex, or google_re2."""

ERROR_TYPE = "error.type"
"""``<module>.error`` for the backend's pattern error, otherwise the exception class name.

Builtins are unqualified (``TypeError``); other classes include their module.
"""
