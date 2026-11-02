# OpenTelemetry instrumentation for Python regex libraries

[![Test](https://github.com/nilox94/opentelemetry-instrumentation-re/actions/workflows/test.yml/badge.svg)](https://github.com/nilox94/opentelemetry-instrumentation-re/actions/workflows/test.yml)

This library provides [OpenTelemetry instrumentation](https://opentelemetry.io/docs/concepts/instrumentation/) for three Python regex libraries: the standard library [`re`](https://docs.python.org/3/library/re.html), and the [`regex`](https://pypi.org/project/regex/) and [`google-re2`](https://pypi.org/project/google-re2/) packages.

It is built to find slow regex calls, such as catastrophic backtracking, in production. It records a histogram (`re.operation.duration`) for calls that take at least `histogram_floor_ms` (default 100 µs), a counter (`re.operation.errors`) for every call that raises, and an INTERNAL span for calls that take at least `span_threshold_ms` (default 10 ms). Fast, successful calls record nothing, but every call still pays the wrapper. See [Cost](#cost).

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

`finditer` duration is the time inside `next`, `close`, and `throw`, plus constructing the iterator. Time in your loop between matches is not included. The returned object is an `Iterator`, but not the stdlib `callable_iterator`. Telemetry is recorded on `StopIteration`, `close()`, `throw()`, or when an abandoned iterator is garbage-collected.

`sub` / `subn` duration does not include a replacement callable. An exception raised by that callable is not counted as a regex error.

## Cost

Every call to an instrumented function or pattern method pays for the wrapper, whether or not anything is recorded. The rest depends on the call:

| When | Added work |
|---|---|
| Every call | The wrapper: two clock reads, an instrumentation check, and the proxy or patched function. |
| `finditer`, or `sub` / `subn` with a callable replacement | A clock pair per match, so the cost grows with the number of matches. This keeps your loop body and replacement function out of the regex duration. |
| Duration at or above `histogram_floor_ms` | `Histogram.record`. The OpenTelemetry SDK takes a lock on each record, which limits multi-threaded throughput when every call records. |
| Duration at or above `span_threshold_ms` | A span, plus what your span processor does with it. |
| The call raises | One counter increment. |

Measured figures are in [BENCHMARKS.md](https://github.com/nilox94/opentelemetry-instrumentation-re/blob/main/BENCHMARKS.md): a fast call at the default settings, the same call with `histogram_floor_ms=0`, the cost per match, and a span on every call. They come from one GitHub-hosted Ubuntu run on Python 3.12. Another machine can differ by about 2×, so run `uv run python benchmarks/bench.py` on your deployment hardware.

To estimate CPU, multiply the added microseconds by the number of instrumented calls per second. One microsecond at 100,000 calls per second is a tenth of a CPU core. `ReInstrumentor` sees every stdlib `re` call in the process, including calls from libraries and from OpenTelemetry itself. To measure your call rate, run briefly with `histogram_floor_ms=0` and read the histogram count.

A trace sampler does not reduce this cost. The floor and the span threshold are checked after the call, and a slow call in an unsampled trace still records the histogram. `suppress_instrumentation()` skips the clocks and all telemetry for the calls inside it, but the wrapper still runs.

## Using this safely

- Call `instrument()` from the application at process startup, not from a library. Patching is process-wide for that module.
- Call it before importing libraries that compile patterns at import time. Method calls on a pattern compiled before `instrument()` are not recorded.
- Keep the default floor and threshold unless you have measured the cost. `span_threshold_ms=0` creates a span for every regex call in the process.
- Leave `capture_pattern` off. When enabled, the pattern is truncated to `capture_pattern_max_len` (256 characters by default).
- If recording telemetry fails (for example a span processor raises), the regex result or exception is returned unchanged and one warning is logged per `instrument()`. Later failures are not logged.
- Regex calls made while this package records telemetry are not recorded. That covers a span processor's `on_end`, an exporter called inline by `SimpleSpanProcessor`, and a log handler formatting this package's warning. The OpenTelemetry SDK suppresses instrumentation during export, so its exporters are not recorded either. Other regex calls from OpenTelemetry code, such as parsing trace-context headers, are recorded.

A span is created after the call, with timestamps covering engine time. It is not the current span while the call runs, so work inside a replacement callable or between `finditer` yields is not a child of the regex span.

## Limitations

- Compiled patterns are proxied at `compile()` time. `isinstance(p, re.Pattern)` stays true. `type(p) is re.Pattern` is false while instrumented, and stays false after `uninstrument()` for patterns compiled while instrumented.
- C extensions that check the pattern's type in C (`PyObject_TypeCheck`, PyO3 downcasts) reject the proxy. Pass `p.__wrapped__` to them.
- Patched functions are compiled from `<opentelemetry_instrumentation_re>`, so tracebacks include those frames, `inspect.getsource` on a patched function raises, and a warning emitted with `stacklevel` aimed at the caller of `re` can be attributed to this package.
- `uninstrument()` leaves `_otel_re_fn_<operation>` on the module. A later `instrument()` replaces them.
- `compile(already_compiled)` returns that same proxy when the backend would return the same pattern. `uninstrument()` then `instrument()` keeps the identity and points those proxies at the new configuration. A second `instrument()` without `uninstrument()` is ignored.
- `from re import search` before `instrument()` is traced: the function object is updated in place, and `uninstrument()` restores its code. The same applies to `regex` and `google-re2`.
- google-re2 names the searched text `text`. `string=` raises `TypeError`, as it does without instrumentation.
- Replacement callables for `sub` / `subn` run with other OpenTelemetry instrumentation enabled. Regex calls made from the callable are recorded separately.
- `Match.re` refers to the inner pattern, not the proxy, so `match.re.search(...)` is not traced.
- An abandoned `finditer` iterator is recorded when it is garbage-collected, with the engine time accumulated by then. It is not recorded at interpreter shutdown, or if it is collected on a thread that is already recording telemetry.
- Pickling uses the backend reducer for `re`, `regex`, and `google-re2`. The pickle does not reference this package. The loaded object is not a proxy, so its method calls are not traced.
- Free-threaded CPython builds (3.13t, 3.14t) are not tested. Patching relies on attribute assignment being atomic under the GIL.

## Requirements

- Python >= 3.10
- OpenTelemetry API ~= 1.28, instrumentation ~= 0.49

## License

Apache-2.0
