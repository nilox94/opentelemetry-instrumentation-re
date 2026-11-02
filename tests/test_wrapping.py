"""Wrapping and API compatibility tests (stdlib re)."""

from __future__ import annotations

import copy
import pickle
import re
import subprocess
import sys

from opentelemetry import trace as trace_api
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.test.globals_test import reset_trace_globals
from opentelemetry.test.test_base import TestBase

from opentelemetry_instrumentation_re import ReInstrumentor


def test_compiled_pattern_module_search() -> None:
    tracer_provider, memory_exporter = TestBase.create_tracer_provider()
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_threshold_ms=0,
    )
    try:
        pat = re.compile(r"\d+")
        assert re.search(pat, "abc 12") is not None
        assert len(memory_exporter.get_finished_spans()) == 1
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_compile_cache_identity() -> None:
    tracer_provider, _ = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)
    try:
        a = re.compile("abc")
        b = re.compile("abc")
        assert a is b
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_copy_and_pickle() -> None:
    tracer_provider, _ = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)
    try:
        pat = re.compile("x", re.IGNORECASE)
        copied = copy.copy(pat)
        assert copied.search("X")
        cloned = copy.deepcopy(pat)
        assert cloned.search("X")
        dumped = pickle.dumps(pat)
        loaded = pickle.loads(dumped)
        assert type(loaded) is re.Pattern
        assert b"opentelemetry_instrumentation_re" not in dumped
        assert loaded.search("X")
        assert loaded.pattern == "x"
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_missing_string_typeerror() -> None:
    tracer_provider, _ = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)
    try:
        try:
            re.search(r"\d+")
        except TypeError as exc:
            assert "string" in str(exc).lower()
        else:
            raise AssertionError("expected TypeError")
    finally:
        inst.uninstrument()
        reset_trace_globals()


def test_stdlib_pickle_loads_without_this_package() -> None:
    tracer_provider, _memory_exporter = TestBase.create_tracer_provider()
    reset_trace_globals()
    trace_api.set_tracer_provider(tracer_provider)
    inst = ReInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, span_threshold_ms=0)
    try:
        data = pickle.dumps(re.compile(r"\d+"))
    finally:
        inst.uninstrument()
        reset_trace_globals()
    assert b"opentelemetry_instrumentation_re" not in data
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import pickle,sys; p=pickle.loads(sys.stdin.buffer.read()); "
            "assert p.search('a1').group()=='1'",
        ],
        input=data,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
