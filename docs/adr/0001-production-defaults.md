# ADR 0001: Production defaults

Status: accepted
Date: 2026-10-21, revised 2026-11-02

## Span on error

- A span is emitted only when duration >= `span_threshold_ms`, including when the call raises.
- A raising call increments `re.operation.errors` once, with `re.operation`, `re.library.name`, and `error.type`.
- `error.type` is `<module>.error` for the backend's pattern error (`re.error`, `regex.error`, `re2.error`). Other exceptions use the class name, module-qualified unless builtin.
- The duration histogram does not carry `error.type`.
- No `record_exception`. Status description stays empty. `capture_pattern` does not put the message on the span.
- No rate limit. No extra config flag. `span_threshold_ms=0` still spans every call and still omits the message.

Why:

- google-re2's error string contains the pattern.
- A caught `re.error` or `TypeError` is one span per call, and the caller sets the rate.
- The threshold already limits spans. A counter fits a frequent event with a closed attribute set.
- `error.type` on the histogram splits the series, and fast errors pull the distribution down.
- `type(exc).__name__` is `error` on Python 3.12 and `PatternError` from 3.13, and google-re2's class is `Error`. A dashboard would break on an interpreter upgrade.

## Histogram floor

- Record the histogram only when duration >= `histogram_floor_ms`, default 0.1 (100 µs). `0` records every call.
- The error counter ignores the floor.
- One setting. No separate on/off flag.
- Advisory buckets start at 250 µs, above the default floor, and run to 2.5 s.
- The count is slow calls, not call volume. The docs say so.

Why:

- `Histogram.record` was about half the per-call cost (about 1.2 µs of 2.5 µs), and the SDK lock on every record made 4 threads slower than 1.
- Nearly every call landed in the first bucket. The histogram is for slow and catastrophic patterns.
- The duration must be measured to compare it with the floor, so the clocks and the wrapper stay. Only `record()` is skipped.
- An off switch would save only `record()` on calls already slower than the floor.
- 100 µs is two to three orders of magnitude above a typical call and well below the span threshold. The histogram covers 100 µs to 10 ms, which spans do not.

## Telemetry failures

- When recording fails, log one warning per `instrument()` and drop later warnings.
- Log with the re-entry flag set.

Why:

- A failing span processor logged a traceback on every regex call.
- A log handler that uses regex re-entered the instrumentation, failed again, and raised `RecursionError` from the application's call.

## google-re2 keywords

- Pass keywords through unchanged. `string=` raises `TypeError`, as it does without instrumentation.

Why:

- Accepting `string=` only while instrumented makes code that works in production fail when instrumentation is turned off.

## In-place patch

- Set `__code__` to the wrapper before clearing `__defaults__` and `__kwdefaults__`. On restore, put the defaults back before restoring `__code__`.
- Never delete `_otel_re_fn_*` from the target module. The next `instrument()` overwrites the name.
- No lock.

Why:

- Each assignment is atomic under the GIL. The previous order ran the original code with no defaults, or ran the wrapper after the global was removed (`TypeError`, `NameError`).
- The wrapper returns the original function once `recorder.active` is false, which happens before restore.

## Pickle

- `__reduce_ex__` returns the backend pattern's own reduction tuple, unchanged.
- No reduction: raise `pickle.PicklingError`. Do not register a reducer in this package.
- The loaded object is the backend pattern, not a proxy. Its methods are not traced.

Why:

- A reducer in this package makes the pickle import it, and a rename breaks every stored pickle.
- google-re2 `Options` round-trip only when that tuple is not rebuilt here.

## finditer finalizer

- The `weakref.finalize` callback for an abandoned iterator only appends its finish to a process-wide `deque(maxlen=1024)`. No lock, no logging, no telemetry. When the deque is full, the oldest entry is dropped.
- The queue is drained by an instrumented call that is about to record (`_record_fast` after the quiet check) or that takes the general path (`_execute`: `finditer`, a callable `sub` / `subn`, a module function given a compiled pattern). Never while this thread is recording.
- `atexit = False`. Nothing is drained at shutdown.
- `compile()` builds a proxy outside the proxy-cache lock and takes the lock only to insert it. Lookups take no lock.

Why:

- The garbage collector runs finalizers at arbitrary points, including while this package, the SDK, or the application holds a non-reentrant lock. Recording runs span processors, meters, and log handlers, which can take those locks or call `re` again.
- Confirmed deadlock: a GC pass inside proxy creation, under the proxy-cache lock, recorded an abandoned iterator. A span processor's `on_end` called `re.compile`, and the thread blocked on the lock it held. The older check (drop the point while this thread records) only covered `Histogram.record`.
- The quiet fast path does not drain, so its cost does not change. The price is that an abandoned iterator's point can arrive late, or never if no recording call follows, and is lost beyond 1,024 pending.
- Shutdown runs atexit finalizers after the meter provider can already be shut down.

## finditer iterator methods

- The wrapper has `close()` and `throw()` only when the engine's iterator has them: google-re2's generator. Not for `re` (`callable_iterator`) or `regex` (`Scanner`).
- `throw()` forwards the caller's arguments unchanged. If it raises, the iteration is finished without an error.

Why:

- Methods that exist only while instrumented make code that works in production fail with instrumentation off. Same principle as the google-re2 keywords decision.
- An exception the caller injects is not engine time and not an engine error.
- The three-argument `throw()` form warns from Python 3.12, so the wrapper does not add arguments.

## Published cost

- Quote added microseconds: `wrapper` and `histogram`. The README gives the arithmetic from microseconds to CPU share, because the ratio against a short match is what users pay.
- The published number is one Benchmark workflow run: `ubuntu-24.04`, CPython 3.12. It runs when a pull request gets the `benchmark` label, and on tags `v*`. The pull-request run is pasted before merge so the release's README and `BENCHMARKS.md` agree. The tag run is a check. Not a Python-version matrix.
- Do not paste a laptop run into `BENCHMARKS.md`. Another machine can differ by about 2×.
- The quoted rows are compiled search at two sizes (the addend should not move), compiled search with `histogram_floor_ms=0`, `finditer` with 5 and 1,000 matches, `compile()` with the pattern kept (`module compile, cache hit`) and dropped (`module compile, new proxy`), a google-re2 module call (`re2 module search, 9 B`), a span on every call with a batch processor, and the cost per match for the wrapper next to the engine's.

Why:

- The addend is flat from a 9-byte search to a 2 KB search. The short-match ratio is that addend over a near-zero raw time.
- Hardware moves the number more than CPython 3.10 versus 3.13. A per-PR threshold flakes.

## Unsampled parent

- Do not read the current span on the fast path. Do not skip the clocks, the histogram, or the error counter when that span is unsampled or non-recording. Reconsidered with the histogram floor; still declined.
- No config flag for that skip.
- `suppress_instrumentation()` stays the opt-out. It already returns before the clocks.

Why:

- A fast call does not start a span, so there is no discarded span to avoid.
- The SDK sampler drops a child when the parent was dropped. The histogram is the signal that remains.
- Skipping it would keep a head sampler's fraction of observations and hide a slow regex on the requests that were not sampled.
- The check is a context read on every call, including the default `parentbased_always_on` sampler, which samples every span.
- It must read the sampled flag, not `is_recording()`: a propagated remote parent is non-recording but sampled. Calls with no parent cannot be skipped. With tail sampling, every head decision is "sampled" and nothing is saved.
- With the floor, the fast path no longer records, so the saving would be the clocks and the instrumentation check, about 0.3 µs.
- The wrapper runs before any check. Suppressing instrumentation removes the clocks and the histogram. It does not remove the wrapper.

## Declined

- No `opentelemetry_instrumentor` entry point.
- Do not merge the fast and slow call paths.
- Do not clear basedpyright findings below `--level error`.
- Do not split `capture_start` so the fast path skips the epoch clock. That is not the sampler cost.
