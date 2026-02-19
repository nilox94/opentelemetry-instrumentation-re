"""Parametrized tests for all regex instrumentors (re, regex, google-re2).

Backend parametrization is applied automatically to tests that use the
backend or instrumented_backend fixture (see conftest.pytest_generate_tests).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.span_helpers import get_span_by_name

if TYPE_CHECKING:
    from tests.conftest import Backend, InstrumentedBackend


def test_search_creates_span(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    m = module.search(r"\d+", "hello 42 world")
    assert m is not None
    assert m.group() == "42"
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes == {
        "re.operation": "search",
        "re.pattern": r"\d+",
        "re.string_length": 14,
        "re.library.name": library_name,
    }


def test_match(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    _ = module.match(r"hello", "hello world")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.match")
    assert span.attributes == {
        "re.operation": "match",
        "re.pattern": "hello",
        "re.string_length": 11,
        "re.library.name": library_name,
    }


def test_findall_sets_match_count(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    pat = module.compile(r"\d+")
    result = pat.findall("x1y22z333")
    assert result == ["1", "22", "333"]
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.findall")
    assert span.attributes == {
        "re.operation": "findall",
        "re.pattern": r"\d+",
        "re.string_length": 9,
        "re.match_count": 3,
        "re.library.name": library_name,
    }


def test_compiled_pattern_search(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    pat = module.compile(r"\w+")
    _ = pat.search("hello world")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes == {
        "re.operation": "search",
        "re.pattern": r"\w+",
        "re.string_length": 11,
        "re.library.name": library_name,
    }


def test_sub(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    result = module.sub(r"\d+", "0", "a1b2c3")
    assert result == "a0b0c0"
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.sub")
    assert span.attributes == {
        "re.operation": "sub",
        "re.pattern": r"\d+",
        "re.string_length": 6,
        "re.library.name": library_name,
    }


def test_subn_sets_match_count(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    result = module.subn(r"x", "y", "xxy")
    assert result == ("yyy", 2)
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.subn")
    assert span.attributes == {
        "re.operation": "subn",
        "re.pattern": "x",
        "re.string_length": 3,
        "re.match_count": 2,
        "re.library.name": library_name,
    }


def test_pattern_captured(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    _ = module.search("secret", "a secret")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes == {
        "re.operation": "search",
        "re.pattern": "secret",
        "re.string_length": 8,
        "re.library.name": library_name,
    }


def test_finditer_instrumented(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    it = module.finditer(r"\d", "a1b2")
    _ = list(it)
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.finditer")
    assert span.attributes == {
        "re.operation": "finditer",
        "re.pattern": r"\d",
        "re.string_length": 4,
        "re.library.name": library_name,
    }


def test_compiled_findall_match_count(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    pat = module.compile(r"\d+")
    result = pat.findall("x1y22z333")
    assert result == ["1", "22", "333"]
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.findall")
    assert span.attributes == {
        "re.operation": "findall",
        "re.pattern": r"\d+",
        "re.string_length": 9,
        "re.match_count": 3,
        "re.library.name": library_name,
    }


def test_bytes_pattern(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    _ = module.search(rb"\d+", b"hello 42")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes == {
        "re.operation": "search",
        "re.pattern": r"\d+",
        "re.string_length": 8,
        "re.library.name": library_name,
    }


def test_compiled_fullmatch(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    pat = module.compile(r"hello")
    _ = pat.fullmatch("hello")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.fullmatch")
    assert span.attributes == {
        "re.operation": "fullmatch",
        "re.pattern": "hello",
        "re.string_length": 5,
        "re.library.name": library_name,
    }


def test_split(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter = instrumented_backend
    result = module.split(r",", "a,b,c")
    assert result == ["a", "b", "c"]
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.split")
    assert span.attributes == {
        "re.operation": "split",
        "re.pattern": ",",
        "re.string_length": 5,
        "re.library.name": library_name,
    }


def test_full_pattern_captured(instrumented_backend: InstrumentedBackend) -> None:
    """Long pattern is fully captured in span attributes."""
    module, library_name, memory_exporter = instrumented_backend
    long_pattern = "a" * 300
    _ = module.search(long_pattern, "a" * 5)
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes == {
        "re.operation": "search",
        "re.pattern": long_pattern,
        "re.string_length": 5,
        "re.library.name": library_name,
    }


def test_uninstrument_restores_behavior(
    backend: Backend, instrumented_backend: InstrumentedBackend
) -> None:
    module, _library_name, memory_exporter = instrumented_backend
    instrumentor_class = backend[1]
    _ = module.search(r"\d+", "hello 42")
    n_before = len(memory_exporter.get_finished_spans())
    assert n_before >= 1
    instrumentor_class().uninstrument()
    _ = module.search(r"\d+", "again 99")
    n_after = len(memory_exporter.get_finished_spans())
    assert n_after == n_before  # no new spans after uninstrument


def test_double_instrumentation_safe(
    backend: Backend, instrumented_backend: InstrumentedBackend
) -> None:
    module, _library_name, memory_exporter = instrumented_backend
    instrumentor_class = backend[1]
    instrumentor = instrumentor_class()
    instrumentor.instrument()
    _ = module.search(r"\d+", "test 123")
    assert len(memory_exporter.get_finished_spans()) >= 1


def test_uninstrument_without_instrument(backend: Backend) -> None:
    instrumentor_class = backend[1]
    instrumentor = instrumentor_class()
    instrumentor.uninstrument()
    # Idempotent; should not raise
