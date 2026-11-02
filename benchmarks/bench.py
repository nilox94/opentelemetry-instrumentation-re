"""Hot-path timings for regex instrumentation.

Run from the repo root:

    uv run python benchmarks/bench.py

The report is the budget for this machine. BENCHMARKS.md is how to read it.
The script stamps the interpreter, the OpenTelemetry SDK, and the hardware,
and each cell is a median with the min and max of that run. Added
microseconds (``wrapper`` and ``histogram``) are the decision numbers. A
ratio against a short match is not. The match past 10 ms is paired single
calls, not a 40 ms batch: that scan moves by more than the wrapper.

``noop`` is the wrapper (no-op meter). ``sdk`` is an SDK meter that does not
export. At the default ``histogram_floor_ms`` (100 µs) a fast call records no
histogram point, so ``sdk − noop`` is near zero. The ``floor 0`` row records
every call; its ``sdk − noop`` is ``Histogram.record``. ``instrument()`` with
no meter provider follows ``noop`` until a global ``MeterProvider`` exists.
``compile()`` records no histogram. Its wrapper is the proxy. sdk − noop is
not that cost.

Each repeat is calibrated to about 40 ms, so a sub-microsecond call is not a
1 ms sample. pyperf is not used: the script has to run from this repo's
environment, and a checked-in gate would fail on the run-to-run movement the
spread is here to show.
"""

from __future__ import annotations

import gc
import importlib
import pathlib
import platform
import re
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from opentelemetry.instrumentation.utils import is_instrumentation_enabled
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opentelemetry_instrumentation_re import (
    GoogleRe2Instrumentor,
    RegexInstrumentor,
    ReInstrumentor,
)
from opentelemetry_instrumentation_re.recorder import _RECORDING, capture_start
from opentelemetry_instrumentation_re.utils.meter import create_duration_histogram, create_meter

_TARGET_NS = 40_000_000
_REPEATS = 5
_WINDOWS = 3
# Separate samples move by about this much from row to row. A smaller gap is
# not a second cost.
_NOTICE_US = 0.10
_FINDITER = "1a2b3c4d5e"
# Matches in the per-match rows. The short rows have 5 (finditer) and 3 (sub).
_MANY = 1_000
_MANY_TEXT = "a1" * _MANY


@dataclass(frozen=True)
class Sample:
    """Microseconds per call across repeats."""

    median: float
    low: float
    high: float


@dataclass(frozen=True)
class Row:
    """One operation under the three meter setups."""

    label: str
    raw: Sample
    noop: Sample
    sdk: Sample


@dataclass(frozen=True)
class SlowMatch:
    """Paired single calls. Extras are instrumented minus bare, in µs."""

    raw: Sample
    noop_extra: Sample
    sdk_extra: Sample


class _Discard(SpanExporter):
    """Exporter that accepts spans and keeps none."""

    def export(self, spans: Any) -> SpanExportResult:
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def _loops(fn: Callable[[], None]) -> int:
    """How many calls fill about ``_TARGET_NS``."""
    loops = 1
    elapsed = 0
    while elapsed < 2_000_000 and loops < 100_000:
        loops *= 10
        started = time.perf_counter_ns()
        for _ in range(loops):
            fn()
        elapsed = time.perf_counter_ns() - started
    if elapsed <= 0:
        return 1
    return max(1, int(_TARGET_NS * loops / elapsed))


def _sample(fn: Callable[[], None]) -> Sample:
    loops = _loops(fn)
    warmup = max(1, loops // 5)
    for _ in range(warmup):
        fn()
    taken: list[float] = []
    for _ in range(_REPEATS):
        started = time.perf_counter_ns()
        for _ in range(loops):
            fn()
        taken.append((time.perf_counter_ns() - started) / loops / 1_000)
    return Sample(statistics.median(taken), min(taken), max(taken))


def _off(inst: Any) -> None:
    if inst.is_instrumented_by_opentelemetry:
        inst.uninstrument()


def _on(inst: Any, **kwargs: Any) -> None:
    _off(inst)
    inst.instrument(**kwargs)


def _three(
    inst: Any,
    raw_fn: Callable[[], None],
    factory: Callable[[], Callable[[], None]],
    **kwargs: Any,
) -> tuple[Sample, Sample, Sample]:
    """Time ``raw_fn`` bare, then ``factory()`` with a no-op meter and an SDK meter."""
    _off(inst)
    raw = _sample(raw_fn)
    _on(inst, meter_provider=NoOpMeterProvider(), **kwargs)
    try:
        noop = _sample(factory())
    finally:
        _off(inst)
    meter = MeterProvider(metric_readers=[InMemoryMetricReader()])
    _on(inst, meter_provider=meter, **kwargs)
    try:
        sdk = _sample(factory())
    finally:
        _off(inst)
        meter.shutdown()
    return raw, noop, sdk


def _compiled(
    inst: Any,
    label: str,
    pattern: str,
    text: str,
    *,
    keyword: bool = False,
    **kwargs: Any,
) -> Row:
    raw_pattern = re.compile(pattern)

    def raw() -> None:
        if keyword:
            raw_pattern.search(text, pos=0)
        else:
            raw_pattern.search(text)

    def factory() -> Callable[[], None]:
        compiled = re.compile(pattern)

        def run() -> None:
            if keyword:
                compiled.search(text, pos=0)
            else:
                compiled.search(text)

        return run

    raw_s, noop_s, sdk_s = _three(inst, raw, factory, **kwargs)
    return Row(label, raw_s, noop_s, sdk_s)


def _callable(inst: Any, label: str, fn: Callable[[], None], **kwargs: Any) -> Row:
    raw_s, noop_s, sdk_s = _three(inst, fn, lambda: fn, **kwargs)
    return Row(label, raw_s, noop_s, sdk_s)


def _pack(taken: list[float]) -> Sample:
    return Sample(statistics.median(taken), min(taken), max(taken))


def _paired(bare: Callable[[], None], instrumented: Callable[[], None]) -> tuple[Sample, Sample]:
    """Alternate which call goes first. The second sample is instrumented minus bare, in µs."""
    bare()
    instrumented()
    raws: list[float] = []
    diffs: list[float] = []
    for turn in range(7):
        if turn % 2:
            started = time.perf_counter_ns()
            instrumented()
            middle = time.perf_counter_ns()
            bare()
            finished = time.perf_counter_ns()
            raw_us = (finished - middle) / 1_000
            diff_us = (middle - started) / 1_000 - raw_us
        else:
            started = time.perf_counter_ns()
            bare()
            middle = time.perf_counter_ns()
            instrumented()
            finished = time.perf_counter_ns()
            raw_us = (middle - started) / 1_000
            diff_us = (finished - middle) / 1_000 - raw_us
        raws.append(raw_us)
        diffs.append(diff_us)
    return _pack(raws), _pack(diffs)


def _time_batch(fn: Callable[[], None], loops: int) -> float:
    started = time.perf_counter_ns()
    for _ in range(loops):
        fn()
    return (time.perf_counter_ns() - started) / loops / 1_000


def _alternating(
    left: Callable[[], None], right: Callable[[], None]
) -> tuple[Sample, Sample, Sample]:
    """Time ``left`` and ``right`` back to back. The third sample is right − left.

    Which side runs first alternates, so a slow stretch does not settle on one call.
    """
    loops = _loops(left)
    warmup = max(1, loops // 5)
    for _ in range(warmup):
        left()
        right()
    lefts: list[float] = []
    rights: list[float] = []
    diffs: list[float] = []
    for turn in range(_REPEATS):
        if turn % 2:
            right_us = _time_batch(right, loops)
            left_us = _time_batch(left, loops)
        else:
            left_us = _time_batch(left, loops)
            right_us = _time_batch(right, loops)
        lefts.append(left_us)
        rights.append(right_us)
        diffs.append(right_us - left_us)
    return _pack(lefts), _pack(rights), _pack(diffs)


def _slow_match(inst: Any, text: str) -> SlowMatch:
    """Match past 10 ms, paired with the bare search.

    A 40 ms batch would average the scan's own movement into the cell. The
    movement is the result, and it is wider than the wrapper. The call is past
    the span threshold, so the extra includes a non-recording span.
    """
    raw_pattern = re.compile("z")

    def bare() -> None:
        raw_pattern.search(text)

    _on(inst, span_threshold_ms=10, meter_provider=NoOpMeterProvider())
    try:
        pattern = re.compile("z")
        _raw, noop_extra = _paired(bare, lambda: pattern.search(text))
    finally:
        _off(inst)
    meter = MeterProvider(metric_readers=[InMemoryMetricReader()])
    _on(inst, span_threshold_ms=10, meter_provider=meter)
    try:
        pattern = re.compile("z")
        raw, sdk_extra = _paired(bare, lambda: pattern.search(text))
    finally:
        _off(inst)
        meter.shutdown()
    return SlowMatch(raw, noop_extra, sdk_extra)


def _keyword_gap(inst: Any, text: str) -> Sample:
    """Keyword minus positional, µs/call, with the two calls alternating."""
    meter = MeterProvider(metric_readers=[InMemoryMetricReader()])
    _on(inst, span_threshold_ms=10, meter_provider=meter)
    try:
        pattern = re.compile(r"\d+")

        def positional() -> None:
            pattern.search(text)

        def keyword() -> None:
            pattern.search(text, pos=0)

        _positional, _keyword, gap = _alternating(positional, keyword)
        return gap
    finally:
        _off(inst)
        meter.shutdown()


def _over_threshold_text() -> str:
    """Haystack whose raw search is past the default 10 ms span threshold."""
    pattern = re.compile("z")
    size = 250_000
    while size < 80_000_000:
        text = "a" * size
        taken = []
        for _ in range(3):
            started = time.perf_counter_ns()
            pattern.search(text)
            taken.append(time.perf_counter_ns() - started)
        if statistics.median(taken) >= 12_000_000:
            return text
        size = int(size * 15_000_000 / max(statistics.median(taken), 1)) + 1
    return "a" * size


def _cell(sample: Sample) -> str:
    return f"{sample.median:.2f} [{sample.low:.2f}–{sample.high:.2f}]"


def _overlap(left: Sample, right: Sample) -> bool:
    return left.low <= right.high and right.low <= left.high


def _resolved(diff: Sample) -> bool:
    """True when a paired gap stays off zero and is wider than its own noise."""
    width = diff.high - diff.low
    return (diff.low > 0 or diff.high < 0) and width < abs(diff.median)


def _delta(left: Sample, right: Sample) -> str:
    """Median difference, unless the two ranges overlap."""
    if _overlap(left, right):
        return "within spread"
    return f"{left.median - right.median:+.2f}"


def _print_table(rows: list[Row]) -> None:
    raw_cells = [_cell(row.raw) for row in rows]
    noop_cells = [_cell(row.noop) for row in rows]
    sdk_cells = [_cell(row.sdk) for row in rows]
    wrapper_cells = [_delta(row.noop, row.raw) for row in rows]
    histogram_cells = [_delta(row.sdk, row.noop) for row in rows]
    op_w = max(len("operation"), *(len(row.label) for row in rows))
    raw_w = max(len("raw µs"), *(len(cell) for cell in raw_cells))
    noop_w = max(len("noop µs"), *(len(cell) for cell in noop_cells))
    sdk_w = max(len("sdk µs"), *(len(cell) for cell in sdk_cells))
    wrap_w = max(len("wrapper"), *(len(cell) for cell in wrapper_cells))
    hist_w = max(len("histogram"), *(len(cell) for cell in histogram_cells))
    print(
        f"{'operation':<{op_w}}  {'raw µs':<{raw_w}}  {'noop µs':<{noop_w}}  "
        f"{'sdk µs':<{sdk_w}}  {'wrapper':>{wrap_w}}  {'histogram':>{hist_w}}"
    )
    for row, raw_cell, noop_cell, sdk_cell, wrapper, histogram in zip(
        rows, raw_cells, noop_cells, sdk_cells, wrapper_cells, histogram_cells, strict=True
    ):
        print(
            f"{row.label:<{op_w}}  {raw_cell:<{raw_w}}  {noop_cell:<{noop_w}}  "
            f"{sdk_cell:<{sdk_w}}  {wrapper:>{wrap_w}}  {histogram:>{hist_w}}"
        )


def _extra_us(diff: Sample) -> str:
    return f"{diff.median:+.0f} µs [{diff.low:+.0f}–{diff.high:+.0f}]"


def _section(title: str) -> None:
    print()
    print(f"## {title}")


def _print_slow(slow: SlowMatch) -> None:
    _section("Match over 10 ms")
    print(
        f"- raw {slow.raw.median / 1000:.1f} ms "
        f"[{slow.raw.low / 1000:.1f}–{slow.raw.high / 1000:.1f}]"
    )
    print(f"- noop extra {_extra_us(slow.noop_extra)}")
    print(f"- sdk extra {_extra_us(slow.sdk_extra)}")


def _print_fast_notes(rows: dict[str, Row], bare: Sample, keyword_gap: Sample) -> None:
    short = rows["compiled search, 9 B"]
    longer = rows["compiled search, 2 KB"]
    repl = rows["module sub, callable repl"]
    consumed = rows["module finditer, consume"]
    first = rows["module finditer, first match"]
    print()
    print(
        f"- 9 B: wrapper {_delta(short.noop, short.raw)}, histogram {_delta(short.sdk, short.noop)}"
    )
    print(f"- wrapper: 9 B {_delta(short.noop, short.raw)}, 2 KB {_delta(longer.noop, longer.raw)}")
    every = rows["compiled search, 9 B, floor 0"]
    print(
        "- histogram at default floor: "
        f"callable repl {_delta(repl.sdk, repl.noop)}, "
        f"finditer consumed {_delta(consumed.sdk, consumed.noop)}, "
        f"finditer first {_delta(first.sdk, first.noop)} "
        f"(9 B {_delta(short.sdk, short.noop)})"
    )
    print(
        f"- floor 0, 9 B: wrapper {_delta(every.noop, every.raw)}, histogram {_delta(every.sdk, every.noop)}"
    )
    print(f"- per match: {_per_match_line(rows)}")
    gap = f"{keyword_gap.median:+.2f} µs [{keyword_gap.low:+.2f}–{keyword_gap.high:+.2f}]"
    if not _resolved(keyword_gap):
        gap = f"{gap}, not distinct"
    print(f"- keyword − positional: {gap}")
    bare_gap = bare.median - short.noop.median
    if _overlap(bare, short.noop) or abs(bare_gap) < _NOTICE_US:
        bare_vs = "same as 9 B noop"
    else:
        bare_vs = f"{bare_gap:+.2f} vs 9 B noop"
    print(f"- no providers: {_cell(bare)} µs, {bare_vs}")
    compiled = rows["module compile, cache hit"]
    meter_gap = compiled.sdk.median - compiled.noop.median
    meter = f"{meter_gap:+.2f} µs"
    if _overlap(compiled.sdk, compiled.noop) or abs(meter_gap) < _NOTICE_US:
        meter = f"{meter}, not separate"
    print(f"- compile cache hit: wrapper {_delta(compiled.noop, compiled.raw)}, sdk − noop {meter}")


def _per_match(many: Row, few: Row, few_matches: int) -> tuple[float, float]:
    """Wrapper and engine µs per extra match, from the many-match and short rows."""
    many_added = many.noop.median - many.raw.median
    few_added = few.noop.median - few.raw.median
    extra = _MANY - few_matches
    return (many_added - few_added) / extra, (many.raw.median - few.raw.median) / extra


def _per_match_line(rows: dict[str, Row]) -> str:
    finditer, finditer_engine = _per_match(
        rows[f"module finditer, {_MANY:,} matches"], rows["module finditer, consume"], 5
    )
    repl, repl_engine = _per_match(
        rows[f"module sub, callable repl, {_MANY:,} matches"], rows["module sub, callable repl"], 3
    )
    return (
        f"finditer wrapper {finditer:.3f} µs, engine {finditer_engine:.3f} µs; "
        f"callable repl wrapper {repl:.3f} µs, engine {repl_engine:.3f} µs"
    )


def _finditer_many() -> None:
    list(re.finditer(r"\d", _MANY_TEXT))


def _sub_many() -> None:
    re.sub(r"\d", lambda _match: "N", _MANY_TEXT)


def _finditer_first() -> None:
    # Dropping the iterator queues its telemetry (refcounting runs the finalizer
    # here); the next sample's finditer records it. That is the path real code takes.
    next(re.finditer(r"\d", _FINDITER), None)


def _finditer_consume() -> None:
    list(re.finditer(r"\d", _FINDITER))


def _compile_hit() -> None:
    re.compile(r"\d+")


def _compile_held(inst: Any) -> Row:
    """``compile`` while the caller keeps the pattern, so the existing proxy is returned."""

    def factory() -> Callable[[], None]:
        kept = re.compile(r"\d+")
        if re.compile(r"\d+") is not kept:
            raise RuntimeError("compile did not return the held proxy")

        def run(_kept: Any = kept) -> None:
            re.compile(r"\d+")

        return run

    raw_s, noop_s, sdk_s = _three(inst, _compile_hit, factory)
    return Row("module compile, cache hit", raw_s, noop_s, sdk_s)


def _batch_provider() -> TracerProvider:
    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(
            _Discard(),
            max_queue_size=100_000,
            schedule_delay_millis=10_000,
            max_export_batch_size=512,
        )
    )
    return provider


def _telemetry(inst: ReInstrumentor, text: str, sdk_search: Sample) -> Row:
    proxy = _compiled(
        inst,
        "span every call, proxy tracer",
        r"\d+",
        text,
        span_threshold_ms=0,
    )
    provider = _batch_provider()
    try:
        batch = _compiled(
            inst,
            "span every call, batch processor",
            r"\d+",
            text,
            span_threshold_ms=0,
            tracer_provider=provider,
        )
    finally:
        provider.shutdown()

    parent_provider = TracerProvider()
    parent_provider.add_span_processor(SimpleSpanProcessor(_Discard()))
    parent_tracer = parent_provider.get_tracer("bench")
    meter = MeterProvider(metric_readers=[InMemoryMetricReader()])
    try:
        _on(inst, span_threshold_ms=10, histogram_floor_ms=0, meter_provider=meter)
        pattern = re.compile(r"\d+")

        def search() -> None:
            pattern.search(text)

        with parent_tracer.start_as_current_span("request") as request:
            sampled = request.get_span_context().trace_flags.sampled
            parent = _sample(search)
    finally:
        _off(inst)
        meter.shutdown()
        parent_provider.shutdown()

    _section("Telemetry")
    _print_table([proxy, batch])
    if sampled:
        gap = parent.median - sdk_search.median
        print(f"- parent sampled, floor 0: {_cell(parent)} µs, {gap:+.2f} vs 9 B floor 0 sdk")
    else:
        print(f"- parent not sampled: {_cell(parent)} µs")
    return batch


def _engine(module_name: str, instrumentor: Any, *, module_level: bool = False) -> Row | None:
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        if not module_level:
            print(f"- {module_name}: not installed")
        return None
    inst = instrumentor()
    text = "abc123xyz"
    if module_level:

        def raw() -> None:
            module.search(r"\d+", text)

        def factory() -> Callable[[], None]:
            return raw

        label = f"{module_name} module search, 9 B"
    else:
        raw_pattern = module.compile(r"\d+")

        def raw() -> None:
            raw_pattern.search(text)

        def factory() -> Callable[[], None]:
            compiled = module.compile(r"\d+")

            def run() -> None:
                compiled.search(text)

            return run

        label = f"{module_name} compiled search, 9 B"

    raw_s, noop_s, sdk_s = _three(inst, raw, factory, span_threshold_ms=10)
    return Row(label, raw_s, noop_s, sdk_s)


def _rate(fn: Callable[[], None], threads: int, calls_each: int) -> float:
    go = threading.Event()

    def worker() -> None:
        go.wait()
        for _ in range(calls_each):
            fn()

    workers = [threading.Thread(target=worker) for _ in range(threads)]
    for worker_thread in workers:
        worker_thread.start()
    started = time.perf_counter()
    go.set()
    for worker_thread in workers:
        worker_thread.join()
    elapsed = time.perf_counter() - started
    return threads * calls_each / elapsed


def _windows(fn: Callable[[], None], sample: Sample, threads: int) -> Sample:
    each = max(1, int(0.25 / (sample.median / 1_000_000)) // threads)
    return _pack([_rate(fn, threads, each) for _ in range(_WINDOWS)])


def _rate_cell(sample: Sample) -> str:
    return f"{sample.median:,.0f} [{sample.low:,.0f}–{sample.high:,.0f}]"


def _shape(one: Sample, four: Sample) -> str:
    """How the 4-thread windows sit against the 1-thread windows."""
    if one.median <= 0:
        return "unknown"
    relative = four.median / one.median
    # A tight raw timer can refuse to overlap on a 2% shift. That is not
    # parallelism. "above" / "below" require the medians to actually move.
    if relative < 0.90:
        if four.high < one.low:
            return "below"
        return "lower"
    if relative > 1.25 and four.low > one.high:
        return "above"
    if relative > 1.05:
        return "higher"
    return "flat"


def _throughput_label(
    raw: dict[int, Sample], noop: dict[int, Sample], sdk: dict[int, Sample]
) -> str:
    raw_shape = _shape(raw[1], raw[4])
    noop_shape = _shape(noop[1], noop[4])
    sdk_shape = _shape(sdk[1], sdk[4])
    if raw_shape == "above":
        return "raw scaled"
    if noop_shape == "flat" and sdk_shape == "below":
        return "histogram below; wrapper flat"
    if noop_shape == "flat" and sdk_shape == "flat":
        return "wrapper flat; histogram flat"
    if noop_shape == "below" and sdk_shape == "below":
        return "wrapper and histogram below"
    if noop_shape == "flat" and sdk_shape == "lower":
        return "histogram lower, windows overlap; wrapper flat"
    return "4 threads did not multiply"


def _throughput(inst: ReInstrumentor, text: str) -> tuple[Sample, Sample]:
    raw_pattern = re.compile(r"\d+")

    def raw() -> None:
        raw_pattern.search(text)

    _off(inst)
    raw_sample = _sample(raw)
    raw_rates = {threads: _windows(raw, raw_sample, threads) for threads in (1, 4)}

    _on(inst, span_threshold_ms=10, meter_provider=NoOpMeterProvider())
    try:
        pattern = re.compile(r"\d+")

        def noop_fn() -> None:
            pattern.search(text)

        noop_sample = _sample(noop_fn)
        noop_rates = {threads: _windows(noop_fn, noop_sample, threads) for threads in (1, 4)}
    finally:
        _off(inst)

    meter = MeterProvider(metric_readers=[InMemoryMetricReader()])
    _on(inst, span_threshold_ms=10, meter_provider=meter)
    try:
        pattern = re.compile(r"\d+")

        def sdk_fn() -> None:
            pattern.search(text)

        sdk_sample = _sample(sdk_fn)
        sdk_rates = {threads: _windows(sdk_fn, sdk_sample, threads) for threads in (1, 4)}
    finally:
        _off(inst)
        meter.shutdown()

    meter = MeterProvider(metric_readers=[InMemoryMetricReader()])
    _on(inst, span_threshold_ms=10, histogram_floor_ms=0, meter_provider=meter)
    try:
        pattern = re.compile(r"\d+")

        def every_fn() -> None:
            pattern.search(text)

        every_sample = _sample(every_fn)
        every_rates = {threads: _windows(every_fn, every_sample, threads) for threads in (1, 4)}
    finally:
        _off(inst)
        meter.shutdown()

    _section("Throughput")
    print(f"calls/s, {_WINDOWS} windows, median [min–max]")
    for threads in (1, 4):
        print(
            f"- {threads} thread(s): "
            f"raw {_rate_cell(raw_rates[threads])}  "
            f"noop {_rate_cell(noop_rates[threads])}  "
            f"sdk {_rate_cell(sdk_rates[threads])}  "
            f"sdk floor 0 {_rate_cell(every_rates[threads])}"
        )
    print(f"- {_throughput_label(raw_rates, noop_rates, sdk_rates)}")
    print(f"- floor 0: {_throughput_label(raw_rates, noop_rates, every_rates)}")
    return raw_rates[1], sdk_rates[1]


def _warmup(fn: Callable[[], None]) -> None:
    for _ in range(50):
        fn()
    gc.collect()


def _retained(fn: Callable[[], None], calls: int) -> int:
    _warmup(fn)
    before = sys.getallocatedblocks()
    for _ in range(calls):
        fn()
    gc.collect()
    return sys.getallocatedblocks() - before


def _retention(inst: ReInstrumentor, text: str) -> None:
    calls = 2_000
    meter = MeterProvider(metric_readers=[InMemoryMetricReader()])
    _on(inst, span_threshold_ms=10, histogram_floor_ms=0, meter_provider=meter)
    try:
        pattern = re.compile(r"\d+")
        histogram_blocks = _retained(lambda: pattern.search(text), calls)
    finally:
        _off(inst)
        meter.shutdown()

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    _on(
        inst,
        span_threshold_ms=0,
        tracer_provider=provider,
        meter_provider=NoOpMeterProvider(),
    )
    try:
        pattern = re.compile(r"\d+")

        def search() -> None:
            pattern.search(text)

        # Warmup spans would sit in the exporter and inflate the kept count.
        _warmup(search)
        exporter.clear()
        before = sys.getallocatedblocks()
        for _ in range(calls):
            search()
        gc.collect()
        span_blocks = sys.getallocatedblocks() - before
        kept = len(exporter.get_finished_spans())
    finally:
        _off(inst)
        provider.shutdown()
    _section("Retained")
    print(f"after gc, {calls} calls")
    print(f"- histogram, floor 0: {histogram_blocks:+d} blocks")
    print(f"- spans: {span_blocks:+d} blocks, {kept} kept")


def _above_empty(sample: Sample, empty: Sample) -> float:
    return max(0.0, sample.median - empty.median)


def _pieces(raw: Sample, wrapped: Sample) -> None:
    histogram = create_duration_histogram(create_meter(NoOpMeterProvider()))
    meter = MeterProvider(metric_readers=[InMemoryMetricReader()])
    sdk_histogram = create_duration_histogram(create_meter(meter))
    attributes = {"re.operation": "search", "re.library.name": "re"}
    empty = _sample(lambda: None)
    clocks = _sample(lambda: capture_start())
    enabled = _sample(lambda: is_instrumentation_enabled())
    recording = _sample(lambda: _RECORDING.get())
    noop_record = _sample(lambda: histogram.record(1e-6, attributes))
    try:
        sdk_record = _sample(lambda: sdk_histogram.record(1e-6, attributes))
    finally:
        meter.shutdown()
    pieces = (
        ("empty call", empty),
        ("two clocks", clocks),
        ("instrumentation flag", enabled),
        ("re-entry contextvar", recording),
        ("noop histogram", noop_record),
        ("sdk histogram", sdk_record),
    )
    width = max(len(name) for name, _piece in pieces)
    _section("Pieces")
    print("µs, median [min–max]")
    for name, sample in pieces:
        print(f"- {name:<{width}}  {_cell(sample)}")
    accounted = sum(_above_empty(sample, empty) for sample in (clocks, enabled, recording))
    wrapper = wrapped.median - raw.median
    # Smaller than this is the noise of subtracting separate loops, not a proxy cost.
    rest = wrapper - accounted
    tail = f"remainder {rest:.2f} µs" if rest > 0.05 else "no remainder"
    print(f"- 9 B wrapper {wrapper:.2f} µs; named pieces {accounted:.2f} µs; {tail}")


def _print_snapshot(
    rows: dict[str, Row],
    batch: Row,
    engine_rows: list[Row],
    raw_rate: Sample,
    sdk_rate: Sample,
) -> None:
    cases = (
        rows["compiled search, 9 B"],
        rows["compiled search, 2 KB"],
        rows["compiled search, 9 B, floor 0"],
        rows["module finditer, consume"],
        rows[f"module finditer, {_MANY:,} matches"],
        rows["module compile, cache hit"],
        rows["module compile, new proxy"],
        *engine_rows,
        batch,
    )
    _section("Snapshot")
    print("Paste this block into BENCHMARKS.md. It is this machine only.")
    print(_platform_line())
    print(f"cpu: {_cpu()}")
    print(f"commit: {_commit()}")
    print()
    print("| case | wrapper µs | histogram µs |")
    print("| --- | --- | --- |")
    for row in cases:
        print(f"| {row.label} | {_delta(row.noop, row.raw)} | {_delta(row.sdk, row.noop)} |")
    print(f"per match: {_per_match_line(rows)}")
    print(
        "throughput, 1 thread, short-string compiled search, default floor, calls/s: "
        f"raw {_rate_cell(raw_rate)}  sdk {_rate_cell(sdk_rate)}"
    )


def _cpu() -> str:
    if sys.platform.startswith("linux"):
        try:
            with pathlib.Path("/proc/cpuinfo").open(encoding="utf-8") as handle:
                for line in handle:
                    if line.lower().startswith("model name"):
                        name = line.split(":", 1)[1].strip()
                        return name or "unknown"
        except OSError:
            return "unknown"
        return "unknown"
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return "unknown"
        name = completed.stdout.strip()
        return name or "unknown"
    name = platform.processor()
    return name or "unknown"


def _commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    name = completed.stdout.strip()
    if completed.returncode != 0 or not name:
        return "unknown"
    return name


def _platform_line() -> str:
    return (
        f"python {platform.python_version()} {platform.machine()} {platform.system()}  "
        f"opentelemetry-sdk {version('opentelemetry-sdk')}"
    )


def _stamp() -> None:
    print(_platform_line())
    print(f"cpu: {_cpu()}")
    print(f"commit: {_commit()}")
    print(
        f"{_REPEATS}×~{_TARGET_NS / 1_000_000:.0f} ms, median [min–max] µs/call. "
        "wrapper = noop − raw. histogram = sdk − noop."
    )


def main() -> None:
    short = "abc123xyz"
    longer = ("abc-" * 400) + "123"
    inst = ReInstrumentor()
    _off(inst)
    _stamp()
    rows = [
        _compiled(inst, "compiled search, 9 B", r"\d+", short),
        _compiled(inst, "compiled search, 2 KB", r"\d+", longer),
        _compiled(inst, "compiled search, 9 B, floor 0", r"\d+", short, histogram_floor_ms=0),
        _compiled(inst, "compiled search, keyword", r"\d+", short, keyword=True),
        _callable(inst, "module search, 9 B", lambda: re.search(r"\d+", short)),
        _callable(inst, "module sub, string repl", lambda: re.sub(r"\d", "N", short)),
        _callable(
            inst,
            "module sub, callable repl",
            lambda: re.sub(r"\d", lambda _match: "N", short),
        ),
        _callable(inst, f"module sub, callable repl, {_MANY:,} matches", _sub_many),
        _callable(inst, "module finditer, consume", _finditer_consume),
        _callable(inst, f"module finditer, {_MANY:,} matches", _finditer_many),
        _callable(inst, "module finditer, first match", _finditer_first),
        _compile_held(inst),
        _callable(inst, "module compile, new proxy", _compile_hit),
    ]
    _section("Hot path")
    _print_table(rows)
    _on(inst, span_threshold_ms=10)
    try:
        pattern = re.compile(r"\d+")
        bare = _sample(lambda: pattern.search(short))
    finally:
        _off(inst)
    found = {row.label: row for row in rows}
    _print_fast_notes(found, bare, _keyword_gap(inst, short))
    _print_slow(_slow_match(inst, _over_threshold_text()))
    batch = _telemetry(inst, short, found["compiled search, 9 B, floor 0"].sdk)
    _section("Other engines")
    engine_rows = [
        row
        for row in (
            _engine("regex", RegexInstrumentor),
            _engine("re2", GoogleRe2Instrumentor),
            _engine("re2", GoogleRe2Instrumentor, module_level=True),
        )
        if row is not None
    ]
    if engine_rows:
        _print_table(engine_rows)
    raw_rate, sdk_rate = _throughput(inst, short)
    _retention(inst, short)
    _pieces(found["compiled search, 9 B"].raw, found["compiled search, 9 B"].noop)
    re2_module = [row for row in engine_rows if row.label == "re2 module search, 9 B"]
    _print_snapshot(found, batch, re2_module, raw_rate, sdk_rate)


if __name__ == "__main__":
    main()
