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
from functools import partial
from typing import TYPE_CHECKING, Any, Callable

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
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

# Marker to avoid double uninstrument
_INSTRUMENTED_MARKER = "_opentelemetry_instrumentation_re_applied"

# Saved originals for uninstrument
_originals: dict[str, Any] = {}


def _instrument_call(
    tracer: Tracer,
    name: str,
    attributes: dict[str, Any],
    call_original: Callable[[], Any],
    result_attributes: Callable[[Any], dict[str, Any]] | None = None,
) -> Any:
    """Run call_original inside a span, setting attributes. Minimal error handling (SDK sets status)."""
    with tracer.start_as_current_span(
        f"re.{name}",
        kind=SpanKind.INTERNAL,
    ) as span:
        if span.is_recording():
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
        result = call_original()
        if span.is_recording() and result_attributes is not None:
            for key, value in result_attributes(result).items():
                if value is not None:
                    span.set_attribute(key, value)
        return result


def _make_module_wrapper(
    tracer: Tracer,
    name: str,
    original: Callable[..., Any],
) -> Callable[..., Any]:
    """Build a wrapper for a module-level re function (e.g. re.search).

    Args:
        tracer: The OpenTelemetry Tracer instance.
        name: The function name (e.g., "search", "match").
        original: The original re module function to wrap.

    Returns:
        A wrapped function that creates spans for each call.
    """

    def wrapper(pattern: Any, string: Any, *args: Any, **kwargs: Any) -> Any:
        def get_attrs() -> dict[str, Any]:
            attrs: dict[str, Any] = {RE_FUNCTION: name}
            if string is not None:
                attrs[RE_STRING_LENGTH] = len(string)
            pattern_str = get_pattern_string(pattern)
            if pattern_str is not None:
                attrs[RE_PATTERN] = pattern_str
            return attrs

        return _instrument_call(
            tracer,
            name,
            get_attrs(),
            lambda: original(pattern, string, *args, **kwargs),
            None,
        )

    # Set __wrapped__ for introspection and unwrapping
    setattr(wrapper, "__wrapped__", original)  # noqa: B010
    setattr(wrapper, _INSTRUMENTED_MARKER, True)  # noqa: B010
    return wrapper


def _make_module_wrapper_with_match_count(
    tracer: Tracer,
    name: str,
    original: Callable[..., Any],
    get_count: Callable[[Any], int],
) -> Callable[..., Any]:
    """Build a wrapper for findall or subn that sets re.match_count from result."""

    def wrapper(pattern: Any, string: Any, *args: Any, **kwargs: Any) -> Any:
        def get_attrs() -> dict[str, Any]:
            attrs: dict[str, Any] = {RE_FUNCTION: name}
            if string is not None:
                attrs[RE_STRING_LENGTH] = len(string)
            pattern_str = get_pattern_string(pattern)
            if pattern_str is not None:
                attrs[RE_PATTERN] = pattern_str
            return attrs

        def result_attrs(result: Any) -> dict[str, Any]:
            return {RE_MATCH_COUNT: get_count(result)}

        return _instrument_call(
            tracer,
            name,
            get_attrs(),
            lambda: original(pattern, string, *args, **kwargs),
            result_attrs,
        )

    # Set __wrapped__ for introspection and unwrapping
    setattr(wrapper, "__wrapped__", original)  # noqa: B010
    setattr(wrapper, _INSTRUMENTED_MARKER, True)  # noqa: B010
    return wrapper


def _make_pattern_wrapper(
    tracer: Tracer,
    name: str,
    original: Callable[..., Any],
) -> Callable[..., Any]:
    """Build a wrapper for a Pattern method (e.g. Pattern.search).

    Args:
        tracer: The OpenTelemetry Tracer instance.
        name: The method name (e.g., "search", "match").
        original: The original Pattern method to wrap.

    Returns:
        A wrapped method that creates spans for each call.
    """

    def wrapper(self: Any, string: Any, *args: Any, **kwargs: Any) -> Any:
        pattern_str = getattr(self, "pattern", None)

        def get_attrs() -> dict[str, Any]:
            attrs: dict[str, Any] = {RE_FUNCTION: name}
            if string is not None:
                attrs[RE_STRING_LENGTH] = len(string)
            if pattern_str is not None:
                attrs[RE_PATTERN] = pattern_str
            return attrs

        return _instrument_call(
            tracer,
            name,
            get_attrs(),
            lambda: original(self, string, *args, **kwargs),
            None,
        )

    # Set __wrapped__ for introspection and unwrapping
    setattr(wrapper, "__wrapped__", original)  # noqa: B010
    setattr(wrapper, _INSTRUMENTED_MARKER, True)  # noqa: B010
    return wrapper


def _make_pattern_wrapper_with_match_count(
    tracer: Tracer,
    name: str,
    original: Callable[..., Any],
    get_count: Callable[[Any], int],
) -> Callable[..., Any]:
    """Build a wrapper for Pattern.findall or Pattern.subn that sets re.match_count.

    Args:
        tracer: The OpenTelemetry Tracer instance.
        name: The method name ("findall" or "subn").
        original: The original Pattern method to wrap.
        get_count: Function to extract match count from the result.

    Returns:
        A wrapped method that creates spans with match_count attribute.
    """

    def wrapper(self: Any, string: Any, *args: Any, **kwargs: Any) -> Any:
        pattern_str = getattr(self, "pattern", None)

        def get_attrs() -> dict[str, Any]:
            attrs: dict[str, Any] = {RE_FUNCTION: name}
            if string is not None:
                attrs[RE_STRING_LENGTH] = len(string)
            if pattern_str is not None:
                attrs[RE_PATTERN] = pattern_str
            return attrs

        def result_attrs(result: Any) -> dict[str, Any]:
            return {RE_MATCH_COUNT: get_count(result)}

        return _instrument_call(
            tracer,
            name,
            get_attrs(),
            lambda: original(self, string, *args, **kwargs),
            result_attrs,
        )

    # Set __wrapped__ for introspection and unwrapping
    setattr(wrapper, "__wrapped__", original)  # noqa: B010
    setattr(wrapper, _INSTRUMENTED_MARKER, True)  # noqa: B010
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

    def __init__(self, pattern: Any, tracer: Tracer) -> None:
        self._pattern = pattern
        self._tracer = tracer
        self._wrapped_methods: dict[str, Callable[..., Any]] = {}
        self._setup_wrappers()

    def _setup_wrappers(self) -> None:
        """Set up wrapped methods for this instance."""
        for name, has_match_count in _PATTERN_METHODS:
            # Get the unbound method from the Pattern class
            original = getattr(re.Pattern, name)
            if has_match_count:
                wrapped_unbound = _make_pattern_wrapper_with_match_count(
                    self._tracer, name, original, _get_count_func(name)
                )
            else:
                wrapped_unbound = _make_pattern_wrapper(self._tracer, name, original)
            # Bind the wrapper to self._pattern using partial
            self._wrapped_methods[name] = partial(wrapped_unbound, self._pattern)

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to wrapped pattern or wrapped methods."""
        if name in self._wrapped_methods:
            return self._wrapped_methods[name]
        return getattr(self._pattern, name)

    # Delegate common Pattern attributes
    @property
    def pattern(self) -> str:
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
        return self._pattern.groupindex


def _make_compile_wrapper(tracer: Tracer, original_compile: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap re.compile to instrument Pattern instances.

    Args:
        tracer: The OpenTelemetry Tracer instance.
        original_compile: The original re.compile function.

    Returns:
        A wrapped compile function that returns instrumented Pattern instances.
    """
    def wrapper(pattern: Any, flags: int = 0) -> Any:
        compiled = original_compile(pattern, flags)
        return _PatternWrapper(compiled, tracer)

    # Set __wrapped__ for introspection and unwrapping
    setattr(wrapper, "__wrapped__", original_compile)  # noqa: B010
    setattr(wrapper, _INSTRUMENTED_MARKER, True)  # noqa: B010
    return wrapper


def _instrument(tracer: Tracer) -> None:
    """Patch re module and Pattern methods.

    This function replaces module-level re functions and re.compile with
    instrumented versions that create OpenTelemetry spans.

    Args:
        tracer: The OpenTelemetry Tracer instance to use for creating spans.
    """
    # Module-level functions
    for name, has_match_count in _MODULE_FUNCTIONS:
        original = getattr(re, name)
        _originals[name] = original
        if has_match_count:
            wrapped = _make_module_wrapper_with_match_count(
                tracer, name, original, _get_count_func(name)
            )
        else:
            wrapped = _make_module_wrapper(tracer, name, original)
        setattr(re, name, wrapped)

    # Patch re.compile to wrap Pattern instances
    _originals["compile"] = re.compile
    re.compile = _make_compile_wrapper(tracer, re.compile)


def _uninstrument() -> None:
    """Restore original re module and Pattern methods.

    This function undoes the instrumentation by restoring the original
    re module functions and re.compile. Safe to call multiple times.
    """
    if not _originals:
        return
    # Restore module-level functions
    for name, _ in _MODULE_FUNCTIONS:
        if name in _originals:
            setattr(re, name, _originals.pop(name))
    # Restore re.compile
    if "compile" in _originals:
        re.compile = _originals.pop("compile")


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

    def instrumentation_dependencies(self) -> Collection[str]:
        return _instruments

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

    def _uninstrument(self, **kwargs: Any) -> None:
        """Uninstrument the re module.

        Restores the original re module functions. Safe to call multiple times.

        Args:
            **kwargs: Optional keyword arguments (unused).
        """
        _uninstrument()


__all__ = ["ReInstrumentor", "__version__"]
