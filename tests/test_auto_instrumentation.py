"""Tests that auto-instrumentation works: instrumentors are discoverable via entry points
and produce spans when loaded and instrument() is called (as opentelemetry-instrument does).
"""

from __future__ import annotations

import re
from importlib.metadata import entry_points

from opentelemetry import trace as trace_api
from opentelemetry.test.globals_test import reset_trace_globals
from opentelemetry.test.test_base import TestBase

from tests.span_helpers import get_span_by_name


def test_re_instrumentor_loadable_via_entry_point() -> None:
    """The 're' instrumentor is registered and loadable via opentelemetry_instrumentor entry point."""
    group = entry_points(group="opentelemetry_instrumentor")
    re_ep = next((ep for ep in group if ep.name == "re"), None)
    assert re_ep is not None, "entry point 're' not found in opentelemetry_instrumentor"
    instrumentor_class = re_ep.load()
    assert instrumentor_class is not None
    # Same class we export
    from opentelemetry_instrumentation_re import ReInstrumentor

    assert instrumentor_class is ReInstrumentor


def test_auto_instrumentation_re_produces_spans() -> None:
    """Loading the re instrumentor via entry point and calling instrument() produces spans.
    This mirrors what opentelemetry-instrument does when it discovers and loads instrumentors.
    """
    group = entry_points(group="opentelemetry_instrumentor")
    re_ep = next((ep for ep in group if ep.name == "re"), None)
    assert re_ep is not None
    instrumentor_class = re_ep.load()

    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    memory_exporter.clear()

    instrumentor = instrumentor_class()
    instrumentor.instrument(tracer_provider=tracer_provider)
    try:
        m = re.search(r"\d+", "hello 42 world")
        assert m is not None
        assert m.group() == "42"
        spans = memory_exporter.get_finished_spans()
        span = get_span_by_name(spans, "re.search")
        assert span.attributes == {
            "re.operation": "search",
            "re.pattern": r"\d+",
            "re.string_length": 14,
            "re.library.name": "re",
        }
    finally:
        instrumentor.uninstrument()
        reset_trace_globals()


def test_all_instrumentors_registered() -> None:
    """All three instrumentors (re, regex, google_re2) are registered as entry points."""
    group = entry_points(group="opentelemetry_instrumentor")
    names = {ep.name for ep in group if ep.value.startswith("opentelemetry_instrumentation_re")}
    assert "re" in names
    assert "regex" in names
    assert "google_re2" in names
