"""Runtime configuration for regex instrumentation."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    return None


def _parse_threshold(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _parse_max_len(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            return None
        return int(value)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def _require(value: Any, parsed: Any, message: str) -> Any:
    if parsed is None:
        raise ValueError(f"{message}, got {value!r}")
    return parsed


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    parsed = _parse_bool(raw)
    if parsed is None:
        _log.warning("ignoring invalid %s=%r; using %s", name, raw, default)
        return default
    return parsed


def _env_threshold(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    parsed = _parse_threshold(raw)
    if parsed is None:
        _log.warning("ignoring invalid %s=%r; using %s", name, raw, default)
        return default
    return parsed


def _env_max_len(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    parsed = _parse_max_len(raw)
    if parsed is None:
        _log.warning("ignoring invalid %s=%r; using %s", name, raw, default)
        return default
    return parsed


@dataclass(frozen=True, slots=True)
class InstrumentationConfig:
    """Knobs for spans, metrics, and pattern capture."""

    span_threshold_ms: float = 10.0
    histogram_floor_ms: float = 0.1
    capture_pattern: bool = False
    capture_pattern_max_len: int = 256

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> InstrumentationConfig:
        span_threshold_ms = kwargs.get("span_threshold_ms")
        if span_threshold_ms is None:
            span_threshold_ms = _env_threshold("OTEL_PYTHON_RE_SPAN_THRESHOLD_MS", 10.0)
        else:
            span_threshold_ms = _require(
                span_threshold_ms,
                _parse_threshold(span_threshold_ms),
                "span_threshold_ms must be a finite number >= 0",
            )
        histogram_floor_ms = kwargs.get("histogram_floor_ms")
        if histogram_floor_ms is None:
            histogram_floor_ms = _env_threshold("OTEL_PYTHON_RE_HISTOGRAM_FLOOR_MS", 0.1)
        else:
            histogram_floor_ms = _require(
                histogram_floor_ms,
                _parse_threshold(histogram_floor_ms),
                "histogram_floor_ms must be a finite number >= 0",
            )
        capture_pattern = kwargs.get("capture_pattern")
        if capture_pattern is None:
            capture_pattern = _env_bool("OTEL_PYTHON_RE_CAPTURE_PATTERN", False)
        else:
            capture_pattern = _require(
                capture_pattern,
                _parse_bool(capture_pattern),
                "capture_pattern must be a boolean",
            )
        capture_pattern_max_len = kwargs.get("capture_pattern_max_len")
        if capture_pattern_max_len is None:
            capture_pattern_max_len = _env_max_len("OTEL_PYTHON_RE_CAPTURE_PATTERN_MAX_LEN", 256)
        else:
            capture_pattern_max_len = _require(
                capture_pattern_max_len,
                _parse_max_len(capture_pattern_max_len),
                "capture_pattern_max_len must be an integer >= 0",
            )
        return cls(
            span_threshold_ms=span_threshold_ms,
            histogram_floor_ms=histogram_floor_ms,
            capture_pattern=capture_pattern,
            capture_pattern_max_len=capture_pattern_max_len,
        )
