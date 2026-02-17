# conftest.py
"""Pytest configuration and shared fixtures for opentelemetry-instrumentation-re tests."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, TypeAlias

import pytest
from opentelemetry import trace as trace_api
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
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

# Backends: (module, instrumentor_class, library_name for spans)
BACKEND_NAMES = ("re", "regex", "google_re2")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize any test that uses `backend` or `instrumented_backend` over `BACKEND_NAMES` fixtures."""
    if "backend" in metafunc.fixturenames or "instrumented_backend" in metafunc.fixturenames:
        metafunc.parametrize("backend", BACKEND_NAMES, indirect=True)


Backend: TypeAlias = tuple[Any, type[BaseInstrumentor], str]
InstrumentedBackend: TypeAlias = tuple[Any, str, InMemorySpanExporter]


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
    """Parametrized backend: (module, instrumentor_class, library_name). Use with indirect=True."""
    name: str = request.param
    loader = _BACKEND_LOADERS[name]
    return loader()


@pytest.fixture
def instrumented_backend(
    backend: Backend,
) -> Generator[InstrumentedBackend, Any, Any]:
    """Setup tracer provider + instrument the backend; yield (module, library_name, memory_exporter); teardown."""
    module, instrumentor_class, library_name = backend
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    memory_exporter.clear()
    instrumentor_class().instrument(tracer_provider=tracer_provider)
    try:
        yield (module, library_name, memory_exporter)
    finally:
        instrumentor_class().uninstrument()
        reset_trace_globals()
