# OpenTelemetry instrumentation for Python regex libraries

[![Test](https://github.com/nilox94/opentelemetry-instrumentation-re/actions/workflows/test.yml/badge.svg)](https://github.com/nilox94/opentelemetry-instrumentation-re/actions/workflows/test.yml)

This library provides [OpenTelemetry instrumentation](https://opentelemetry.io/docs/concepts/instrumentation/) for three Python regex libraries: the standard library [`re`](https://docs.python.org/3/library/re.html), and the [`regex`](https://pypi.org/project/regex/) and [`google-re2`](https://pypi.org/project/google-re2/) packages.

It is built to find slow regex calls, such as catastrophic backtracking, in production. It records a histogram (`re.operation.duration`) for calls that take at least `histogram_floor_ms` (default 100 µs), a counter (`re.operation.errors`) for every call that raises, and an INTERNAL span for calls that take at least `span_threshold_ms` (default 10 ms). Fast, successful calls record nothing, but every call still pays the wrapper. See [Cost](#cost).

Telemetry is written when a call returns or raises. A call that never finishes records nothing. See [Calls that never finish](#calls-that-never-finish).

Installing the package does not patch `re`. Tracing starts when the application calls `instrument()`.

## Installation

```bash
pip install opentelemetry-instrumentation-re                    # stdlib re
pip install opentelemetry-instrumentation-re[regex]             # regex package
pip install opentelemetry-instrumentation-re[google-re2]        # google-re2 package
```

The stdlib `re` module needs no extra. For `regex`, use `>= 2021.0`. For `google-re2`, use `>= 1.0`.

## Usage

```python
import re
from opentelemetry_instrumentation_re import ReInstrumentor

ReInstrumentor().instrument()
re.search(r"\d+", "hello 42 world")
```

Optional kwargs (or environment variables):

| Kwarg | Env | Default |
|-------|-----|---------|
| `span_threshold_ms` | `OTEL_PYTHON_RE_SPAN_THRESHOLD_MS` | `10` |
| `histogram_floor_ms` | `OTEL_PYTHON_RE_HISTOGRAM_FLOOR_MS` | `0.1` |
| `capture_pattern` | `OTEL_PYTHON_RE_CAPTURE_PATTERN` | `false` |
| `capture_pattern_max_len` | `OTEL_PYTHON_RE_CAPTURE_PATTERN_MAX_LEN` | `256` |
| `tracer_provider` | — | global |
| `meter_provider` | — | global |

`0` for either threshold records every call. Invalid environment values are logged and the default is used. The same bad value passed as a keyword raises `ValueError`.

Use `RegexInstrumentor` or `GoogleRe2Instrumentor` when your code imports those modules. Call `uninstrument()` on the same instrumentor to restore the module.

## Telemetry

- **Histogram** `re.operation.duration` (seconds), for calls at or above `histogram_floor_ms`. Attributes: `re.operation`, `re.library.name`. Its count is the number of slow calls, not the number of regex calls. Advisory buckets run from 250 µs to 2.5 s.
- **Counter** `re.operation.errors`, once per call that raises, at any duration. Attributes: `re.operation`, `re.library.name`, `error.type`. The exception message is not recorded.
- **Span** `{library}.{operation}`, for calls at or above `span_threshold_ms`, including failures. Attributes: `re.operation`, `re.library.name`, `re.string_length`, `re.pattern_length`, and `re.match_count` for `findall` and `subn`. A failed span has status ERROR and `error.type`, with no status description and no exception event.
- `re.pattern` is added to spans only with `capture_pattern=True`. Pattern text can contain secrets.

`error.type` is `re.error`, `regex.error`, or `re2.error` for an invalid pattern, on every Python version (`re.error` is named `PatternError` from 3.13). Other exceptions use the class name, qualified by its module unless it is a builtin (`TypeError`).

The `re.*` attribute names are defined by this package. They are not OpenTelemetry semantic conventions and may change in a later release.

### Example span (`span_threshold_ms=0`, pattern capture off)

```json
{
  "name": "re.search",
  "kind": "INTERNAL",
  "attributes": {
    "re.operation": "search",
    "re.pattern_length": 3,
    "re.string_length": 14,
    "re.library.name": "re"
  }
}
```

## Supported operations

| Operation | Module-level | Compiled pattern |
|-----------|--------------|------------------|
| `search` | ✓ | ✓ |
| `match` | ✓ | ✓ |
| `fullmatch` | ✓ | ✓ |
| `split` | ✓ | ✓ |
| `finditer` | ✓ | ✓ |
| `findall` | ✓ | ✓ |
| `sub` | ✓ | ✓ |
| `subn` | ✓ | ✓ |

Not traced: `escape`, `purge`, and `regex`'s `subf`, `subfn`, and `splititer`. Keyword arguments the engine accepts, such as `regex`'s `timeout=`, are passed through unchanged.

`finditer` duration is the time spent constructing the iterator and inside `next`. Time in your loop between matches is not included. The returned object has the same methods as the engine's iterator, but `type()` is not the engine's type. `re` and `regex` iterators have no `close()` or `throw()`. google-re2 returns a generator, so its wrapper has both and forwards them. Telemetry is recorded on `StopIteration`, on an exception from `next`, or when google-re2's `close()` or `throw()` ends the iteration. An exception you pass to `throw()` is not counted as a regex error. An iterator you abandon is recorded later, not when it is garbage-collected. See [Limitations](#limitations).

`sub` / `subn` duration does not include a replacement callable. An exception raised by that callable is not counted as a regex error.

## Cost

Every call to an instrumented function or pattern method pays for the wrapper, whether or not anything is recorded. The rest depends on the call:

| When | Added work |
|---|---|
| Every call | The wrapper: two clock reads, an instrumentation check, and the proxy or patched function. |
| `compile()` | The patched function and a lookup of the pattern's proxy. `compile()` records nothing. A pattern without a live proxy gets a new one, inserted under a process-wide lock. That happens on the first compile, and every time if the caller drops the pattern after use, as in `re.compile(p).search(s)`. |
| google-re2 module functions | `re2.search(...)` and the other module functions call `compile()` on every call, and google-re2 patterns cannot be weakly referenced, so each call builds a new proxy. Compile the pattern once and call its methods. |
| `finditer`, or `sub` / `subn` with a callable replacement | A clock pair per match, so the cost grows with the number of matches. This keeps your loop body and replacement function out of the regex duration. For a simple pattern this costs more per match than the engine's own matching, so a call with many matches can take more than twice as long as without instrumentation. |
| Duration at or above `histogram_floor_ms` | `Histogram.record`. The OpenTelemetry SDK takes a lock on each record, which limits multi-threaded throughput when every call records. |
| Duration at or above `span_threshold_ms` | A span, plus what your span processor does with it. |
| The call raises | One counter increment. |

Measured figures are in [BENCHMARKS.md](https://github.com/nilox94/opentelemetry-instrumentation-re/blob/main/BENCHMARKS.md): a fast call at the default settings, the same call with `histogram_floor_ms=0`, the cost per match next to the engine's, `compile()` with and without a live proxy, a google-re2 module call, and a span on every call. They come from one GitHub-hosted Ubuntu run on Python 3.12. Another machine can differ by about 2×, so run `uv run python benchmarks/bench.py` on your deployment hardware.

<!-- cost-snapshot -->
From the published run (commit `f47f7f7`), with an SDK meter provider and the default settings:

| Call | Without instrumentation | Instrumented |
|---|---|---|
| Compiled `search` on 9 bytes | 0.13 µs | 1.21 µs |
| `finditer`, 1,000 matches, consumed | 157 µs | 370 µs |
| `sub` with a callable, 1,000 matches | 103 µs | 284 µs |
| `re.compile`, caller keeps the pattern | 0.14 µs | 0.79 µs |
| `re.compile`, caller drops the pattern | 0.13 µs | 2.42 µs |
| google-re2 module-level `search` on 9 bytes | 5.96 µs | 11.62 µs |

With `histogram_floor_ms=0`, the 9-byte search takes 3.96 µs. With `span_threshold_ms=0` and a batch span processor, it takes 16.54 µs. One thread ran 8.1 million short searches per second without instrumentation and 0.85 million with it.

To estimate CPU, multiply the added microseconds by the number of instrumented calls per second. One microsecond at 100,000 calls per second is a tenth of a CPU core. `ReInstrumentor` sees every stdlib `re` call in the process, including calls from libraries and from OpenTelemetry itself. To measure your call rate, run briefly with `histogram_floor_ms=0` and read the histogram count.

A trace sampler does not reduce this cost. The floor and the span threshold are checked after the call, and a slow call in an unsampled trace still records the histogram. `suppress_instrumentation()` skips the clocks and all telemetry for the calls inside it, but the wrapper still runs.

## Using this safely

- Call `instrument()` from the application at process startup, not from a library. Patching is process-wide for that module.
- Call it before importing libraries that compile patterns at import time. Method calls on a pattern compiled before `instrument()` are not recorded.
- Keep the default floor and threshold unless you have measured the cost. `span_threshold_ms=0` creates a span for every regex call in the process.
- Leave `capture_pattern` off. When enabled, the pattern is truncated to `capture_pattern_max_len` (256 characters by default). `capture_pattern_max_len=0` omits `re.pattern`.
- If recording telemetry fails (for example a span processor raises), the regex result or exception is returned unchanged and one warning is logged per `instrument()`. Later failures are not logged.
- Regex calls made while this package records telemetry are not recorded. That covers a span processor's `on_end`, an exporter called inline by `SimpleSpanProcessor`, and a log handler formatting this package's warning. The OpenTelemetry SDK suppresses instrumentation during export, so its exporters are not recorded either. Other regex calls from OpenTelemetry code, such as parsing trace-context headers, are recorded.

A span is created after the call, with timestamps covering engine time. It is not the current span while the call runs, so work inside a replacement callable or between `finditer` yields is not a child of the regex span.

### Calls that never finish

Catastrophic backtracking often does not end on its own. If a request timeout or a supervisor kills the worker first, nothing is recorded: no span, no histogram point, no error count. To see these calls, bound them so they raise:

- `regex` accepts `timeout=` in seconds and raises `TimeoutError`. That is recorded as an error with `error.type` `TimeoutError`, and as a span if the call reached `span_threshold_ms`.
- For stdlib `re` in the main thread, a `SIGALRM` handler (`signal.alarm` or `signal.setitimer`) that raises interrupts a running match. Signals are delivered only to the main thread.
- google-re2 matches in linear time and does not backtrack.

```python
import regex
from opentelemetry_instrumentation_re import RegexInstrumentor

RegexInstrumentor().instrument()
try:
    regex.match(user_pattern, text, timeout=0.5)
except TimeoutError:
    ...  # counted in re.operation.errors with error.type="TimeoutError"
```

## Limitations

- Compiled patterns are proxied at `compile()` time. `isinstance(p, re.Pattern)` stays true. `type(p) is re.Pattern` is false while instrumented, and stays false after `uninstrument()` for patterns compiled while instrumented.
- C extensions that check the pattern's type in C (`PyObject_TypeCheck`, PyO3 downcasts) reject the proxy. Pass `p.__wrapped__` to them.
- Patched functions are compiled from `<opentelemetry_instrumentation_re>`, so tracebacks include those frames and `inspect.getsource` on a patched function raises.
- A warning the engine emits with `stacklevel` aimed at its caller is attributed to `opentelemetry_instrumentation_re/core.py`, not to your code. For example, from Python 3.13, `re.sub(pattern, repl, string, 1)` warns that a positional `count` is deprecated (the same for positional `maxsplit` and `flags`). While instrumented, Python's default filters hide that `DeprecationWarning`, because they show it only for `__main__`. Filters scoped to your module, such as `-W error::DeprecationWarning:myapp`, no longer match. All call sites share one location, so the warning is shown once. Run your tests with instrumentation off, or use a filter without a module (`-W error::DeprecationWarning`).
- `uninstrument()` leaves `_otel_re_fn_<operation>` on the module. A later `instrument()` replaces them.
- `compile(already_compiled)` returns that same proxy when the backend would return the same pattern. `uninstrument()` then `instrument()` keeps the identity and points those proxies at the new configuration. A second `instrument()` without `uninstrument()` is ignored.
- `from re import search` before `instrument()` is traced: the function object is updated in place, and `uninstrument()` restores its code. The same applies to `regex` and `google-re2`.
- google-re2 names the searched text `text`. `string=` raises `TypeError`, as it does without instrumentation.
- Replacement callables for `sub` / `subn` run with other OpenTelemetry instrumentation enabled. Regex calls made from the callable are recorded separately.
- `Match.re` refers to the inner pattern, not the proxy, so `match.re.search(...)` is not traced.
- An abandoned `finditer` iterator is not recorded when it is garbage-collected. The collector can run at any point, including while a lock is held, and recording runs span processors and log handlers. Its result, with the engine time accumulated by then, is queued instead. The next instrumented call on any thread records it, if that call records telemetry or is a `finditer`, a `sub` / `subn` with a callable replacement, or a module function given a compiled pattern. Fast calls that record nothing leave the queue alone, so the point can arrive late, or never. The span keeps its original timestamps and parent. The queue holds 1,024 results; beyond that the oldest is dropped. Nothing is recorded at interpreter shutdown.
- Pickling uses the backend reducer for `re`, `regex`, and `google-re2`. The pickle does not reference this package. The loaded object is not a proxy, so its method calls are not traced.
- Free-threaded CPython builds (3.13t, 3.14t) are not tested. Patching relies on attribute assignment being atomic under the GIL, and proxy lookups rely on dictionary reads being atomic under it.

## Requirements

- Python >= 3.10
- OpenTelemetry API ~= 1.30, instrumentation ~= 0.49. The duration histogram's bucket advisory needs API 1.30.

## License

Apache-2.0


[You have received this identical output 3 times. Re-reading '/Users/nano/Projects/opentelemetry-instrumentation-re/README.md:raw' will not change it — use a narrower selector (path:A-B), or proceed with the edit.]
