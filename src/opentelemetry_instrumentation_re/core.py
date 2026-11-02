"""Core instrumentation logic for re-like modules (patch helpers, wrappers)."""

from __future__ import annotations

import copy
import copyreg
import inspect
import logging
import pickle
import sys
import threading
import types
import weakref
from collections import deque
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, SupportsIndex, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

import wrapt
from opentelemetry import context as context_api
from opentelemetry.instrumentation.utils import is_instrumentation_enabled

from .recorder import (
    OperationRecorder,
    capture_start,
    make_result_attrs_fn,
    result_match_count,
    string_length,
)
from .utils.pattern import unwrap_pattern

# Module object, not a from-import: tests replace recorder.monotonic_ns and the
# hot path must see that. Importing the name from the package (__init__) cycles.
_package = __package__
if _package is None:
    raise RuntimeError("core must be imported as part of opentelemetry_instrumentation_re")
recorder_mod: Any = sys.modules[_package + ".recorder"]

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter, Histogram
    from opentelemetry.trace import Tracer

    from .config import InstrumentationConfig

_log = logging.getLogger(__name__)

_R = TypeVar("_R")

_SUB_SUBN = ("sub", "subn")

# google-re2 module functions are ``compile(...).method(...)``. Consume exactly
# one method recording for that inner call. A boolean held for the whole call
# also hid pattern methods invoked from a ``sub`` replacement.
_SKIP_DEPTH: ContextVar[int] = ContextVar("otel_re_skip_method_depth", default=0)

_FUNCTIONS = (
    "search",
    "match",
    "fullmatch",
    "split",
    "finditer",
    "findall",
    "sub",
    "subn",
)

_MODULE_FUNCTIONS = _FUNCTIONS
_MODULE_NAMES = (*_MODULE_FUNCTIONS, "compile")

# Injected into the target function's globals. One per operation so the patched
# code object does not branch on the operation name.
_ENTRY_PREFIX = "_otel_re_fn_"


class BackendProfile:
    """Calling convention that does not change from one call to the next.

    Baked into each module's wrappers so the hot path does not inspect signatures.
    """

    __slots__ = (
        "haystack_keyword",
        "library_name",
        "module_name",
        "skip_one_method",
    )

    def __init__(
        self,
        module_name: str,
        library_name: str,
        haystack_keyword: str,
        *,
        skip_one_method: bool,
    ) -> None:
        self.module_name = module_name
        self.library_name = library_name
        self.haystack_keyword = haystack_keyword
        self.skip_one_method = skip_one_method


_PROFILES = {
    "re": BackendProfile("re", "re", "string", skip_one_method=False),
    "regex": BackendProfile("regex", "regex", "string", skip_one_method=False),
    "re2": BackendProfile("re2", "google_re2", "text", skip_one_method=True),
}


class _ProxyCache:
    """Map compiled patterns to proxies without retaining them.

    A strong value in ``WeakKeyDictionary`` would cycle: the proxy holds the
    pattern, so every ``compile`` would live until uninstrument. google-re2's
    ``_Regexp`` cannot be a weak key at all; keying a normal dict by ``id``
    would leak those for the process lifetime. Values stay weak in both maps.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._weak: weakref.WeakKeyDictionary[Any, weakref.ref[Any]] = weakref.WeakKeyDictionary()
        self._by_id: weakref.WeakValueDictionary[int, Any] = weakref.WeakValueDictionary()

    def get_or_create(self, compiled: Any, factory: Callable[[Any], Any]) -> Any:
        """Return the proxy for ``compiled``. Concurrent misses keep the first one stored."""
        with self._lock:
            existing = self._get(compiled)
        if existing is not None:
            return existing
        # Outside the lock: the factory runs Python code, and anything it calls
        # back into (a span processor, a log handler) may compile a pattern.
        proxy = factory(compiled)
        with self._lock:
            existing = self._get(compiled)
            if existing is not None:
                return existing
            self._set(compiled, proxy)
        return proxy

    def _get(self, compiled: Any) -> Any | None:
        try:
            ref = self._weak.get(compiled)
        except TypeError:
            return self._by_id.get(id(compiled))
        if ref is None:
            return None
        proxy = ref()
        if proxy is None:
            self._weak.pop(compiled, None)
            return None
        return proxy

    def _set(self, compiled: Any, proxy: Any) -> None:
        try:
            self._weak[compiled] = weakref.ref(proxy)
        except TypeError:
            self._by_id[id(compiled)] = proxy


class _FnPatch:
    """In-place ``__code__`` swap so existing ``from module import fn`` bindings update."""

    __slots__ = (
        "added_signature",
        "code",
        "defaults",
        "entry_name",
        "fn",
        "globals_dict",
        "kwdefaults",
    )

    def __init__(
        self,
        fn: types.FunctionType,
        code: types.CodeType,
        defaults: tuple[Any, ...] | None,
        kwdefaults: dict[str, Any] | None,
        added_signature: bool,
        globals_dict: dict[str, Any],
        entry_name: str,
    ) -> None:
        self.fn = fn
        self.code = code
        self.defaults = defaults
        self.kwdefaults = kwdefaults
        self.added_signature = added_signature
        self.globals_dict = globals_dict
        self.entry_name = entry_name

    def restore(self) -> None:
        # Order is load-bearing. See docs/adr/0001-production-defaults.md.
        self.fn.__defaults__ = self.defaults
        self.fn.__kwdefaults__ = self.kwdefaults
        self.fn.__code__ = self.code
        if self.added_signature:
            self.fn.__dict__.pop("__signature__", None)
        self.fn.__dict__.pop("_otel_re_patched", None)


_MODULE_STATE: dict[int, tuple[OperationRecorder, _ProxyCache, list[_FnPatch]]] = {}
# Kept across uninstrument so a later instrument() reuses compile identity.
_PROXY_CACHES: dict[int, _ProxyCache] = {}
_LIVE_PROXIES: dict[int, weakref.WeakSet[Any]] = {}
_LIVE_LOCK = threading.Lock()


def _register_proxy(module_key: int, proxy: Any) -> None:
    with _LIVE_LOCK:
        bucket = _LIVE_PROXIES.get(module_key)
        if bucket is None:
            bucket = weakref.WeakSet()
            _LIVE_PROXIES[module_key] = bucket
        bucket.add(proxy)


def _retarget_proxies(module_key: int, recorder: OperationRecorder) -> None:
    """Point proxies handed out earlier at ``recorder``."""
    with _LIVE_LOCK:
        bucket = _LIVE_PROXIES.get(module_key)
        proxies = list(bucket) if bucket is not None else []
    for proxy in proxies:
        proxy._self_recorder = recorder


def _profile(recorder: OperationRecorder) -> BackendProfile:
    profile = recorder.profile
    if not isinstance(profile, BackendProfile):
        raise RuntimeError("regex recorder has no backend profile")
    return profile


def _subject(
    profile: BackendProfile, args: tuple[Any, ...], kwargs: dict[str, Any], index: int
) -> Any:
    key = profile.haystack_keyword
    if key in kwargs:
        return kwargs[key]
    if len(args) > index:
        return args[index]
    return None


def _module_pattern_arg(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any | None:
    if "pattern" in kwargs:
        return kwargs["pattern"]
    if args:
        return args[0]
    return None


def _unwrap_module_args(
    args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if not args and "pattern" not in kwargs:
        return args, kwargs
    new_args = list(args)
    if new_args:
        new_args[0] = unwrap_pattern(new_args[0])
    if "pattern" not in kwargs:
        return tuple(new_args), kwargs
    new_kwargs = dict(kwargs)
    new_kwargs["pattern"] = unwrap_pattern(new_kwargs["pattern"])
    return tuple(new_args), new_kwargs


class _ReplClock:
    """Time spent inside a ``sub``/``subn`` replacement, excluded from regex duration."""

    __slots__ = ("elapsed_ns", "error", "repl")

    def __init__(self, repl: Callable[..., Any]) -> None:
        self.repl = repl
        self.elapsed_ns = 0
        self.error: BaseException | None = None

    def __call__(self, match: Any) -> Any:
        started = recorder_mod.monotonic_ns()
        try:
            return self.repl(match)
        except BaseException as exc:
            self.error = exc
            raise
        finally:
            self.elapsed_ns += recorder_mod.monotonic_ns() - started


def _wrap_repl(
    name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    repl_index: int | None,
) -> tuple[tuple[Any, ...], dict[str, Any], _ReplClock | None]:
    if name not in _SUB_SUBN:
        return args, kwargs, None
    if "repl" in kwargs and callable(kwargs["repl"]):
        clock = _ReplClock(kwargs["repl"])
        copied = dict(kwargs)
        copied["repl"] = clock
        return args, copied, clock
    if repl_index is None or len(args) <= repl_index:
        return args, kwargs, None
    repl = args[repl_index]
    if not callable(repl):
        return args, kwargs, None
    clock = _ReplClock(repl)
    mutated = list(args)
    mutated[repl_index] = clock
    return tuple(mutated), kwargs, clock


# Finishes of abandoned finditer iterators, recorded at the next drain point.
# The garbage collector runs finalizers at arbitrary points, including while
# this package, the SDK, or the application holds a non-reentrant lock, so the
# finalizer itself only appends. Full: the oldest entry is dropped.
_PENDING_MAX = 1024
_PENDING_FINISHES: deque[Callable[[BaseException | None], None]] = deque(maxlen=_PENDING_MAX)


def _on_iterator_collected(finish: Callable[[BaseException | None], None]) -> None:
    """Finalize callback. Must not be a bound method: that would keep the iterator alive."""
    _PENDING_FINISHES.append(finish)


def _drain_pending() -> None:
    """Record queued finishes. Call only where recording inline is already allowed."""
    while True:
        try:
            finish = _PENDING_FINISHES.popleft()
        except IndexError:
            return
        finish(None)


class _TracedIterator:
    """Iterator wrapper. Duration is construction plus time spent inside ``next``."""

    def __init__(
        self,
        iterator: Iterator[Any],
        *,
        bucket: list[int],
        finish: Callable[[BaseException | None], None],
    ) -> None:
        self._iterator = iterator
        self._bucket = bucket
        self._finish = finish
        self._done = False
        self._finalizer = weakref.finalize(self, _on_iterator_collected, finish)
        self._finalizer.atexit = False

    def _add(self, started: int) -> None:
        self._bucket[0] += recorder_mod.monotonic_ns() - started

    def _complete(self, exc: BaseException | None) -> None:
        if self._done:
            return
        self._done = True
        self._finalizer.detach()
        self._finish(exc)

    def __iter__(self) -> _TracedIterator:
        return self

    def __next__(self) -> Any:
        started = recorder_mod.monotonic_ns()
        try:
            value = next(self._iterator)
        except StopIteration:
            self._add(started)
            self._complete(None)
            raise
        except BaseException as exc:
            self._add(started)
            self._complete(exc)
            raise
        self._add(started)
        return value


class _TracedGenerator(_TracedIterator):
    """Wrapper for a generator (google-re2). ``close``/``throw`` exist only when the inner has them."""

    def close(self) -> None:
        generator: Any = self._iterator
        if self._done:
            generator.close()
            return
        started = recorder_mod.monotonic_ns()
        try:
            generator.close()
        except BaseException as exc:
            self._add(started)
            self._complete(exc)
            raise
        self._add(started)
        self._complete(None)

    def throw(self, *args: Any) -> Any:
        generator: Any = self._iterator
        started = recorder_mod.monotonic_ns()
        try:
            # Forward the caller's arity: the three-argument form warns from 3.12.
            # A swallowed throw resumes iteration, so telemetry stays open.
            value = generator.throw(*args)
        except BaseException:
            self._add(started)
            # The caller injected the exception; the engine did not fail.
            self._complete(None)
            raise
        self._add(started)
        return value


def _report_failure(recorder: OperationRecorder, message: str) -> None:
    """Log the current exception once per ``instrument()``.

    The re-entry flag is set so a log handler that uses regex is not recorded,
    and cannot fail again and recurse.
    """
    if recorder.failure_logged:
        return
    recorder.failure_logged = True
    token = recorder_mod._RECORDING.set(True)
    try:
        _log.warning("%s; later failures are not logged", message, exc_info=True)
    finally:
        recorder_mod._RECORDING.reset(token)


def _safe_record(recorder: OperationRecorder, **kwargs: Any) -> None:
    try:
        recorder.record_finished(**kwargs)
    except Exception:
        _report_failure(recorder, "failed to record regex telemetry")


def _engine_elapsed(started_mono: int, repl_timer: _ReplClock | None) -> int:
    elapsed = recorder_mod.monotonic_ns() - started_mono
    if repl_timer is not None:
        elapsed -= repl_timer.elapsed_ns
    if elapsed < 0:
        return 0
    return elapsed


def _regex_exc(exc: BaseException, repl_timer: _ReplClock | None) -> BaseException | None:
    """Replacement failures are the callable's, not a regex-engine error."""
    if repl_timer is not None and repl_timer.error is exc:
        return None
    return exc


def _consume_skip(call: Callable[[], _R]) -> _R:
    """Skip this method call and leave depth 0 for code it invokes (a replacement)."""
    token = _SKIP_DEPTH.set(_SKIP_DEPTH.get() - 1)
    try:
        return call()
    finally:
        _SKIP_DEPTH.reset(token)


def _invoke(profile: BackendProfile, from_method: bool, call: Callable[[], _R]) -> _R:
    if from_method or not profile.skip_one_method:
        return call()
    token = _SKIP_DEPTH.set(_SKIP_DEPTH.get() + 1)
    try:
        return call()
    finally:
        _SKIP_DEPTH.reset(token)


def _execute(
    recorder: OperationRecorder,
    operation: str,
    pattern_source: Any,
    subject: Any | None,
    call: Callable[[], _R],
    *,
    from_method: bool = False,
    repl_timer: _ReplClock | None = None,
) -> _R:
    profile = _profile(recorder)
    if recorder_mod._RECORDING.get() or not is_instrumentation_enabled() or not recorder.active:
        return call()
    if from_method and profile.skip_one_method and _SKIP_DEPTH.get():
        return _consume_skip(call)
    if _PENDING_FINISHES:
        _drain_pending()

    start_epoch, start_mono = capture_start()
    parent_context = context_api.get_current()
    result_attrs_fn = make_result_attrs_fn(operation)
    subj_len = string_length(subject)

    def record(exc: BaseException | None, elapsed_ns: int) -> None:
        _safe_record(
            recorder,
            operation=operation,
            start_ns=start_epoch,
            end_ns=start_epoch + elapsed_ns,
            parent_context=parent_context,
            pattern_source=pattern_source,
            string_length=subj_len,
            exc=exc,
            result_attributes=None,
        )

    if operation == "finditer":
        try:
            raw_iterator = _invoke(profile, from_method, call)
        except BaseException as exc:
            record(_regex_exc(exc, repl_timer), _engine_elapsed(start_mono, repl_timer))
            raise
        # Mutable cell so the finalizer can read engine time without holding the iterator.
        bucket = [_engine_elapsed(start_mono, repl_timer)]
        finished = False

        def finish(exc_inner: BaseException | None) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            record(exc_inner, bucket[0])

        wrapper = _TracedGenerator if hasattr(raw_iterator, "throw") else _TracedIterator
        return cast(
            "_R",
            wrapper(cast("Iterator[Any]", raw_iterator), bucket=bucket, finish=finish),
        )

    try:
        result = _invoke(profile, from_method, call)
    except BaseException as exc:
        record(_regex_exc(exc, repl_timer), _engine_elapsed(start_mono, repl_timer))
        raise

    result_attributes = None
    try:
        result_attributes = result_attrs_fn(result)
    except Exception:
        _report_failure(recorder, "failed to read regex result attributes")
    _safe_record(
        recorder,
        operation=operation,
        start_ns=start_epoch,
        end_ns=start_epoch + _engine_elapsed(start_mono, repl_timer),
        parent_context=parent_context,
        pattern_source=pattern_source,
        string_length=subj_len,
        exc=None,
        result_attributes=result_attributes,
    )
    return result


class _TracedPattern(wrapt.ObjectProxy):
    """Proxy around a compiled pattern; traced methods delegate to the inner pattern."""

    def __init__(self, pattern: Any, recorder: OperationRecorder) -> None:
        self._self_recorder = recorder
        super().__init__(pattern)
        _register_proxy(recorder._module_key, self)

    def __repr__(self) -> str:
        return repr(self.__wrapped__)

    def __reduce_ex__(self, protocol: SupportsIndex) -> tuple[Any, ...]:
        inner = self.__wrapped__
        reduced = _pattern_reduction(inner, protocol)
        if reduced is None:
            raise pickle.PicklingError(
                f"cannot pickle {type(inner).__name__} without its own reducer"
            )
        return reduced

    def __copy__(self) -> Any:
        inner = copy.copy(self.__wrapped__)
        if inner is self.__wrapped__:
            return self
        return type(self)(inner, self._self_recorder)

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        prior = memo.get(id(self))
        if prior is not None:
            return prior
        # Register before copying the inner pattern so a cycle returns this instance.
        result = type(self).__new__(type(self))
        memo[id(self)] = result
        inner = copy.deepcopy(self.__wrapped__, memo)
        type(self).__init__(result, inner, self._self_recorder)
        return result

    def _traced_method(self, name: str, *args: Any, **kwargs: Any) -> Any:
        profile = _profile(self._self_recorder)
        index = 1 if name in _SUB_SUBN else 0
        subject = _subject(profile, args, kwargs, index)
        # Bound methods take the replacement first. Module calls take it second.
        args, kwargs, repl_timer = _wrap_repl(name, args, kwargs, 0 if name in _SUB_SUBN else None)
        original = getattr(self.__wrapped__, name)

        def call() -> Any:
            return original(*args, **kwargs)

        return _execute(
            self._self_recorder,
            name,
            self,
            subject,
            call,
            from_method=True,
            repl_timer=repl_timer,
        )

    def search(self, *args: Any, **kwargs: Any) -> Any:
        return _fast_method(self, "search", args, kwargs)

    def match(self, *args: Any, **kwargs: Any) -> Any:
        return _fast_method(self, "match", args, kwargs)

    def fullmatch(self, *args: Any, **kwargs: Any) -> Any:
        return _fast_method(self, "fullmatch", args, kwargs)

    def split(self, *args: Any, **kwargs: Any) -> Any:
        return _fast_method(self, "split", args, kwargs)

    def finditer(self, *args: Any, **kwargs: Any) -> Any:
        return self._traced_method("finditer", *args, **kwargs)

    def findall(self, *args: Any, **kwargs: Any) -> Any:
        return _fast_method(self, "findall", args, kwargs)

    def sub(self, *args: Any, **kwargs: Any) -> Any:
        if _repl_is_callable(args, kwargs, 0):
            return self._traced_method("sub", *args, **kwargs)
        return _fast_method(self, "sub", args, kwargs)

    def subn(self, *args: Any, **kwargs: Any) -> Any:
        if _repl_is_callable(args, kwargs, 0):
            return self._traced_method("subn", *args, **kwargs)
        return _fast_method(self, "subn", args, kwargs)


def _suppressed(recorder: OperationRecorder) -> bool:
    return bool(
        recorder_mod._RECORDING.get() or not recorder.active or not is_instrumentation_enabled()
    )


def _repl_is_callable(args: tuple[Any, ...], kwargs: dict[str, Any], index: int) -> bool:
    if "repl" in kwargs:
        return callable(kwargs["repl"])
    return len(args) > index and callable(args[index])


def _haystack(
    recorder: OperationRecorder,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    index: int,
) -> Any:
    if kwargs:
        key = recorder.haystack_keyword
        if key in kwargs:
            return kwargs[key]
    if len(args) > index:
        return args[index]
    return None


def _pattern_source(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if args:
        return args[0]
    if kwargs:
        return kwargs.get("pattern")
    return None


def _module_can_skip_unwrap(name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
    """Positional or keyword call whose pattern is text, so the engine can see it as-is.

    A compiled pattern (including a proxy) still goes through the general path,
    which unwraps it. ``finditer`` and a callable replacement also stay there:
    their duration is not the wall time of one C call.
    """
    if name == "finditer":
        return False
    if name in _SUB_SUBN and _repl_is_callable(args, kwargs, 1):
        return False
    return isinstance(_pattern_source(args, kwargs), (str, bytes))


def _record_fast(
    recorder: OperationRecorder,
    operation: str,
    pattern_source: Any,
    subject: Any,
    start_epoch: int,
    start_mono: int,
    exc: BaseException | None,
    result: Any,
) -> None:
    elapsed = recorder_mod.monotonic_ns() - start_mono
    if elapsed < 0:
        elapsed = 0
    if exc is None and elapsed < recorder.quiet_below_ns:
        return
    if _PENDING_FINISHES:
        _drain_pending()
    result_attributes = None
    if exc is None and operation in ("findall", "subn"):
        try:
            result_attributes = result_match_count(operation, result)
        except Exception:
            _report_failure(recorder, "failed to read regex result attributes")
    _safe_record(
        recorder,
        operation=operation,
        start_ns=start_epoch,
        end_ns=start_epoch + elapsed,
        parent_context=None,
        pattern_source=pattern_source,
        string_length=string_length(subject),
        exc=exc,
        result_attributes=result_attributes,
    )


def _invoke_original(
    original: Callable[..., _R], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> _R:
    if kwargs:
        return original(*args, **kwargs)
    return original(*args)


def _timed_original(
    recorder: OperationRecorder,
    operation: str,
    pattern_source: Any,
    subject: Any,
    original: Callable[..., _R],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> _R:
    start_epoch, start_mono = capture_start()
    try:
        result = original(*args, **kwargs) if kwargs else original(*args)
    except BaseException as exc:
        _record_fast(
            recorder, operation, pattern_source, subject, start_epoch, start_mono, exc, None
        )
        raise
    _record_fast(
        recorder, operation, pattern_source, subject, start_epoch, start_mono, None, result
    )
    return result


def _fast_method(
    proxy: _TracedPattern,
    name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    """Search-like method call. No user Python runs inside the engine."""
    recorder = proxy._self_recorder
    original = getattr(proxy.__wrapped__, name)
    if _suppressed(recorder):
        return _invoke_original(original, args, kwargs)
    # google-re2 module functions are compile().method(). That one inner call
    # is already recorded by the module wrapper.
    if recorder.skip_one_method and _SKIP_DEPTH.get():
        token = _SKIP_DEPTH.set(_SKIP_DEPTH.get() - 1)
        try:
            return _invoke_original(original, args, kwargs)
        finally:
            _SKIP_DEPTH.reset(token)
    index = 1 if name in _SUB_SUBN else 0
    return _timed_original(
        recorder,
        name,
        proxy,
        _haystack(recorder, args, kwargs, index),
        original,
        args,
        kwargs,
    )


def _fast_module(
    recorder: OperationRecorder,
    name: str,
    original: Callable[..., _R],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> _R:
    if _suppressed(recorder):
        return _invoke_original(original, args, kwargs)
    index = 2 if name in _SUB_SUBN else 1
    subject = _haystack(recorder, args, kwargs, index)
    pattern = _pattern_source(args, kwargs)
    if recorder.skip_one_method:
        token = _SKIP_DEPTH.set(_SKIP_DEPTH.get() + 1)
        try:
            return _timed_original(recorder, name, pattern, subject, original, args, kwargs)
        finally:
            _SKIP_DEPTH.reset(token)
    return _timed_original(recorder, name, pattern, subject, original, args, kwargs)


def _make_module_wrapper(
    recorder: OperationRecorder,
    name: str,
    original: Callable[..., _R],
) -> Callable[[tuple[Any, ...], dict[str, Any]], _R]:
    """Entry stored on the target module and called by the patched ``__code__``."""
    profile = _profile(recorder)
    string_index = 2 if name in _SUB_SUBN else 1
    repl_index = 1 if name in _SUB_SUBN else None

    def entry(args: tuple[Any, ...], kwargs: dict[str, Any]) -> _R:
        if _module_can_skip_unwrap(name, args, kwargs):
            return _fast_module(recorder, name, original, args, kwargs)
        pattern_source = _module_pattern_arg(args, kwargs)
        subject = _subject(profile, args, kwargs, string_index)
        call_args, call_kwargs, repl_timer = _wrap_repl(name, args, kwargs, repl_index)
        call_args, call_kwargs = _unwrap_module_args(call_args, call_kwargs)

        def call() -> _R:
            return original(*call_args, **call_kwargs)

        return _execute(
            recorder,
            name,
            pattern_source,
            subject,
            call,
            repl_timer=repl_timer,
        )

    return entry


def _make_compile_entry(
    recorder: OperationRecorder,
    original_compile: Callable[..., Any],
    proxy_cache: _ProxyCache,
) -> Callable[[tuple[Any, ...], dict[str, Any]], Any]:
    def entry(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        # Backends return an already-compiled pattern unchanged. Unwrap first so
        # that object is the inner pattern, not a proxy we would wrap again.
        args, kwargs = _unwrap_module_args(args, kwargs)
        compiled = original_compile(*args, **kwargs)
        if isinstance(compiled, _TracedPattern):
            return compiled
        return proxy_cache.get_or_create(compiled, lambda inner: _TracedPattern(inner, recorder))

    return entry


def _pattern_reduction(inner: Any, protocol: SupportsIndex) -> tuple[Any, ...] | None:
    """Reduction pickle would use for ``inner``, without going through this proxy."""
    reducer = copyreg.dispatch_table.get(type(inner))
    if reducer is not None:
        try:
            reduced = reducer(inner)
        except Exception:
            reduced = None
        if isinstance(reduced, tuple) and reduced:
            return reduced
    reduce = getattr(inner, "__reduce_ex__", None)
    if reduce is None:
        return None
    try:
        reduced = reduce(protocol)
    except Exception:
        return None
    if isinstance(reduced, tuple) and reduced:
        return reduced
    return None


def _clone_function(fn: types.FunctionType) -> types.FunctionType:
    cloned = types.FunctionType(
        fn.__code__,
        fn.__globals__,
        fn.__name__,
        fn.__defaults__,
        fn.__closure__,
    )
    cloned.__kwdefaults__ = fn.__kwdefaults__
    return cloned


def _entry_code(func_name: str, entry_global: str, qualname: str) -> types.CodeType:
    source = f"def {func_name}(*args, **kwargs):\n    return {entry_global}(args, kwargs)\n"
    namespace: dict[str, Any] = {}
    exec(compile(source, "<opentelemetry_instrumentation_re>", "exec"), {}, namespace)
    code: types.CodeType = namespace[func_name].__code__
    try:
        code = code.replace(co_qualname=qualname)
    except TypeError:
        return code
    return code


def _set_attr(obj: Any, name: str, value: Any) -> None:
    """Assign an attribute the type checker does not declare on ``FunctionType``."""
    setattr(obj, name, value)


def _patch_inplace(
    fn: Any,
    entry: Callable[..., Any],
    patches: list[_FnPatch],
    qualname: str,
) -> None:
    if not isinstance(fn, types.FunctionType):
        raise TypeError(
            f"{qualname} is {type(fn).__name__}, not a Python function; "
            "cannot update names that were already imported"
        )
    if fn.__closure__:
        raise TypeError(f"{qualname} closes over cells; refusing to replace its code")
    if getattr(fn, "_otel_re_patched", False):
        raise RuntimeError(f"{qualname} is already patched")
    entry_name = f"{_ENTRY_PREFIX}{fn.__name__}"
    globals_dict = fn.__globals__
    added_signature = False
    signature: inspect.Signature | None = None
    if "__signature__" not in fn.__dict__:
        try:
            signature = inspect.signature(fn)
            added_signature = True
        except (TypeError, ValueError):
            added_signature = False
    patch = _FnPatch(
        fn,
        fn.__code__,
        fn.__defaults__,
        fn.__kwdefaults__,
        added_signature,
        globals_dict,
        entry_name,
    )
    patches.append(patch)
    try:
        if added_signature and signature is not None:
            _set_attr(fn, "__signature__", signature)
        globals_dict[entry_name] = entry
        # Order is load-bearing. See docs/adr/0001-production-defaults.md.
        fn.__code__ = _entry_code(fn.__name__, entry_name, qualname)
        fn.__defaults__ = None
        fn.__kwdefaults__ = None
        _set_attr(fn, "_otel_re_patched", True)
    except BaseException:
        patch.restore()
        patches.pop()
        raise


def instrument_module(
    module: Any,
    tracer: Tracer,
    histogram: Histogram,
    errors: Counter,
    config: InstrumentationConfig,
    get_pattern_type: Callable[[], type],
    *,
    library_name: str,
) -> None:
    """Patch a re-like module in place, including names imported before this call."""
    _ = get_pattern_type()  # validate backend before any patch
    profile = _PROFILES.get(module.__name__)
    if profile is None or profile.library_name != library_name:
        raise RuntimeError(f"no regex profile for module {module.__name__!r} ({library_name})")
    module_key = id(module)
    recorder = OperationRecorder(
        tracer,
        histogram,
        errors,
        config,
        library_name=library_name,
        module_name=module.__name__,
    )
    recorder.profile = profile
    recorder.skip_one_method = profile.skip_one_method
    recorder.haystack_keyword = profile.haystack_keyword
    pattern_error = getattr(module, "error", None)
    if isinstance(pattern_error, type) and issubclass(pattern_error, BaseException):
        recorder.pattern_error = pattern_error
    recorder._module_key = module_key
    proxy_cache = _PROXY_CACHES.setdefault(module_key, _ProxyCache())
    patches: list[_FnPatch] = []
    _MODULE_STATE[module_key] = (recorder, proxy_cache, patches)
    _retarget_proxies(module_key, recorder)
    try:
        for name in _MODULE_FUNCTIONS:
            fn = getattr(module, name)
            original = _clone_function(fn)
            entry = _make_module_wrapper(recorder, name, original)
            _patch_inplace(fn, entry, patches, f"{module.__name__}.{name}")
        compile_fn = module.compile
        original_compile = _clone_function(compile_fn)
        compile_entry = _make_compile_entry(recorder, original_compile, proxy_cache)
        _patch_inplace(compile_fn, compile_entry, patches, f"{module.__name__}.compile")
    except BaseException:
        uninstrument_module(module)
        raise


def uninstrument_module(module: Any) -> None:
    """Restore original function code. Live proxies stay and follow the next recorder.

    Code is restored on the function objects themselves, so ``from module import search``
    bindings from before ``instrument()`` go back to the original implementation too.
    """
    state = _MODULE_STATE.pop(id(module), None)
    if state is None:
        return
    state[0].active = False
    for patch in reversed(state[2]):
        patch.restore()
