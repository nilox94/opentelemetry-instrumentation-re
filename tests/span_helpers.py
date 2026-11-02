"""Shared test helpers for regex instrumentors (re, regex, google-re2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace import ReadableSpan

_DURATION_METRIC = "re.operation.duration"
_ERROR_METRIC = "re.operation.errors"


def histogram_point_count(reader: InMemoryMetricReader) -> int:
    """Sum of histogram counts for ``re.operation.duration``."""
    data = reader.get_metrics_data()
    if data is None:
        return 0
    total = 0
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != _DURATION_METRIC:
                    continue
                total += sum(point.count for point in metric.data.data_points)
    return total


def error_count(
    reader: InMemoryMetricReader,
    *,
    operation: str,
    library: str,
    error_type: str,
) -> int:
    """Sum of ``re.operation.errors`` for one operation, library, and exception class."""
    data = reader.get_metrics_data()
    if data is None:
        return 0
    total = 0
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != _ERROR_METRIC:
                    continue
                for point in metric.data.data_points:
                    attrs = point.attributes or {}
                    if (
                        attrs.get("re.operation") == operation
                        and attrs.get("re.library.name") == library
                        and attrs.get("error.type") == error_type
                    ):
                        total += int(point.value)
    return total


def pattern_error_type(module: object) -> str:
    """``error.type`` for the backend's own pattern error (``re.error``, ``re2.error``)."""
    return f"{getattr(module, '__name__', '')}.error"


def haystack_keyword(library_name: str) -> str:
    """google-re2 names the searched text ``text``; ``re`` and ``regex`` name it ``string``."""
    return "text" if library_name == "google_re2" else "string"


def get_span_by_name(spans: Sequence[ReadableSpan], name: str) -> ReadableSpan:
    """Return the only span with the given name."""
    matches = [s for s in spans if s.name == name]
    assert len(matches) == 1, (
        f"expected exactly 1 span named {name!r}, got {len(matches)}: {[s.name for s in spans]}"
    )
    return matches[0]
