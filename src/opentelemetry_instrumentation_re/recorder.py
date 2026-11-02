"""Record histograms and conditional spans for regex operations."""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from opentelemetry.context import get_current
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.trace import SpanKind, Status, StatusCode

from opentelemetry_instrumentation_re.utils.pattern import get_pattern_string, unwrap_pattern
from opentelemetry_instrumentation_re.utils.semconv import (
    ERROR_TYPE,
    RE_LIBRARY_NAME,
    RE_MATCH_COUNT,
    RE_OPERATION,
    RE_PATTERN,
    RE_PATTERN_LENGTH,
    RE_STRING_LENGTH,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from opentelemetry import context as context_api
    from opentelemetry.metrics import Counter, Histogram
    from opentelemetry.trace import Tracer
    from opentelemetry.util.types import AttributeValue

    from opentelemetry_instrumentation_re.config import InstrumentationConfig

# Set for the duration of histogram.record and span end. A custom meter or
# SpanProcessor.on_end can call back into re; the SDK does not suppress on_end.
_RECORDING: ContextVar[bool] = ContextVar("otel_re_recording", default=False)


class OperationRecorder:
    """Per-module recorder; set ``active=False`` on uninstrument."""

    # BackendProfile assigned by instrument_module before any call.
    profile: object | None = None
    # Copied off the profile so the hot path does not re-check its type.
    skip_one_method: bool = False
    haystack_keyword: str = "string"
    # The backend's own pattern error, reported as ``<module>.error``.
    pattern_error: type[BaseException] | None = None

    def __init__(
        self,
        tracer: Tracer,
        histogram: Histogram,
        errors: Counter,
        config: InstrumentationConfig,
        *,
        library_name: str,
        module_name: str,
    ) -> None:
        self.tracer = tracer
        self.histogram = histogram
        self.errors = errors
        self.config = config
        self.library_name = library_name
        self.module_name = module_name
        self.active = True
        # Set by instrument_module so proxies can be found again after uninstrument.
        self._module_key = 0
        # BackendProfile from core. Assigned before any instrumented call.
        self.profile = None
        self.skip_one_method = False
        self.haystack_keyword = "string"
        self.pattern_error = None
        self.histogram_floor_ns = config.histogram_floor_ms * 1_000_000
        self.span_threshold_ns = config.span_threshold_ms * 1_000_000
        # A successful call faster than this records nothing.
        self.quiet_below_ns = min(self.histogram_floor_ns, self.span_threshold_ns)
        # A failing exporter or meter would otherwise log on every regex call.
        self.failure_logged = False
        # Reused across calls. The SDK copies attribute items into its own key.
        self._metric_attrs: dict[str, dict[str, AttributeValue]] = {}
        self._error_attrs: dict[tuple[str, str], dict[str, AttributeValue]] = {}

    def _attributes_for(self, operation: str) -> dict[str, AttributeValue]:
        cached = self._metric_attrs.get(operation)
        if cached is None:
            fresh: dict[str, AttributeValue] = {
                RE_OPERATION: operation,
                RE_LIBRARY_NAME: self.library_name,
            }
            cached = fresh
            self._metric_attrs[operation] = cached
        return cached

    def _error_attributes(self, operation: str, error_type: str) -> dict[str, AttributeValue]:
        key = (operation, error_type)
        cached = self._error_attrs.get(key)
        if cached is None:
            fresh: dict[str, AttributeValue] = {
                RE_OPERATION: operation,
                RE_LIBRARY_NAME: self.library_name,
                ERROR_TYPE: error_type,
            }
            cached = fresh
            self._error_attrs[key] = cached
        return cached

    def error_type(self, exc: BaseException) -> str:
        """Stable ``error.type``. ``re.error`` is ``PatternError`` from Python 3.13 on."""
        if self.pattern_error is not None and isinstance(exc, self.pattern_error):
            return f"{self.module_name}.error"
        cls = type(exc)
        if cls.__module__ == "builtins":
            return cls.__qualname__
        return f"{cls.__module__}.{cls.__qualname__}"

    def record_finished(
        self,
        operation: str,
        start_ns: int,
        end_ns: int,
        parent_context: context_api.Context | None,
        *,
        pattern_source: Any,
        string_length: int | None,
        exc: BaseException | None,
        result_attributes: dict[str, AttributeValue] | None = None,
    ) -> None:
        if not self.active:
            return
        elapsed_ns = end_ns - start_ns
        record_duration = elapsed_ns >= self.histogram_floor_ns
        emit_span = elapsed_ns >= self.span_threshold_ns
        if exc is None and not record_duration and not emit_span:
            return
        # Also reached from an abandoned finditer's finalizer, which the garbage
        # collector can run inside histogram.record while the SDK holds its lock.
        if _RECORDING.get():
            return

        # Parent is the caller's context. Fetch it only when a span is emitted,
        # and before suppress_instrumentation attaches a different context.
        # Callers that run user code (a replacement, finditer) pass the context
        # captured at the start of the call.
        parent = parent_context
        if emit_span and parent is None:
            parent = get_current()

        token = _RECORDING.set(True)
        try:
            if record_duration:
                self.histogram.record(elapsed_ns / 1_000_000_000, self._attributes_for(operation))
            if exc is not None:
                self.errors.add(1, self._error_attributes(operation, self.error_type(exc)))
            if not emit_span or parent is None:
                return
            # on_end runs inline. Suppress every instrumentation there, not
            # only this one: a processor may export or open other spans.
            with suppress_instrumentation():
                self._emit_span(
                    operation,
                    start_ns,
                    end_ns,
                    parent,
                    pattern_source=pattern_source,
                    string_length=string_length,
                    exc=exc,
                    result_attributes=result_attributes,
                )
        finally:
            _RECORDING.reset(token)

    def _emit_span(
        self,
        operation: str,
        start_ns: int,
        end_ns: int,
        parent_context: context_api.Context,
        *,
        pattern_source: Any,
        string_length: int | None,
        exc: BaseException | None,
        result_attributes: dict[str, AttributeValue] | None = None,
    ) -> None:
        span_attrs: dict[str, AttributeValue] = {
            RE_OPERATION: operation,
            RE_LIBRARY_NAME: self.library_name,
        }
        if string_length is not None:
            span_attrs[RE_STRING_LENGTH] = string_length

        pattern_len = self._pattern_length(pattern_source)
        if pattern_len is not None:
            span_attrs[RE_PATTERN_LENGTH] = pattern_len
        if self.config.capture_pattern:
            pattern_text = self._pattern_text(pattern_source)
            if pattern_text is not None:
                max_len = self.config.capture_pattern_max_len
                span_attrs[RE_PATTERN] = pattern_text[:max_len]

        if result_attributes:
            span_attrs.update(result_attributes)

        span = self.tracer.start_span(
            f"{self.library_name}.{operation}",
            context=parent_context,
            kind=SpanKind.INTERNAL,
            start_time=start_ns,
        )
        if span.is_recording():
            span.set_attributes(span_attrs)
            if exc is not None:
                span.set_attribute(ERROR_TYPE, self.error_type(exc))
                span.set_status(Status(StatusCode.ERROR))
        span.end(end_time=end_ns)

    def _pattern_length(self, pattern_source: Any) -> int | None:
        if pattern_source is None:
            return None
        if isinstance(pattern_source, (str, bytes)):
            return len(pattern_source)
        try:
            raw = getattr(unwrap_pattern(pattern_source), "pattern", None)
            if isinstance(raw, (str, bytes)):
                return len(raw)
        except (TypeError, ValueError, AttributeError):
            return None
        return None

    def _pattern_text(self, pattern_source: Any) -> str | None:
        if pattern_source is None:
            return None
        try:
            return get_pattern_string(pattern_source, decode_bytes=True)
        except (TypeError, ValueError, AttributeError):
            return None


def monotonic_ns() -> int:
    return time.perf_counter_ns()


def epoch_ns() -> int:
    return time.time_ns()


def capture_start() -> tuple[int, int]:
    """Return ``(epoch_ns, monotonic_ns)`` taken together.

    Span timestamps must be epoch nanoseconds. Duration uses the monotonic
    clock so a wall-clock step cannot shrink or stretch the measurement.
    """
    return epoch_ns(), monotonic_ns()


def string_length(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return len(value)
    except TypeError:
        return None


def result_match_count(operation: str, result: Any) -> dict[str, AttributeValue] | None:
    if operation == "findall" and isinstance(result, list):
        return {RE_MATCH_COUNT: len(result)}
    if operation == "subn" and isinstance(result, tuple) and len(result) == 2:
        return {RE_MATCH_COUNT: result[1]}
    return None


def make_result_attrs_fn(
    operation: str,
) -> Callable[[Any], dict[str, AttributeValue] | None]:
    def _fn(result: Any) -> dict[str, AttributeValue] | None:
        return result_match_count(operation, result)

    return _fn
