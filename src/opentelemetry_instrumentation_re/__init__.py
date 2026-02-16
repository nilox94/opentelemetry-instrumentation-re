"""
OpenTelemetry instrumentation for Python's standard library re (regex) module.

Usage::

    import re
    from opentelemetry_instrumentation_re import ReInstrumentor

    ReInstrumentor().instrument()

    re.search(r"\\d+", "hello 42 world")
    re.compile(r"\\w+").findall("a b c")
"""

from __future__ import annotations

import re
from functools import partial, wraps
from typing import TYPE_CHECKING, Any, Callable, ParamSpec, TypeVar, override

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.sdk.resources import Attributes
from opentelemetry.trace import SpanKind, Tracer, get_tracer

from opentelemetry_instrumentation_re._wrap import (
    RE_FUNCTION,
    RE_MATCH_COUNT,
    RE_PATTERN,
    RE_STRING_LENGTH,
    get_pattern_string,
)
from opentelemetry_instrumentation_re.package import _instruments
from opentelemetry_instrumentation_re.version import __version__

if TYPE_CHECKING:
    from collections.abc import Collection

_P = ParamSpec("_P")
_R = TypeVar("_R")

# For sub/subn the "string" param is the replacement; the searched string is the next positional.
_SUB_SUBN = ("sub", "subn")

def _search_string_for_attrs(name: str, *args: Any) -> str | bytes:
    """
    String to use for re.string_length.
    For sub/subn it's the third positional (args[0]).
    NB: args are sliced to exclude the first positional arg (pattern).
    """
    if name in _SUB_SUBN and args:
        # pattern | repl, (string), ...
        return args[1]
    # pattern | (string), ...
    return args[0]


def _instrument_call(
    tracer: Tracer,
    name: str,
    attributes: Attributes,
    call_original: Callable[[], _R],
    result_attributes: Callable[[_R], dict[str, Any]] | None = None,
) -> _R:
    """Run call_original inside a span, setting attributes. Minimal error handling (SDK sets status)."""
    with tracer.start_as_current_span(
        f"re.{name}",
        kind=SpanKind.INTERNAL,
    ) as span:
        if span.is_recording():
            span.set_attributes(attributes)
        result: _R = call_original()
        if span.is_recording() and result_attributes is not None:
            for key, value in result_attributes(result).items():
                if value is not None:
                    span.set_attribute(key, value)
        return result


def _make_wrapper(
    tracer: Tracer,
    name: str,
    original: Callable[..., _R],
    *,
    get_count: Callable[[_R], int] | None = None,
) -> Callable[..., _R]:
    """Build a single wrapper for re module functions or Pattern methods.

    First argument is always the pattern (module) or self (Pattern); both support
    get_pattern_string() and the same attribute logic.

    Args:
        tracer: The OpenTelemetry Tracer instance.
        name: The function/method name (e.g. "search", "findall").
        original: The original callable to wrap.
        get_count: If set, span attribute re.match_count is set from get_count(result).

    Returns:
        A wrapped callable that creates spans for each call.
    """
    @wraps(original)
    def wrapper(first: Any, *args: Any, **kwargs: Any) -> _R:
        pattern_str = get_pattern_string(first)
        search_str = _search_string_for_attrs(name, *args)

        def get_attrs() -> dict[str, Any]:
            attrs: dict[str, Any] = {
                RE_FUNCTION: name,
                RE_STRING_LENGTH: len(search_str),
                RE_PATTERN: pattern_str,
            }
            return attrs

        def call_original() -> _R:
            return original(first, *args, **kwargs)

        if get_count is not None:
            count_fn = get_count

            def result_attrs(r: _R) -> dict[str, Any]:
                return {RE_MATCH_COUNT: count_fn(r)}

            result_attrs_fn: Callable[[_R], dict[str, Any]] | None = result_attrs
        else:
            result_attrs_fn = None

        return _instrument_call(
            tracer,
            name,
            get_attrs(),
            call_original,
            result_attrs_fn,
        )

    return wrapper


# Module-level functions to instrument
_MODULE_FUNCTIONS = [
    ("search", False),
    ("match", False),
    ("fullmatch", False),
    ("split", False),
    ("finditer", False),
    ("findall", True),  # has match_count
    ("sub", False),
    ("subn", True),  # has match_count
]

# Pattern methods to instrument
_PATTERN_METHODS = [
    ("search", False),
    ("match", False),
    ("fullmatch", False),
    ("split", False),
    ("finditer", False),
    ("findall", True),  # has match_count
    ("sub", False),
    ("subn", True),  # has match_count
]

# Names of re module members we patch (for uninstrument via __wrapped__)
_MODULE_NAMES = [name for name, _ in _MODULE_FUNCTIONS] + ["compile"]


def _get_count_func(name: str) -> Callable[[Any], int]:
    """Get count extraction function for findall/subn operations.

    Args:
        name: Operation name, either "findall" or "subn".

    Returns:
        A function that extracts the match count from the result.
        For "findall", returns len(result).
        For "subn", returns result[1] (the count tuple element).
    """
    if name == "findall":
        return len

    # subn returns (new_string, count)
    def get_subn_count(result: tuple[str, int]) -> int:
        return result[1]

    return get_subn_count


class _PatternWrapper:
    """Wrapper for Pattern instances that instruments method calls.

    This wrapper intercepts method calls on compiled regex Pattern objects
    and creates OpenTelemetry spans for each operation. It maintains the
    original Pattern interface while adding observability.

    Attributes:
        _pattern: The original compiled Pattern instance.
        _tracer: The OpenTelemetry Tracer for creating spans.
        _wrapped_methods: Dictionary mapping method names to wrapped callables.
    """

    def __init__(self, pattern: re.Pattern[str] | re.Pattern[bytes], tracer: Tracer) -> None:
        self._pattern: re.Pattern[str] | re.Pattern[bytes] = pattern
        self._tracer: Tracer = tracer
        self._wrapped_methods: dict[str, Callable[..., Any]] = {}
        self._setup_wrappers()

    def _setup_wrappers(self) -> None:
        """Set up wrapped methods for this instance."""
        for name, has_match_count in _PATTERN_METHODS:
            original = getattr(re.Pattern, name)
            wrapped_unbound = _make_wrapper(
                self._tracer,
                name,
                original,
                get_count=_get_count_func(name) if has_match_count else None,
            )
            self._wrapped_methods[name] = partial(wrapped_unbound, self._pattern)

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to wrapped pattern or wrapped methods."""
        if name in self._wrapped_methods:
            return self._wrapped_methods[name]
        return getattr(self._pattern, name)

    # Delegate common Pattern attributes
    @property
    def pattern(self) -> str | bytes:
        """Return the pattern string."""
        return self._pattern.pattern

    @property
    def flags(self) -> int:
        """Return the flags."""
        return self._pattern.flags

    @property
    def groups(self) -> int:
        """Return the number of groups."""
        return self._pattern.groups

    @property
    def groupindex(self) -> dict[str, int]:
        """Return the group index."""
        return dict(self._pattern.groupindex)  # Convert Mapping to dict


def _make_compile_wrapper(
    tracer: Tracer, original_compile: Callable[..., re.Pattern[str] | re.Pattern[bytes]]
) -> Callable[..., _PatternWrapper]:
    """Wrap re.compile to instrument Pattern instances.

    Args:
        tracer: The OpenTelemetry Tracer instance.
        original_compile: The original re.compile function.

    Returns:
        A wrapped compile function that returns instrumented Pattern instances.
    """
    @wraps(original_compile)
    def wrapper(
        pattern: str | bytes | re.Pattern[str] | re.Pattern[bytes], flags: int = 0
    ) -> _PatternWrapper:
        compiled: re.Pattern[str] | re.Pattern[bytes] = original_compile(pattern, flags)
        return _PatternWrapper(compiled, tracer)

    return wrapper


def _instrument(tracer: Tracer) -> None:
    """Patch re module and Pattern methods.

    This function replaces module-level re functions and re.compile with
    instrumented versions that create OpenTelemetry spans. Wrappers use
    functools.wraps so originals can be restored via __wrapped__.
    """
    for name, has_match_count in _MODULE_FUNCTIONS:
        original = getattr(re, name)
        wrapped = _make_wrapper(
            tracer,
            name,
            original,
            get_count=_get_count_func(name) if has_match_count else None,
        )
        setattr(re, name, wrapped)

    re.compile = _make_compile_wrapper(tracer, re.compile)  # type: ignore[assignment]


def _uninstrument() -> None:
    """Restore original re module functions.

    Uses __wrapped__ (set by functools.wraps) to restore each patched
    member. Safe to call multiple times; no-op if not instrumented.
    """
    for name in _MODULE_NAMES:
        wrapper = getattr(re, name)
        if original := getattr(wrapper, "__wrapped__", None):
            setattr(re, name, original)

class ReInstrumentor(BaseInstrumentor):
    """Instrumentor for the re (regex) module.

    This instrumentor adds OpenTelemetry tracing to Python's standard library
    `re` module, creating spans for regex operations like search, match,
    findall, sub, etc.

    Example::

        from opentelemetry_instrumentation_re import ReInstrumentor

        # Instrument the re module
        ReInstrumentor().instrument()

        # Now all re operations are traced
        import re
        re.search(r"\\d+", "hello 42 world")

        # Uninstrument when done
        ReInstrumentor().uninstrument()

    See :class:`opentelemetry.instrumentation.instrumentor.BaseInstrumentor`.
    """

    @override
    def instrumentation_dependencies(self) -> Collection[str]:
        return _instruments

    @override
    def _instrument(self, **kwargs: Any) -> None:
        """Instrument the re module.

        Args:
            **kwargs: Optional keyword arguments.
                tracer_provider: Optional TracerProvider instance.
                    If not provided, uses the global tracer provider.
        """
        tracer_provider = kwargs.get("tracer_provider")
        tracer = get_tracer(
            __name__,
            __version__,
            tracer_provider=tracer_provider,
            schema_url="https://opentelemetry.io/schemas/1.11.0",
        )
        _instrument(tracer)

    @override
    def _uninstrument(self, **kwargs: Any) -> None:
        """Uninstrument the re module.

        Restores the original re module functions. Safe to call multiple times.

        Args:
            **kwargs: Optional keyword arguments (unused).
        """
        _uninstrument()


__all__ = ["ReInstrumentor"]
