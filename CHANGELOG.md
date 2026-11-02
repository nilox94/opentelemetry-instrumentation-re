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
- **`finditer` iterator methods:** the wrapper has the engine iterator's methods. `re` and `regex` iterators have no `close()` or `throw()`; google-re2's generator wrapper has both and forwards them. An exception passed to `throw()` is not counted as a regex error.
- **Abandoned `finditer` iterators:** recorded by a later instrumented call, not by the garbage collector. Up to 1,024 results wait in a queue; beyond that the oldest is dropped.
- **`capture_pattern_max_len=0`** omits `re.pattern` instead of recording an empty string.
- **Requirements:** `opentelemetry-api ~= 1.30`. The advisory histogram buckets need it; with 1.28 or 1.29, `instrument()` raised `TypeError`. `typing-extensions` is required only on Python < 3.12.

### Added

- `histogram_floor_ms` / `OTEL_PYTHON_RE_HISTOGRAM_FLOOR_MS`.
- `benchmarks/bench.py`, a hot-path benchmark (`uv run python benchmarks/bench.py`). It reports the wrapper, the in-process histogram, the cost per match, a recording span, and per-process throughput, with min and max. How to read it is in [BENCHMARKS.md](BENCHMARKS.md). The Benchmark workflow runs on pull requests labelled `benchmark` and on release tags.
- Benchmark rows `module compile, cache hit` (the caller keeps the pattern), `module compile, new proxy` (the caller drops it), and `re2 module search, 9 B`. The per-match line reports the engine's cost per match next to the wrapper's.
- README section on cost: what each call pays, including `compile()` and google-re2 module functions, and how to turn microseconds into CPU share.
- README section on calls that never finish, and how to bound them so they are recorded.
- Decisions are recorded in `docs/adr/0001-production-defaults.md`.

### Fixed

- A failing span processor or meter logs one warning per `instrument()`, not a traceback on every regex call. A log handler that uses regex no longer re-enters the instrumentation and raises `RecursionError` from the application's call.
- A garbage-collector pass no longer records telemetry. Recording an abandoned `finditer` iterator from its finalizer could deadlock: a span processor that called `re.compile` re-entered the proxy cache while the same thread held its lock. Proxies are also created outside that lock now.
- `from re import search` (and the same for `regex` and `google-re2`) taken before `instrument()` is traced. The function object is patched in place and restored by `uninstrument()`.
- `finditer` duration is time inside `next` (and google-re2's `close` and `throw`), not idle time or time until garbage collection.
- `sub` / `subn` duration excludes the replacement callable. An exception from that callable is not a regex error.
- A pattern method called from a `google-re2` `sub` replacement is recorded. The module-level call is still recorded once.
- Pickling a `google-re2` pattern keeps `Options`.
- Invalid `OTEL_PYTHON_RE_*` values log a warning and fall back to the default.
- Suppress instrumentation while emitting telemetry, not around the regex call, so a `sub` replacement callable does not turn off other instrumentation.
- A failure while recording telemetry no longer replaces a successful match or hides the original exception.
- `compile()` of a compiled pattern returns the existing proxy instead of nesting wrappers. Proxies handed out earlier record again after `uninstrument()` / `instrument()`.
- `capture_pattern="false"` (and `"no"` / `"off"` / `"0"`) stays off. Non-finite or negative `span_threshold_ms` and `histogram_floor_ms`, and negative `capture_pattern_max_len`, are rejected.
- google-re2 `finditer` iterators finish telemetry on `throw()`, and when `close()` raises. A `throw()` the generator swallows does not end the span. `throw()` forwards only the arguments it was given, so it no longer triggers Python 3.12's warning about the three-argument form.
- Suppress instrumentation during span and metric export to avoid feedback loops with the OTel SDK (stdlib `re` inside exporters/propagators).
- CI: Test redistribute installs the built wheel with the `regex` and `google-re2` extras. It used the removed `instruments` extra, so those engines' tests were skipped. The lowest-direct Test cells on Python 3.12 to 3.14 run again, with every extra except `google-re2`, whose lowest version does not build there.
- Versioning: `pyproject.toml` and `version.py` stay at the last tag, `1.0.1`. The Prepare release workflow computes the next version from conventional commits (a `feat` commit gives `1.1.0`).

Note: git tags `v1.0.0` and `v1.0.1` were never published to PyPI; the only published wheel is `0.1.0`. For PyPI users the next release is a new major version, which is why it can include the breaking changes above.

## v1.0.1 (2026-02-19)

### Bug Fixes

- Publish to PyPI always ([#3](https://github.com/nilox94/opentelemetry-instrumentation-re/pull/3),
  [`01dcb0e`](https://github.com/nilox94/opentelemetry-instrumentation-re/commit/01dcb0e2468e432f6f33122b060f00bf7d2cec3b))


## v1.0.0 (2026-02-19)

- Initial Release
