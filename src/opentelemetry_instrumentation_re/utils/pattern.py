"""Pattern extraction for re instrumentation."""

from __future__ import annotations

from typing import Any


def unwrap_pattern(pattern: Any) -> Any:
    """Return the underlying compiled pattern if ``pattern`` is a proxy."""
    seen: set[int] = set()
    current = pattern
    while True:
        inner = getattr(current, "__wrapped__", None)
        if inner is None or id(inner) in seen:
            return current
        seen.add(id(current))
        current = inner


def get_pattern_string(pattern: Any, *, decode_bytes: bool = False) -> str:
    """Extract a pattern string from str, bytes, or a compiled pattern-like object."""
    if isinstance(pattern, (str, bytes)):
        raw: str | bytes = pattern
    else:
        unwrapped = unwrap_pattern(pattern)
        raw_attr = getattr(unwrapped, "pattern", None)
        if isinstance(raw_attr, (str, bytes)):
            raw = raw_attr
        elif isinstance(unwrapped, (str, bytes)):
            raw = unwrapped
        else:
            raise TypeError(f"unsupported pattern type: {type(pattern)!r}")

    if isinstance(raw, bytes):
        if decode_bytes:
            return raw.decode("utf-8", errors="replace")
        return raw.decode("latin-1")
    return raw
