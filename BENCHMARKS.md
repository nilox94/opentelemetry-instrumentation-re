# Benchmarks

## Published snapshot

The published figures are one run of the Benchmark workflow on `ubuntu-24.04`, CPython 3.12. Before a pull request that changes the hot path is merged, add the `benchmark` label to it. Paste that job's `## Snapshot` block below, including the `python`, `cpu`, and `commit` lines, and push it to the same pull request. The run on the release tag repeats the measurement as a check. Do not paste a laptop run. Another machine can differ by about 2×.

<!-- snapshot -->
No snapshot yet.

How to read the snapshot:

- `compiled search, 9 B` is the cost of a fast call at the default settings. Nothing is recorded, so this is the wrapper alone.
- `compiled search, 9 B, floor 0` is the same call with `histogram_floor_ms=0`, which records the histogram on every call.
- `per match` is the extra cost of each match for `finditer` and for `sub` with a callable replacement.
- `span every call, batch processor` is the cost of `span_threshold_ms=0`.
- `throughput` is calls per second for one thread at the default settings.

## Run

From the repo root. The SDK is required. `regex` and `google-re2` are optional; a missing engine is skipped.

```bash
uv sync --extra test --extra regex --extra google-re2
uv run python benchmarks/bench.py
```

The first lines are the Python version, the machine, the `opentelemetry-sdk` version, and the commit. A run takes under a minute. pyperf is not used, and CI does not gate on these numbers.

`instrument()` is outside the timer. Each table cell is five repeats. The loop count is chosen so one repeat is about 40 ms, after a warmup. The cell is the median and the min–max of those five, in microseconds per call. Rows are measured one after another, not interleaved, so a difference of a few hundredths of a microsecond between rows is noise.

## Columns

| Column | What it is |
|---|---|
| `raw` | The same call with instrumentation off. |
| `noop` | Instrumented, with `NoOpMeterProvider` and the default thresholds. |
| `sdk` | Instrumented, with an SDK `MeterProvider` whose `InMemoryMetricReader` never collects, so export is not included. |
| `wrapper` | `noop − raw`. The cost of this library. |
| `histogram` | `sdk − noop`. The cost of `Histogram.record` in the SDK. |

At the default `histogram_floor_ms` (100 µs), a fast call records no histogram point, so `histogram` is `within spread` on every fast row. That is the intended result, not a measurement failure. The `floor 0` row shows what `record()` costs when every call records.

`within spread` means the two ranges overlap. That cell is not a measured difference.

## Hot path

| Row | Call |
|---|---|
| `compiled search, 9 B` | `pattern.search` on `abc123xyz`. |
| `compiled search, 2 KB` | Same call on `("abc-" * 400) + "123"` (1,603 characters). The wrapper should not grow with the string. |
| `compiled search, 9 B, floor 0` | The 9-byte search with `histogram_floor_ms=0`. |
| `compiled search, keyword` | `pattern.search(text, pos=0)`. |
| `module search, 9 B` | `re.search(r"\d+", text)` on every call, including the stdlib's compile cache lookup. |
| `module sub, string repl` | `re.sub` with a string replacement. |
| `module sub, callable repl` | `re.sub` with a lambda (3 matches). |
| `module sub, callable repl, 1,000 matches` | The same on `"a1" * 1000`. |
| `module finditer, consume` | `list(finditer)` on `1a2b3c4d5e` (5 matches). |
| `module finditer, 1,000 matches` | `list(finditer)` on `"a1" * 1000`. |
| `module finditer, first match` | One `next`, then `close()`. `close()` records inside the timed call; a dropped iterator would record later, in whichever sample ran the garbage collector. |
| `module compile, cache hit` | `re.compile(r"\d+")` with a warm cache. `compile()` records nothing; `wrapper` is the proxy and the patched function. |

The bullets under the table:

- `9 B` and `wrapper` repeat the fast-call wrapper at two string sizes.
- `histogram at default floor` should be `within spread` everywhere.
- `floor 0, 9 B` is the wrapper and the histogram when every call records. The wrapper is higher than at the default floor because the recording path runs.
- `per match` is `(wrapper on 1,000 matches − wrapper on the short row) / (1,000 − short matches)`, for `finditer` and for callable `sub`.
- `keyword − positional` alternates the two calls in one run. `not distinct` means the gap is within its own spread.
- `no providers` is `instrument()` without a meter provider. `same as 9 B noop` means no global `MeterProvider` is set.

## Match over 10 ms

Paired single calls, not 40 ms batches, because the scan itself varies by more than the wrapper. The haystack is `"a" * n`, searched for `z`, with `n` grown until the raw search takes at least 12 ms. The call crosses the default span threshold, so the instrumented call builds a span. No tracer provider is set, so the span is not recorded.

## Telemetry

- `span every call, proxy tracer`: `span_threshold_ms=0` with no tracer provider. The cost of building a span that is not recorded.
- `span every call, batch processor`: the same with an SDK tracer and a `BatchSpanProcessor` whose exporter discards the batch. The timed call enqueues the span and does not wait for export. Use this row for the cost of a span on every call.
- `parent sampled, floor 0`: the 9-byte search with `histogram_floor_ms=0` inside a sampled, recording span. The gap against the `floor 0` row is the exemplar the SDK attaches to each histogram point.

## Other engines

`regex` and `re2` each have one row: compiled `search` on the 9-byte string. A module-level `google-re2` call is not measured.

## Throughput

Calls per second for the process, at 1 thread and at 4, over three windows of about 0.25 s each. `raw` uses a pattern compiled before `instrument()`; the other columns use patterns compiled after. While the GIL is held, more threads do not raise the totals.

`sdk` is the default floor. `sdk floor 0` records every call. The SDK takes a lock on every `record()`, so with every call recording, 4 threads can be slower than 1.

The label lines compare 4 threads with 1:

| Label | Meaning |
|---|---|
| `raw scaled` | 4-thread raw is above 1.25× the 1-thread rate, so some work ran in parallel. |
| `histogram below; wrapper flat` | The no-op wrapper stays within 0.90×–1.05×, and every SDK window is below every 1-thread SDK window: lock contention in `record()`. |
| `wrapper flat; histogram flat` | Both stay within 0.90×–1.05×. |
| `wrapper and histogram below` | Both drop and the windows do not overlap. |
| `histogram lower, windows overlap; wrapper flat` | The SDK median drops below 0.90×, but the windows overlap. |
| `4 threads did not multiply` | None of the above. |

## Retained after GC

2,000 calls after a warmup and a collection. `histogram, floor 0` is memory blocks still allocated with every call recording; `record()` allocates per call, but a small number means nothing is kept. `spans` is `span_threshold_ms=0` with a `SimpleSpanProcessor` and an in-memory exporter, which keeps every span; the kept count should be 2,000.

## Pieces of the fast path

Separate loops, each including the loop's own Python call (`empty call`).

| Line | What is timed |
|---|---|
| `two clocks` | `time.time_ns` and `time.perf_counter_ns`, taken on every call. |
| `instrumentation flag` | `is_instrumentation_enabled()`. |
| `re-entry contextvar` | The flag that marks this package's own recording. |
| `noop histogram` | `Histogram.record` on a no-op instrument. Not on the default fast path. |
| `sdk histogram` | `Histogram.record` into the SDK. Should be close to the `floor 0` row's `histogram`. |

The last line subtracts `empty call` from the first three and compares the sum with the 9-byte `wrapper`. The `remainder` is the proxy and the Python around the call.

## Not measured

- Periodic metric export, and network export of spans. The batch row stops at the queue.
- `capture_pattern`, which is off by default.
- A failing match, or a span that includes the pattern text.
- Methods on patterns compiled before `instrument()`, which are not instrumented.
- A module-level `google-re2` call.
- More than one core, unless the throughput label is `raw scaled`.
