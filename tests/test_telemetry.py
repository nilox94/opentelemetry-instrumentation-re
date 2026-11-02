"""Metrics and default telemetry policy tests."""

from __future__ import annotations

import gc
import logging
import re
import time
from typing import TYPE_CHECKING

import pytest
from opentelemetry import trace as trace_api
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ParentBased
from opentelemetry.test.globals_test import reset_trace_globals
from opentelemetry.test.test_base import TestBase
from opentelemetry.trace import StatusCode

from opentelemetry_instrumentation_re import ReInstrumentor
from opentelemetry_instrumentation_re import core as core_mod
from opentelemetry_instrumentation_re import recorder as recorder_mod
from tests.span_helpers import error_count, histogram_point_count, pattern_error_type

if TYPE_CHECKING:
    from tests.conftest import Backend


def test_fast_call_records_metric_not_span() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=10,
        histogram_floor_ms=0,
    )
    try:
        re.search(r"\d+", "x")
        assert len(memory_exporter.get_finished_spans()) == 0
        assert histogram_point_count(metric_reader) == 1
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_default_floor_skips_fast_success() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)
    try:
        assert re.search(r"\d+", "a1").group() == "1"
        assert re.compile(r"\d").findall("1a2") == ["1", "2"]
        assert list(re.finditer(r"\d", "1a2"))
        assert re.sub(r"\d", lambda m: "x", "1a2") == "xax"
        assert histogram_point_count(metric_reader) == 0
        assert memory_exporter.get_finished_spans() == ()
    finally:
        inst.uninstrument()
        reset_trace_globals()


@pytest.mark.parametrize(("step_ns", "expected"), [(99_000, 0), (100_000, 1), (2_000_000, 1)])
def test_histogram_floor_boundary(
    monkeypatch: pytest.MonkeyPatch, step_ns: int, expected: int
) -> None:
    mono = {"now": 0}

    def monotonic_ns() -> int:
        mono["now"] += step_ns
        return mono["now"]

    monkeypatch.setattr(recorder_mod, "monotonic_ns", monotonic_ns)
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)
    try:
        re.compile(r"\d").search("1")
        assert histogram_point_count(metric_reader) == expected
        assert memory_exporter.get_finished_spans() == ()
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_capture_pattern_opt_in() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0, capture_pattern=True)
    try:
        re.search("secret", "a secret")
        span = memory_exporter.get_finished_spans()[0]
        assert span.attributes is not None
        assert span.attributes.get("re.pattern") == "secret"
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_capture_pattern_bytes_and_compiled() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0, capture_pattern=True)
    try:
        re.search(b"ab\xff", b"ab\xff")
        span = memory_exporter.get_finished_spans()[0]
        assert span.attributes is not None
        assert span.attributes["re.pattern"] == "ab\ufffd"
        assert span.attributes["re.pattern_length"] == 3
        memory_exporter.clear()
        re.compile("secret").search("secret")
        span = memory_exporter.get_finished_spans()[0]
        assert span.attributes is not None
        assert span.attributes["re.pattern"] == "secret"
        assert span.attributes["re.pattern_length"] == 6
        memory_exporter.clear()
        re.compile(b"caf\xc3\xa9").search(b"caf\xc3\xa9")
        span = memory_exporter.get_finished_spans()[0]
        assert span.attributes is not None
        assert span.attributes["re.pattern"] == "café"
        assert span.attributes["re.pattern_length"] == 5
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_capture_pattern_truncated() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(
        tracer_provider=tracer_provider,
        span_threshold_ms=0,
        capture_pattern=True,
        capture_pattern_max_len=4,
    )
    try:
        re.search("abcdefgh", "abcdefgh")
        span = memory_exporter.get_finished_spans()[0]
        assert span.attributes is not None
        assert span.attributes.get("re.pattern") == "abcd"
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_default_omits_pattern_text() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)
    try:
        re.search("secret", "secret")
        span = memory_exporter.get_finished_spans()[0]
        assert span.attributes is not None
        assert "re.pattern" not in span.attributes
    finally:
        inst.uninstrument()
        reset_trace_globals()


def _duration_points_have_error_type(reader: InMemoryMetricReader) -> bool:
    data = reader.get_metrics_data()
    if data is None:
        return False
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != "re.operation.duration":
                    continue
                for point in metric.data.data_points:
                    if point.attributes and "error.type" in point.attributes:
                        return True
    return False


def _counter_attr_contains(reader: InMemoryMetricReader, marker: str) -> bool:
    data = reader.get_metrics_data()
    if data is None:
        return False
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != "re.operation.errors":
                    continue
                for point in metric.data.data_points:
                    for value in (point.attributes or {}).values():
                        if isinstance(value, str) and marker in value:
                            return True
    return False


def test_fast_error_is_counted_not_spanned(backend: Backend) -> None:
    module, instrumentor_class, library_name = backend
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = instrumentor_class()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=10,
    )
    try:
        with pytest.raises(module.error):
            module.search("hunter2(", "abc")
        assert memory_exporter.get_finished_spans() == ()
        assert histogram_point_count(metric_reader) == 0
        assert (
            error_count(
                metric_reader,
                operation="search",
                library=library_name,
                error_type=pattern_error_type(module),
            )
            == 1
        )
        assert not _duration_points_have_error_type(metric_reader)
        assert not _counter_attr_contains(metric_reader, "hunter2")
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_slow_error_span_omits_message(monkeypatch: pytest.MonkeyPatch) -> None:
    mono = {"now": 0}

    def monotonic_ns() -> int:
        mono["now"] += 20_000_000
        return mono["now"]

    monkeypatch.setattr(
        "opentelemetry_instrumentation_re.recorder.monotonic_ns",
        monotonic_ns,
    )
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=10,
    )
    try:
        with pytest.raises(re.error):
            re.search("hunter2(", "abc")
        spans = memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.status.status_code == StatusCode.ERROR
        assert span.status.description in (None, "")
        assert not any(event.name == "exception" for event in span.events)
        assert span.attributes is not None
        assert span.attributes.get("error.type") == "re.error"
        assert "hunter2" not in (span.status.description or "")
        for value in span.attributes.values():
            if isinstance(value, str):
                assert "hunter2" not in value
        for event in span.events:
            for value in (event.attributes or {}).values():
                if isinstance(value, str):
                    assert "hunter2" not in value
        assert (
            error_count(
                metric_reader,
                operation="search",
                library="re",
                error_type="re.error",
            )
            == 1
        )
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_span_timestamps_are_epoch() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)
    try:
        before = time.time_ns()
        re.search(r"\d+", "a1")
        after = time.time_ns()
        span = memory_exporter.get_finished_spans()[0]
        assert span.start_time is not None
        assert span.end_time is not None
        assert before <= span.start_time <= after
        assert span.start_time <= span.end_time <= after + 1_000_000_000
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_processor_and_exporter_do_not_recurse() -> None:
    class Processor(SpanProcessor):
        def __init__(self) -> None:
            self.calls = 0

        def on_start(self, span, parent_context=None) -> None:
            return None

        def on_end(self, span) -> None:
            self.calls += 1
            re.search(r"a", "a")

    class Exporter(SpanExporter):
        def __init__(self) -> None:
            self.calls = 0

        def export(self, spans):
            self.calls += 1
            re.search(r"b", "b")
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            return None

    processor = Processor()
    exporter = Exporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(processor)
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    inst = ReInstrumentor()
    inst.uninstrument()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=0,
        histogram_floor_ms=0,
    )
    try:
        re.search(r"\d+", "a1")
        assert processor.calls == 1
        assert exporter.calls == 1
        assert histogram_point_count(metric_reader) == 1
    finally:
        inst.uninstrument()


def test_failed_patch_restores_module(monkeypatch: pytest.MonkeyPatch) -> None:
    inst = ReInstrumentor()
    inst.uninstrument()
    original_search = re.search
    real_wrapper = core_mod._make_module_wrapper

    def flaky(recorder, name, original):
        if name == "findall":
            raise RuntimeError("boom")
        return real_wrapper(recorder, name, original)

    monkeypatch.setattr(core_mod, "_make_module_wrapper", flaky)
    with pytest.raises(RuntimeError, match="boom"):
        inst.instrument(span_threshold_ms=0)
    assert inst.is_instrumented_by_opentelemetry is False
    assert re.search is original_search
    assert type(re.compile("zz")) is re.Pattern
    assert re.search(r"a", "a") is not None

    monkeypatch.setattr(core_mod, "_make_module_wrapper", real_wrapper)
    inst.instrument(span_threshold_ms=0)
    try:
        assert re.search(r"\d+", "12") is not None
    finally:
        inst.uninstrument()


def test_capture_pattern_string_false() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.uninstrument()
    inst.instrument(
        tracer_provider=tracer_provider,
        span_threshold_ms=0,
        capture_pattern="false",
    )
    try:
        re.search("secret", "secret")
        span = memory_exporter.get_finished_spans()[0]
        assert span.attributes is not None
        assert "re.pattern" not in span.attributes
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_negative_config_is_rejected_before_patch() -> None:
    inst = ReInstrumentor()
    inst.uninstrument()
    original_search = re.search
    with pytest.raises(ValueError):
        inst.instrument(capture_pattern_max_len=-1)
    with pytest.raises(ValueError):
        inst.instrument(span_threshold_ms=-1)
    with pytest.raises(ValueError):
        inst.instrument(histogram_floor_ms=float("nan"))
    with pytest.raises(ValueError):
        inst.instrument(capture_pattern="maybe")
    assert inst.is_instrumented_by_opentelemetry is False
    assert re.search is original_search
    assert type(re.compile("zz")) is re.Pattern


def test_invalid_env_falls_back(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("OTEL_PYTHON_RE_SPAN_THRESHOLD_MS", "-5")
    monkeypatch.setenv("OTEL_PYTHON_RE_HISTOGRAM_FLOOR_MS", "fast")
    monkeypatch.setenv("OTEL_PYTHON_RE_CAPTURE_PATTERN", "nope")
    monkeypatch.setenv("OTEL_PYTHON_RE_CAPTURE_PATTERN_MAX_LEN", "-1")
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.uninstrument()
    with caplog.at_level("WARNING"):
        inst.instrument(tracer_provider=tracer_provider)
    try:
        assert "OTEL_PYTHON_RE_SPAN_THRESHOLD_MS" in caplog.text
        assert "OTEL_PYTHON_RE_HISTOGRAM_FLOOR_MS" in caplog.text
        assert "OTEL_PYTHON_RE_CAPTURE_PATTERN" in caplog.text
        assert "OTEL_PYTHON_RE_CAPTURE_PATTERN_MAX_LEN" in caplog.text
        re.search(r"\d+", "a1")
        # Invalid threshold falls back to 10ms, so a fast call has no span.
        assert memory_exporter.get_finished_spans() == ()
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_env_config_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_PYTHON_RE_SPAN_THRESHOLD_MS", "0")
    monkeypatch.setenv("OTEL_PYTHON_RE_CAPTURE_PATTERN", "yes")
    monkeypatch.setenv("OTEL_PYTHON_RE_CAPTURE_PATTERN_MAX_LEN", "4")
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.uninstrument()
    inst.instrument(tracer_provider=tracer_provider)
    try:
        re.search("abcdefgh", "abcdefgh")
        span = memory_exporter.get_finished_spans()[0]
        assert span.attributes is not None
        assert span.attributes["re.pattern"] == "abcd"
        assert span.attributes["re.pattern_length"] == 8
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_callback_time_and_consumer_time_are_not_regex_time() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.uninstrument()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=10,
        histogram_floor_ms=0,
    )
    try:

        def repl(match: re.Match[str]) -> str:
            time.sleep(0.02)
            raise ValueError(match.group())

        with pytest.raises(ValueError):
            re.sub(r"\d", repl, "1")
        for _match in re.finditer(r"\d", "a1b2"):
            time.sleep(0.02)
        # 20ms of callback / loop time must not look like a slow regex.
        assert memory_exporter.get_finished_spans() == ()
        assert histogram_point_count(metric_reader) == 2
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_telemetry_failure_returns_match(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.uninstrument()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)
    calls = {"n": 0}

    def boom(*_args: object, **_kwargs: object) -> None:
        calls["n"] += 1
        raise RuntimeError("meter down")

    recorder = core_mod._MODULE_STATE[id(re)][0]
    monkeypatch.setattr(recorder, "record_finished", boom)
    try:
        match = re.search(r"\d+", "a1")
        assert match is not None
        assert match.group() == "1"
        assert calls["n"] == 1
        assert memory_exporter.get_finished_spans() == ()
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_telemetry_failure_preserves_pattern_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer_provider, _memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.uninstrument()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("meter down")

    recorder = core_mod._MODULE_STATE[id(re)][0]
    monkeypatch.setattr(recorder, "record_finished", boom)
    try:
        with pytest.raises(re.error):
            re.search("[", "abc")
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_unsampled_parent_still_records_histogram() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=ParentBased(ALWAYS_OFF))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # get_tracer compiles warning filters with re before we instrument.
    tracer = provider.get_tracer("test")
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    inst = ReInstrumentor()
    inst.instrument(
        tracer_provider=provider,
        meter_provider=meter_provider,
        span_threshold_ms=10,
        histogram_floor_ms=0,
    )
    try:
        with tracer.start_as_current_span("request") as span:
            assert span.is_recording() is False
            context = span.get_span_context()
            assert context.is_valid is True
            assert context.trace_flags.sampled is False
            re.search(r"\d+", "abc123")
        assert histogram_point_count(metric_reader) == 1
        assert exporter.get_finished_spans() == ()
    finally:
        inst.uninstrument()


def test_suppress_instrumentation_skips_histogram() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=10,
        histogram_floor_ms=0,
    )
    try:
        with suppress_instrumentation():
            re.search(r"\d+", "abc123")
        assert histogram_point_count(metric_reader) == 0
        assert memory_exporter.get_finished_spans() == ()
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_histogram_floor_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_PYTHON_RE_HISTOGRAM_FLOOR_MS", "0")
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    inst = ReInstrumentor()
    inst.uninstrument()
    inst.instrument(meter_provider=meter_provider)
    try:
        re.search(r"\d+", "a1")
        assert histogram_point_count(metric_reader) == 1
    finally:
        inst.uninstrument()


def test_telemetry_failure_logged_once_and_not_recursive() -> None:
    class FailingProcessor(SpanProcessor):
        def on_start(self, span, parent_context=None) -> None:
            return None

        def on_end(self, span) -> None:
            raise RuntimeError("exporter down")

    class RegexHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records = 0

        def emit(self, record: logging.LogRecord) -> None:
            self.records += 1
            re.sub(r"\d", "#", record.getMessage())

    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(FailingProcessor())
    handler = RegexHandler()
    logger = logging.getLogger(core_mod.__name__)
    logger.addHandler(handler)
    inst = ReInstrumentor()
    inst.uninstrument()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)
    try:
        for _ in range(50):
            assert re.search(r"\d", "a1").group() == "1"
        assert handler.records == 1
        inst.uninstrument()
        inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)
        re.search(r"\d", "a1")
        assert handler.records == 2
    finally:
        logger.removeHandler(handler)
        inst.uninstrument()


def test_finditer_collected_while_recording_is_dropped() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    inst = ReInstrumentor()
    inst.uninstrument()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=0,
        histogram_floor_ms=0,
    )
    try:
        iterator = re.finditer(r"\d", "a1")
        token = recorder_mod._RECORDING.set(True)
        try:
            del iterator
            gc.collect()
        finally:
            recorder_mod._RECORDING.reset(token)
        assert histogram_point_count(metric_reader) == 0
        assert memory_exporter.get_finished_spans() == ()
        iterator = re.finditer(r"\d", "a1")
        del iterator
        gc.collect()
        assert histogram_point_count(metric_reader) == 1
    finally:
        inst.uninstrument()
