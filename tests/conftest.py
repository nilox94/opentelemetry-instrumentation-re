# conftest.py
"""Pytest configuration and shared fixtures for opentelemetry-instrumentation-re tests."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, TypeAlias

import pytest
from opentelemetry import trace as trace_api
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.test.globals_test import reset_trace_globals
from opentelemetry.test.test_base import TestBase

from opentelemetry_instrumentation_re import (
    GoogleRe2Instrumentor,
    RegexInstrumentor,
    ReInstrumentor,
)

if TYPE_CHECKING:
    from collections.abc import Generator

BACKEND_NAMES = ("re", "regex", "google_re2")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "backend" in metafunc.fixturenames or "instrumented_backend" in metafunc.fixturenames:
        metafunc.parametrize("backend", BACKEND_NAMES, indirect=True)


Backend: TypeAlias = tuple[Any, type[BaseInstrumentor], str]
InstrumentedBackend: TypeAlias = tuple[Any, str, InMemorySpanExporter, InMemoryMetricReader]


def _backend_re() -> Backend:
    return (re, ReInstrumentor, "re")


def _backend_regex() -> Backend:
    try:
        import regex

        return (regex, RegexInstrumentor, "regex")
    except ImportError as e:
        pytest.skip(f"regex module not installed: {e}")


def _backend_google_re2() -> Backend:
    try:
        import re2

        return (re2, GoogleRe2Instrumentor, "google_re2")
    except ImportError as e:
        pytest.skip(f"re2 module (google-re2) not installed: {e}")


_BACKEND_LOADERS = {
    "re": _backend_re,
    "regex": _backend_regex,
    "google_re2": _backend_google_re2,
}


@pytest.fixture
def backend(request: pytest.FixtureRequest) -> Backend:
    name: str = request.param
    loader = _BACKEND_LOADERS[name]
    return loader()


@pytest.fixture
def instrumented_backend(
    backend: Backend,
) -> Generator[InstrumentedBackend, Any, Any]:
    module, instrumentor_class, library_name = backend
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    memory_exporter.clear()
    instrumentor_class().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=0,
        histogram_floor_ms=0,
    )
    try:
        yield (module, library_name, memory_exporter, metric_reader)
    finally:
        instrumentor_class().uninstrument()
        reset_trace_globals()
