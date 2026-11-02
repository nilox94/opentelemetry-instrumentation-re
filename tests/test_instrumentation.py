"""Parametrized tests for all regex instrumentors (re, regex, google-re2)."""

from __future__ import annotations

import collections.abc
import copy
import gc
import pickle
import re
import sys
import threading
import weakref
from typing import TYPE_CHECKING, Any

import pytest
from opentelemetry import trace as trace_api
from opentelemetry.instrumentation.utils import is_instrumentation_enabled
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.test.globals_test import reset_trace_globals
from opentelemetry.test.test_base import TestBase
from opentelemetry.trace import StatusCode

from opentelemetry_instrumentation_re import GoogleRe2Instrumentor, ReInstrumentor, core, recorder
from tests.span_helpers import (
    error_count,
    get_span_by_name,
    haystack_keyword,
    histogram_point_count,
    pattern_error_type,
)

if TYPE_CHECKING:
    from tests.conftest import Backend, InstrumentedBackend


def _search_attrs(library_name: str, pattern_len: int, string_len: int) -> dict[str, object]:
    return {
        "re.operation": "search",
        "re.pattern_length": pattern_len,
        "re.string_length": string_len,
        "re.library.name": library_name,
    }


def test_search_creates_span(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _metric_reader = instrumented_backend
    m = module.search(r"\d+", "hello 42 world")
    assert m is not None
    assert m.group() == "42"
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes == _search_attrs(library_name, 3, 14)
    assert histogram_point_count(_metric_reader) == 1


def test_match(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    _ = module.match(r"hello", "hello world")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.match")
    assert span.attributes == {
        "re.operation": "match",
        "re.pattern_length": 5,
        "re.string_length": 11,
        "re.library.name": library_name,
    }


def test_findall_sets_match_count(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    result = module.findall(r"\d+", "x1y22z333")
    assert result == ["1", "22", "333"]
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.findall")
    assert span.attributes == {
        "re.operation": "findall",
        "re.pattern_length": 3,
        "re.string_length": 9,
        "re.match_count": 3,
        "re.library.name": library_name,
    }


def test_compiled_pattern_search(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    pat = module.compile(r"\w+")
    _ = pat.search("hello world")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes == {
        "re.operation": "search",
        "re.pattern_length": 3,
        "re.string_length": 11,
        "re.library.name": library_name,
    }


def test_sub(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    result = module.sub(r"\d+", "0", "a1b2c3")
    assert result == "a0b0c0"
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.sub")
    assert span.attributes == {
        "re.operation": "sub",
        "re.pattern_length": 3,
        "re.string_length": 6,
        "re.library.name": library_name,
    }


def test_subn_sets_match_count(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    result = module.subn(r"x", "y", "xxy")
    assert result == ("yyy", 2)
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.subn")
    assert span.attributes == {
        "re.operation": "subn",
        "re.pattern_length": 1,
        "re.string_length": 3,
        "re.match_count": 2,
        "re.library.name": library_name,
    }


def test_finditer_instrumented(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    it = module.finditer(r"\d", "a1b2")
    assert isinstance(it, collections.abc.Iterator)
    assert type(it).__name__ != "callable_iterator"
    spans_before = memory_exporter.get_finished_spans()
    assert len(spans_before) == 0
    _ = list(it)
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.finditer")
    assert span.attributes == {
        "re.operation": "finditer",
        "re.pattern_length": 2,
        "re.string_length": 4,
        "re.library.name": library_name,
    }


def test_bytes_pattern(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    _ = module.search(rb"\d+", b"hello 42")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes == {
        "re.operation": "search",
        "re.pattern_length": 3,
        "re.string_length": 8,
        "re.library.name": library_name,
    }


def test_compiled_fullmatch(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    pat = module.compile(r"hello")
    _ = pat.fullmatch("hello")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.fullmatch")
    assert span.attributes == {
        "re.operation": "fullmatch",
        "re.pattern_length": 5,
        "re.string_length": 5,
        "re.library.name": library_name,
    }


def test_split(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    result = module.split(r",", "a,b,c")
    assert result == ["a", "b", "c"]
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.split")
    assert span.attributes == {
        "re.operation": "split",
        "re.pattern_length": 1,
        "re.string_length": 5,
        "re.library.name": library_name,
    }


def test_uninstrument_restores_behavior(
    backend: Backend, instrumented_backend: InstrumentedBackend
) -> None:
    module, _library_name, memory_exporter, metric_reader = instrumented_backend
    instrumentor_class = backend[1]
    _ = module.search(r"\d+", "hello 42")
    n_before = len(memory_exporter.get_finished_spans())
    count_before = histogram_point_count(metric_reader)
    assert n_before >= 1
    assert count_before >= 1
    instrumentor_class().uninstrument()
    assert type(module.compile("abc")).__name__ != "_TracedPattern"
    _ = module.search(r"\d+", "again 99")
    n_after = len(memory_exporter.get_finished_spans())
    assert n_after == n_before
    assert histogram_point_count(metric_reader) == count_before


def test_double_instrumentation_safe(
    backend: Backend, instrumented_backend: InstrumentedBackend
) -> None:
    module, _library_name, memory_exporter, metric_reader = instrumented_backend
    instrumentor = backend[1]()
    wrapped_search = module.search
    # Already instrumented by the fixture. A second call is a no-op: same
    # wrapper, and the new threshold / capture_pattern are ignored.
    instrumentor.instrument(span_threshold_ms=50, capture_pattern=True)
    assert module.search is wrapped_search
    memory_exporter.clear()
    assert module.search(r"\d+", "test 123") is not None
    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes is not None
    assert "re.pattern" not in spans[0].attributes
    assert histogram_point_count(metric_reader) == 1


def test_uninstrument_without_instrument(backend: Backend) -> None:
    instrumentor_class = backend[1]
    instrumentor = instrumentor_class()
    instrumentor.uninstrument()


def test_keyword_arguments(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    key = haystack_keyword(library_name)
    _ = module.search(pattern=r"\d+", **{key: "hello 42"})
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes["re.string_length"] == 8
    memory_exporter.clear()
    _ = module.search(r"\d+", **{key: "hello 42"})
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes["re.string_length"] == 8
    memory_exporter.clear()
    assert module.sub(r"\d+", "N", **{key: "a1b2"}) == "aNbN"
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.sub")
    assert span.attributes["re.string_length"] == 4
    memory_exporter.clear()
    pat = module.compile(r"\d+")
    assert pat.search(**{key: "ab12"}).group() == "12"
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.attributes["re.string_length"] == 4


def test_re2_string_keyword_rejected_as_uninstrumented(backend: Backend) -> None:
    module, instrumentor_class, library_name = backend
    if library_name != "google_re2":
        pytest.skip("only google-re2 names the haystack text")
    instrumentor_class().uninstrument()

    def outcome(call: Any) -> str:
        try:
            call()
        except TypeError:
            return "TypeError"
        return "ok"

    calls = (
        lambda: module.search(r"a", string="a"),
        lambda: module.sub(r"a", "b", string="a"),
        lambda: module.compile(r"a").search(string="a"),
    )
    plain = [outcome(call) for call in calls]
    instrumentor_class().instrument(span_threshold_ms=0)
    try:
        assert [outcome(call) for call in calls] == plain == ["TypeError"] * 3
    finally:
        instrumentor_class().uninstrument()


def _assert_marker_absent_from_span(span: Any, marker: str, *, attributes: bool) -> None:
    assert marker not in (span.status.description or "")
    if attributes and span.attributes:
        for value in span.attributes.values():
            if isinstance(value, str):
                assert marker not in value
    for event in span.events:
        if marker in event.name:
            raise AssertionError(marker)
        for value in (event.attributes or {}).values():
            if isinstance(value, str):
                assert marker not in value


def test_invalid_pattern_error_span(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, metric_reader = instrumented_backend
    with pytest.raises(Exception) as exc_info:
        module.search("hunter2(", "abc")
    exc = exc_info.value
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description in (None, "")
    assert not any(event.name == "exception" for event in span.events)
    assert span.attributes is not None
    assert isinstance(exc, module.error)
    assert span.attributes.get("error.type") == pattern_error_type(module)
    _assert_marker_absent_from_span(span, "hunter2", attributes=True)
    assert (
        error_count(
            metric_reader,
            operation="search",
            library=library_name,
            error_type=pattern_error_type(module),
        )
        == 1
    )


def test_compiled_findall_match_count(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    pat = module.compile(r"\d+")
    result = pat.findall("x1y22z333")
    assert result == ["1", "22", "333"]
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.findall")
    assert span.attributes["re.match_count"] == 3


def test_pattern_proxy_contract(instrumented_backend: InstrumentedBackend) -> None:
    module, _library_name, _memory_exporter, _ = instrumented_backend
    pat = module.compile("abc")
    inner_type = type(pat.__wrapped__)
    assert isinstance(pat, inner_type)
    assert type(pat) is not inner_type
    assert repr(pat) == repr(pat.__wrapped__)
    assert "search" in dir(pat)
    assert module.compile("abc") is pat
    copied = copy.copy(pat)
    assert copied.search("abc")
    cloned = copy.deepcopy(pat)
    assert cloned.search("abc")
    dumped = pickle.dumps(pat)
    loaded = pickle.loads(dumped)
    assert type(loaded) is inner_type
    assert b"opentelemetry_instrumentation_re" not in dumped
    assert loaded.search("abc")
    assert loaded.pattern == "abc"


def test_proxy_cache_does_not_pin(instrumented_backend: InstrumentedBackend) -> None:
    module, _library_name, _memory_exporter, _ = instrumented_backend
    refs = [weakref.ref(module.compile(f"unique-{i}-pat")) for i in range(20)]
    gc.collect()
    assert all(ref() is None for ref in refs)
    left = module.compile("abc")
    right = module.compile("abc")
    assert left is right


def test_missing_haystack_is_typeerror(instrumented_backend: InstrumentedBackend) -> None:
    module, _library_name, _memory_exporter, _ = instrumented_backend
    with pytest.raises(TypeError) as exc_info:
        module.search(r"\d+")
    message = str(exc_info.value).lower()
    assert "string" in message or "text" in message
    pat = module.compile(r"\d+")
    with pytest.raises(TypeError):
        pat.search()


def test_preinstrument_method_untraced(backend: Backend) -> None:
    module, instrumentor_class, _library_name = backend
    instrumentor_class().uninstrument()
    pre = module.compile(r"\d+")
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    instrumentor_class().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=0,
        histogram_floor_ms=0,
    )
    try:
        assert pre.search("12") is not None
        assert memory_exporter.get_finished_spans() == ()
        assert histogram_point_count(metric_reader) == 0
        assert module.search(pre, "12") is not None
        assert len(memory_exporter.get_finished_spans()) == 1
        assert histogram_point_count(metric_reader) == 1
    finally:
        instrumentor_class().uninstrument()
        reset_trace_globals()


def test_name_bound_before_instrument(backend: Backend) -> None:
    """Patching replaces function code, so bindings taken before instrument() are traced."""
    module, instrumentor_class, library_name = backend
    instrumentor_class().uninstrument()
    search = module.search
    compile_ = module.compile
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    instrumentor_class().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=0,
        histogram_floor_ms=0,
    )
    try:
        assert search is module.search
        assert compile_ is module.compile
        assert search(r"\d+", "12") is not None
        span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
        assert span.attributes is not None
        assert span.attributes["re.operation"] == "search"
        assert histogram_point_count(metric_reader) == 1
        assert module.search(r"\d+", "34") is not None
        assert len(memory_exporter.get_finished_spans()) == 2
        assert histogram_point_count(metric_reader) == 2
        memory_exporter.clear()
        pat = compile_(r"\d+")
        assert pat.search("56") is not None
        assert len(memory_exporter.get_finished_spans()) == 1
        assert histogram_point_count(metric_reader) == 3
        instrumentor_class().uninstrument()
        before = histogram_point_count(metric_reader)
        memory_exporter.clear()
        assert search(r"\d+", "78") is not None
        assert memory_exporter.get_finished_spans() == ()
        assert histogram_point_count(metric_reader) == before
    finally:
        instrumentor_class().uninstrument()
        reset_trace_globals()


def test_match_re_is_inner(instrumented_backend: InstrumentedBackend) -> None:
    module, _library_name, _memory_exporter, _ = instrumented_backend
    pat = module.compile(r"\d+")
    match = pat.search("a1")
    assert match is not None
    assert match.re is pat.__wrapped__


def test_finditer_duration_is_time_inside_next(
    instrumented_backend: InstrumentedBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Idle time between yields is not regex time, including time until GC."""
    module, library_name, memory_exporter, _ = instrumented_backend
    mono = {"now": 1_000_000_000}

    def monotonic_ns() -> int:
        return mono["now"]

    def epoch_ns() -> int:
        return 5_000_000_000

    monkeypatch.setattr(recorder, "monotonic_ns", monotonic_ns)
    monkeypatch.setattr(recorder, "epoch_ns", epoch_ns)

    class Engine:
        def __init__(self) -> None:
            self.n = 0

        def __iter__(self) -> Engine:
            return self

        def __next__(self) -> int:
            mono["now"] += 4_000_000
            self.n += 1
            if self.n > 2:
                raise StopIteration
            return self.n

    traced = core._MODULE_STATE[id(module)][0]
    iterator = core._execute(traced, "finditer", r"\d", "abcd", lambda: Engine())
    mono["now"] += 30_000_000_000
    assert list(iterator) == [1, 2]
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.finditer")
    assert span.start_time == 5_000_000_000
    assert span.end_time is not None
    # Three next() calls (the last raises StopIteration), 4ms each. The 30s gap is excluded.
    assert span.end_time - span.start_time == 12_000_000


def test_finditer_iteration_error(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, metric_reader = instrumented_backend

    class Bad:
        def __iter__(self) -> Bad:
            return self

        def __next__(self) -> str:
            raise RuntimeError("boom")

    traced = core._MODULE_STATE[id(module)][0]
    iterator = core._execute(traced, "finditer", r"\d", "abcd", lambda: Bad())
    # Do not use pytest.raises(match=...): that calls stdlib re.search.
    with pytest.raises(RuntimeError) as exc_info:
        next(iterator)
    assert str(exc_info.value) == "boom"
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.finditer")
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description in (None, "")
    assert not any(event.name == "exception" for event in span.events)
    assert span.attributes is not None
    assert span.attributes.get("error.type") == "RuntimeError"
    _assert_marker_absent_from_span(span, "boom", attributes=False)
    assert histogram_point_count(metric_reader) == 1
    assert (
        error_count(
            metric_reader,
            operation="finditer",
            library=library_name,
            error_type="RuntimeError",
        )
        == 1
    )


def test_abandoned_finditer_records_at_next_call(
    instrumented_backend: InstrumentedBackend,
) -> None:
    module, library_name, memory_exporter, metric_reader = instrumented_backend
    iterator = module.finditer(r"\d", "a1b2")
    ref = weakref.ref(iterator)
    del iterator
    gc.collect()
    assert ref() is None
    assert memory_exporter.get_finished_spans() == ()
    assert histogram_point_count(metric_reader) == 0
    module.search(r"x", "x")
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.finditer")
    assert span.attributes is not None
    assert span.attributes["re.operation"] == "finditer"
    assert histogram_point_count(metric_reader) == 2


def test_finditer_methods_match_engine(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, _memory_exporter, _metric_reader = instrumented_backend
    iterator = module.finditer(r"\d", "a1b2")
    is_generator = library_name == "google_re2"
    assert hasattr(iterator, "close") is is_generator
    assert hasattr(iterator, "throw") is is_generator
    list(iterator)


def test_finditer_close_finishes_once(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, metric_reader = instrumented_backend
    if library_name != "google_re2":
        pytest.skip("only google-re2 returns a generator with close()")
    iterator = module.finditer(r"\d", "a1b2")
    iterator.close()
    iterator.close()
    get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.finditer")
    assert len(memory_exporter.get_finished_spans()) == 1
    assert histogram_point_count(metric_reader) == 1


def test_compile_of_compiled_returns_same_proxy(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, metric_reader = instrumented_backend
    pat = module.compile("abc")
    assert module.compile(pat) is pat
    assert not isinstance(pat.__wrapped__, type(pat))
    if library_name == "google_re2":
        with pytest.raises(module.error):
            module.compile(pat, module.Options())
    else:
        with pytest.raises(ValueError):
            module.compile(pat, module.IGNORECASE)
    memory_exporter.clear()
    assert module.search(pat, "abc") is not None
    assert len(memory_exporter.get_finished_spans()) == 1
    assert histogram_point_count(metric_reader) == 1


def test_sub_callback_keeps_other_instrumentation(
    instrumented_backend: InstrumentedBackend,
) -> None:
    module, library_name, memory_exporter, metric_reader = instrumented_backend
    seen: dict[str, bool] = {}

    def repl(_match: object) -> str:
        seen["enabled"] = is_instrumentation_enabled()
        assert module.search(r"a", "a") is not None
        return "x"

    assert module.sub(r"\d", repl, "1") == "x"
    assert seen["enabled"] is True
    names = [span.name for span in memory_exporter.get_finished_spans()]
    assert names.count(f"{library_name}.sub") == 1
    assert names.count(f"{library_name}.search") == 1
    assert histogram_point_count(metric_reader) == 2


def test_sub_callback_records_compiled_method(instrumented_backend: InstrumentedBackend) -> None:
    """A pattern method called from sub() is its own operation, including google-re2."""
    module, library_name, memory_exporter, metric_reader = instrumented_backend

    def repl(_match: object) -> str:
        assert module.compile("a").search("a") is not None
        return "x"

    assert module.sub(r"\d", repl, "1") == "x"
    names = [span.name for span in memory_exporter.get_finished_spans()]
    assert names.count(f"{library_name}.sub") == 1
    assert names.count(f"{library_name}.search") == 1
    assert histogram_point_count(metric_reader) == 2


def test_compiled_callable_sub_excludes_callback(
    instrumented_backend: InstrumentedBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pattern sub/subn, and repl=, record engine time and a nested call."""
    module, library_name, memory_exporter, metric_reader = instrumented_backend
    mono = {"now": 1_000_000_000}

    def monotonic_ns() -> int:
        return mono["now"]

    def epoch_ns() -> int:
        return 5_000_000_000

    monkeypatch.setattr(recorder, "monotonic_ns", monotonic_ns)
    monkeypatch.setattr(recorder, "epoch_ns", epoch_ns)
    pat = module.compile(r"\d")

    def repl(_match: object) -> str:
        mono["now"] += 50_000_000
        assert module.compile("a").search("a") is not None
        return "Z"

    def assert_recorded(operation: str, *, match_count: int | None = None) -> None:
        span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.{operation}")
        assert span.start_time == 5_000_000_000
        assert span.end_time == 5_000_000_000
        assert span.status.status_code == StatusCode.UNSET
        if match_count is not None:
            assert span.attributes is not None
            assert span.attributes["re.match_count"] == match_count
        get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.search")
        memory_exporter.clear()

    before = histogram_point_count(metric_reader)
    assert pat.sub(repl, "1") == "Z"
    assert_recorded("sub")
    key = haystack_keyword(library_name)
    assert pat.sub(repl=repl, **{key: "1"}) == "Z"
    assert_recorded("sub")
    assert module.sub(r"\d", repl=repl, **{key: "1"}) == "Z"
    assert_recorded("sub")
    assert pat.subn(repl, "1") == ("Z", 1)
    assert_recorded("subn", match_count=1)
    # Each call is the replacement plus the search made inside it.
    assert histogram_point_count(metric_reader) == before + 8


def test_sub_callback_error_is_not_regex_error(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, metric_reader = instrumented_backend

    def repl(_match: object) -> str:
        raise ValueError("cb")

    with pytest.raises(ValueError) as exc_info:
        module.sub(r"\d", repl, "1")
    assert str(exc_info.value) == "cb"
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.sub")
    assert span.status.status_code == StatusCode.UNSET
    assert not any(event.name == "exception" for event in span.events)
    assert histogram_point_count(metric_reader) == 1
    assert (
        error_count(
            metric_reader,
            operation="sub",
            library=library_name,
            error_type="ValueError",
        )
        == 0
    )


def test_pickle_preserves_re2_options(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, _ = instrumented_backend
    if library_name != "google_re2":
        pytest.skip("stdlib and regex pickle paths are covered by the proxy contract test")
    options = module.Options()
    options.case_sensitive = False
    options.dot_nl = True
    pat = module.compile("a.c", options)
    dumped = pickle.dumps(pat)
    loaded = pickle.loads(dumped)
    assert type(loaded) is type(pat.__wrapped__)
    assert b"opentelemetry_instrumentation_re" not in dumped
    assert loaded.search("A\nC") is not None
    cased_dump = pickle.dumps(module.compile("abc", options))
    cased = pickle.loads(cased_dump)
    assert type(cased) is type(pat.__wrapped__)
    assert b"opentelemetry_instrumentation_re" not in cased_dump
    assert cased.search("ABC") is not None
    assert cased.search("ab") is None
    memory_exporter.clear()
    assert cased.search("ABC") is not None
    assert memory_exporter.get_finished_spans() == ()


def test_deepcopy_keeps_shared_proxy(instrumented_backend: InstrumentedBackend) -> None:
    module, _library_name, _memory_exporter, _metric_reader = instrumented_backend
    pat = module.compile("abc")
    bundle = {"left": pat, "right": pat}
    cloned = copy.deepcopy(bundle)
    assert cloned["left"] is cloned["right"]
    assert cloned["left"].search("abc")


def test_reinstrument_revives_proxy(backend: Backend) -> None:
    module, instrumentor_class, _library_name = backend
    instrumentor_class().uninstrument()
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = instrumentor_class()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=0,
        histogram_floor_ms=0,
    )
    try:
        pat = module.compile("abc")
        inst.uninstrument()
        assert pat.search("abc")
        assert memory_exporter.get_finished_spans() == ()
        inst.instrument(
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            span_threshold_ms=0,
            histogram_floor_ms=0,
        )
        assert module.compile("abc") is pat
        assert pat.search("zzabc")
        assert len(memory_exporter.get_finished_spans()) == 1
        assert histogram_point_count(metric_reader) == 1
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_finditer_plain_iterator_has_no_close_or_throw(
    instrumented_backend: InstrumentedBackend,
) -> None:
    module, _library_name, _memory_exporter, _metric_reader = instrumented_backend

    class NoThrow:
        def __iter__(self) -> NoThrow:
            return self

        def __next__(self) -> str:
            return "x"

    traced = core._MODULE_STATE[id(module)][0]
    iterator: Any = core._execute(traced, "finditer", r"\d", "abcd", lambda: NoThrow())
    assert not hasattr(iterator, "close")
    assert not hasattr(iterator, "throw")


def test_finditer_injected_throw_is_not_regex_error(
    instrumented_backend: InstrumentedBackend,
) -> None:
    module, library_name, memory_exporter, metric_reader = instrumented_backend

    class Rethrows:
        def __iter__(self) -> Rethrows:
            return self

        def __next__(self) -> str:
            return "x"

        def throw(self, exc: BaseException) -> str:
            raise exc

    traced = core._MODULE_STATE[id(module)][0]
    iterator: Any = core._execute(traced, "finditer", r"\d", "abcd", lambda: Rethrows())
    err = ValueError("x")
    with pytest.raises(ValueError) as exc_info:
        iterator.throw(err)
    assert exc_info.value is err
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.finditer")
    assert span.status.status_code != StatusCode.ERROR
    assert span.attributes is not None
    assert "error.type" not in span.attributes
    assert histogram_point_count(metric_reader) == 1
    assert (
        error_count(
            metric_reader,
            operation="finditer",
            library=library_name,
            error_type="ValueError",
        )
        == 0
    )


def test_re2_finditer_throw_forwards_to_generator(backend: Backend) -> None:
    module, instrumentor_class, library_name = backend
    if library_name != "google_re2":
        pytest.skip("only google-re2 returns a generator")
    metric_reader = InMemoryMetricReader()
    inst = instrumentor_class()
    inst.instrument(
        meter_provider=MeterProvider(metric_readers=[metric_reader]), histogram_floor_ms=0
    )
    try:
        iterator = module.finditer(r"\d", "a1b2")
        assert next(iterator).group() == "1"
        err = KeyError("stop")
        with pytest.raises(KeyError) as exc_info:
            iterator.throw(err)
        assert exc_info.value is err
        assert histogram_point_count(metric_reader) == 1
        assert (
            error_count(
                metric_reader, operation="finditer", library=library_name, error_type="KeyError"
            )
            == 0
        )
    finally:
        inst.uninstrument()


def test_finditer_swallowed_throw_stays_open(instrumented_backend: InstrumentedBackend) -> None:
    module, _library_name, memory_exporter, metric_reader = instrumented_backend

    class Swallows:
        def __iter__(self) -> Swallows:
            return self

        def __next__(self) -> str:
            raise StopIteration

        def throw(self, _typ: object, _val: object = None, _tb: object = None) -> str:
            return "kept"

    traced = core._MODULE_STATE[id(module)][0]
    iterator = core._execute(traced, "finditer", r"\d", "abcd", lambda: Swallows())
    assert iterator.throw(RuntimeError("nope")) == "kept"
    assert memory_exporter.get_finished_spans() == ()
    assert histogram_point_count(metric_reader) == 0


def test_finditer_close_error_finishes(instrumented_backend: InstrumentedBackend) -> None:
    module, library_name, memory_exporter, metric_reader = instrumented_backend

    class BadClose:
        def __iter__(self) -> BadClose:
            return self

        def __next__(self) -> str:
            return "x"

        def throw(self, exc: BaseException) -> str:
            raise exc

        def close(self) -> None:
            raise RuntimeError("close failed")

    traced = core._MODULE_STATE[id(module)][0]
    iterator = core._execute(traced, "finditer", r"\d", "abcd", lambda: BadClose())
    with pytest.raises(RuntimeError) as exc_info:
        iterator.close()
    assert str(exc_info.value) == "close failed"
    span = get_span_by_name(memory_exporter.get_finished_spans(), f"{library_name}.finditer")
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description in (None, "")
    assert not any(event.name == "exception" for event in span.events)
    assert span.attributes is not None
    assert span.attributes.get("error.type") == "RuntimeError"
    _assert_marker_absent_from_span(span, "close failed", attributes=False)
    assert histogram_point_count(metric_reader) == 1
    assert (
        error_count(
            metric_reader,
            operation="finditer",
            library=library_name,
            error_type="RuntimeError",
        )
        == 1
    )
    with pytest.raises(RuntimeError) as again:
        iterator.close()
    assert str(again.value) == "close failed"
    assert histogram_point_count(metric_reader) == 1
    assert (
        error_count(
            metric_reader,
            operation="finditer",
            library=library_name,
            error_type="RuntimeError",
        )
        == 1
    )


def test_re2_capture_does_not_put_pattern_in_status(backend: Backend) -> None:
    module, _instrumentor_class, library_name = backend
    if library_name != "google_re2":
        pytest.skip("only google-re2 embeds the pattern in its error string")
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = GoogleRe2Instrumentor()
    inst.instrument(
        tracer_provider=tracer_provider,
        span_threshold_ms=0,
        capture_pattern=True,
    )
    try:
        with pytest.raises(Exception) as exc_info:
            module.search("hunter2(", "abc")
        assert type(exc_info.value).__name__
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.status.description in (None, "")
        assert not any(event.name == "exception" for event in span.events)
        assert "hunter2" not in (span.status.description or "")
        for event in span.events:
            for value in (event.attributes or {}).values():
                if isinstance(value, str):
                    assert "hunter2" not in value
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_callers_survive_instrument_cycle() -> None:
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    errors: list[str] = []
    stop = threading.Event()

    def worker() -> None:
        while not stop.is_set():
            try:
                re.search("a", "a")
            except Exception as exc:
                errors.append(repr(exc))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
    for thread in threads:
        thread.start()
    inst = ReInstrumentor()
    try:
        for _ in range(400):
            inst.instrument()
            inst.uninstrument()
    finally:
        stop.set()
        for thread in threads:
            thread.join()
        sys.setswitchinterval(interval)
        inst.uninstrument()
    assert errors == []
    match = re.search("a", "a")
    assert match is not None
    assert hasattr(re, "_otel_re_fn_search")


def test_finditer_finalizer_skips_atexit(instrumented_backend: InstrumentedBackend) -> None:
    module, _library_name, _memory_exporter, _metric_reader = instrumented_backend
    iterator = module.finditer(r"\d", "a1b2")
    assert iterator._finalizer.atexit is False
