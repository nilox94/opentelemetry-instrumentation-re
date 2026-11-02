# CHANGELOG

<!-- version list -->

## Unreleased

### Changed

- **Breaking vs the published 0.1.0 wheel:** a call no longer emits a span every time, and pattern text is no longer recorded unless `capture_pattern` is enabled.
- **Manual instrumentation only:** removed `opentelemetry_instrumentor` entry points and the `instruments` / `all` extras.
- **Telemetry:** the histogram is recorded only for calls at or above `histogram_floor_ms` (default 100 µs; `0` records every call), so its count is slow calls, not call volume. Spans are emitted only when duration crosses `span_threshold_ms` (default 10 ms). Every raising call increments `re.operation.errors`; fast errors do not emit a span. The exception message is not recorded.
- **Histogram buckets:** advisory boundaries run from 250 µs to 2.5 s.
- **`error.type`:** `re.error`, `regex.error`, or `re2.error` for an invalid pattern, on every Python version. Other exceptions use the class name, module-qualified unless builtin.
- **Privacy:** `re.pattern` is off by default; use `capture_pattern=True` to opt in (truncated to 256 chars by default).
- **Wrapping:** `compile()` returns a `wrapt.ObjectProxy` that preserves `isinstance(..., Pattern)` and module-level `re.search(compiled, text)`.
- **Calling convention:** keyword arguments (`string=`, `pattern=`) work; missing-argument errors match the stdlib. On `google-re2`, `string=` raises `TypeError`, as it does without instrumentation.
- **`finditer`:** span/metric cover iteration, not construction only.

### Added

- `histogram_floor_ms` / `OTEL_PYTHON_RE_HISTOGRAM_FLOOR_MS`.
- `benchmarks/bench.py`, a hot-path benchmark (`uv run python benchmarks/bench.py`). It reports the wrapper, the in-process histogram, the cost per match, a recording span, and per-process throughput, with min and max. How to read it is in [BENCHMARKS.md](BENCHMARKS.md). The Benchmark workflow runs on pull requests labelled `benchmark` and on release tags.
- README section on cost: what each call pays, and how to turn microseconds into CPU share.
- Decisions are recorded in `docs/adr/0001-production-defaults.md`.

### Fixed

- A failing span processor or meter logs one warning per `instrument()`, not a traceback on every regex call. A log handler that uses regex no longer re-enters the instrumentation and raises `RecursionError` from the application's call.
- An abandoned `finditer` iterator collected while telemetry is being recorded no longer records from inside `Histogram.record`, which could deadlock on the SDK's lock.
- `from re import search` (and the same for `regex` and `google-re2`) taken before `instrument()` is traced. The function object is patched in place and restored by `uninstrument()`.
- `finditer` duration is time inside `next`, `close`, and `throw`, not idle time or time until garbage collection.
- `sub` / `subn` duration excludes the replacement callable. An exception from that callable is not a regex error.
- A pattern method called from a `google-re2` `sub` replacement is recorded. The module-level call is still recorded once.
- Pickling a `google-re2` pattern keeps `Options`.
- Invalid `OTEL_PYTHON_RE_*` values log a warning and fall back to the default.
- Suppress instrumentation while emitting telemetry, not around the regex call, so a `sub` replacement callable does not turn off other instrumentation.
- A failure while recording telemetry no longer replaces a successful match or hides the original exception.
- `compile()` of a compiled pattern returns the existing proxy instead of nesting wrappers. Proxies handed out earlier record again after `uninstrument()` / `instrument()`.
- `capture_pattern="false"` (and `"no"` / `"off"` / `"0"`) stays off. Non-finite or negative `span_threshold_ms` and `histogram_floor_ms`, and negative `capture_pattern_max_len`, are rejected.
- `finditer` iterators finish telemetry on `throw()`, and when `close()` raises. A `throw()` the inner iterator swallows does not end the span.
- Suppress instrumentation during span and metric export to avoid feedback loops with the OTel SDK (stdlib `re` inside exporters/propagators).
- Version source of truth: `pyproject.toml` and `version.py` both track the published version.

Note: git tags `v1.0.x` preceded PyPI; the last published wheel was `0.1.0`.

## v1.0.1 (2026-02-19)

### Bug Fixes

- Publish to PyPI always ([#3](https://github.com/nilox94/opentelemetry-instrumentation-re/pull/3),
  [`01dcb0e`](https://github.com/nilox94/opentelemetry-instrumentation-re/commit/01dcb0e2468e432f6f33122b060f00bf7d2cec3b))


## v1.0.0 (2026-02-19)

- Initial Release
