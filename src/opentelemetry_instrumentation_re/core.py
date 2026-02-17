"""Core instrumentation logic for re-like modules (patch helpers, wrappers)."""

from __future__ import annotations

from functools import partial, wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from opentelemetry.trace import SpanKind

from opentelemetry_instrumentation_re.utils.pattern import get_pattern_string
from opentelemetry_instrumentation_re.utils.semconv import (
    RE_FUNCTION,
    RE_LIBRARY_NAME,
    RE_MATCH_COUNT,
    RE_PATTERN,
    RE_STRING_LENGTH,
)

if TYPE_CHECKING:
    from opentelemetry.sdk.resources import Attributes
    from opentelemetry.trace import Tracer

_R = TypeVar("_R")

_SUB_SUBN = ("sub", "subn")

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
"""Module-level functions to instrument."""

_PATTERN_METHODS = _FUNCTIONS
"""Pattern methods to instrument."""

_MODULE_NAMES = (*_MODULE_FUNCTIONS, "compile")
"""Names of functions and methods on the module to instrument."""


def _search_string_for_attrs(name: str, *args: Any) -> str | bytes:
    if name in _SUB_SUBN and args:
        return args[1]
    return args[0]


def _instrument_call(
    tracer: Tracer,
    name: str,
    attributes: Attributes,
    call_original: Callable[[], _R],
    result_attributes: Callable[[_R], Attributes] | None = None,
    *,
    library_name: str | None = None,
) -> _R:
    with tracer.start_as_current_span(f"re.{name}", kind=SpanKind.INTERNAL) as span:
        if span.is_recording():
            span.set_attributes(attributes)
            if library_name is not None:
                span.set_attribute(RE_LIBRARY_NAME, library_name)
        result: _R = call_original()
        if result_attributes is not None and span.is_recording():
            span.set_attributes(result_attributes(result))
        return result


def _get_count_func(name: str) -> Callable[[Any], int] | None:
    if name == "findall":
        return len
    if name == "subn":
        # text, count = result
        return lambda result: result[1]
    return None


def _make_wrapper(
    tracer: Tracer,
    name: str,
    original: Callable[..., _R],
    *,
    get_count: Callable[[_R], int] | None = None,
    library_name: str | None = None,
) -> Callable[..., _R]:
    @wraps(original)
    def wrapper(first: Any, *args: Any, **kwargs: Any) -> _R:
        pattern_str = get_pattern_string(first)
        search_str = _search_string_for_attrs(name, *args)
        attrs: Attributes = {
            RE_FUNCTION: name,
            RE_STRING_LENGTH: len(search_str),
            RE_PATTERN: pattern_str,
        }
        result_attrs_fn: Callable[[_R], Attributes] | None = (
            (lambda r: {RE_MATCH_COUNT: get_count(r)}) if callable(get_count) else None  # pyright: ignore[reportOptionalCall]
        )
        return _instrument_call(
            tracer,
            name,
            attrs,
            lambda: original(first, *args, **kwargs),
            result_attrs_fn,
            library_name=library_name,
        )

    return wrapper


class _PatternWrapper:
    """Wraps a compiled pattern so method calls are traced. Uses tracer and pattern_type only in __init__ to build wrapped methods."""

    def __init__(
        self,
        pattern: Any,
        tracer: Tracer,
        pattern_type: type,
        *,
        library_name: str | None = None,
    ) -> None:
        self._pattern: Any = pattern
        self._wrapped_methods: dict[str, Callable[..., Any]] = {}
        for name in _PATTERN_METHODS:
            original = getattr(pattern_type, name)
            wrapped = _make_wrapper(
                tracer,
                name,
                original,
                get_count=_get_count_func(name),
                library_name=library_name,
            )
            self._wrapped_methods[name] = partial(wrapped, pattern)

    def __getattr__(self, name: str) -> Any:
        if name in self._wrapped_methods:
            return self._wrapped_methods[name]
        return getattr(self._pattern, name)

    @property
    def pattern(self) -> str | bytes:
        return self._pattern.pattern


def _make_compile_wrapper(
    tracer: Tracer,
    original_compile: Callable[..., Any],
    pattern_type: type,
    *,
    library_name: str | None = None,
) -> Callable[..., _PatternWrapper]:
    @wraps(original_compile)
    def wrapper(*args: Any, **kwargs: Any) -> _PatternWrapper:
        compiled = original_compile(*args, **kwargs)
        return _PatternWrapper(compiled, tracer, pattern_type, library_name=library_name)

    return wrapper


def instrument_module(
    module: Any,
    tracer: Tracer,
    get_pattern_type: Callable[[], type],
    *,
    library_name: str | None = None,
) -> None:
    """Patch a re-like module with instrumented functions and compile."""
    pattern_type = get_pattern_type()
    for name in _MODULE_FUNCTIONS:
        original = getattr(module, name)
        wrapped = _make_wrapper(
            tracer,
            name,
            original,
            get_count=_get_count_func(name),
            library_name=library_name,
        )
        setattr(module, name, wrapped)
    original_compile = module.compile
    module.compile = _make_compile_wrapper(
        tracer, original_compile, pattern_type, library_name=library_name
    )


def uninstrument_module(module: Any) -> None:
    """Restore original functions on a previously instrumented module."""
    for name in _MODULE_NAMES:
        wrapper = getattr(module, name, None)
        if original := getattr(wrapper, "__wrapped__", None):
            setattr(module, name, original)
