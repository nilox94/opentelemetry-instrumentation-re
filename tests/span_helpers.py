"""Shared test helpers for regex instrumentors (re, regex, google-re2).

Some backends (e.g. google-re2) may produce more than one span per module-level
call (e.g. search() calling compile().search() internally). get_span_by_name
picks the first span matching the expected name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opentelemetry.sdk.trace import ReadableSpan


def get_span_by_name(spans: Sequence[ReadableSpan], name: str) -> ReadableSpan:
    """Return the first span with the given name. Asserts at least one span exists."""
    assert len(spans) >= 1, f"expected at least 1 span, got {len(spans)}"
    for s in spans:
        if s.name == name:
            return s
    raise AssertionError(f"no span named {name!r} in {[s.name for s in spans]}")
