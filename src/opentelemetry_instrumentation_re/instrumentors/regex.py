"""Instrumentor for the regex (PyPI) module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor

from opentelemetry_instrumentation_re._compat import override
from opentelemetry_instrumentation_re.config import InstrumentationConfig
from opentelemetry_instrumentation_re.core import instrument_module, uninstrument_module
from opentelemetry_instrumentation_re.utils.meter import (
    create_duration_histogram,
    create_error_counter,
    create_meter,
)
from opentelemetry_instrumentation_re.utils.tracer import create_tracer

if TYPE_CHECKING:
    from collections.abc import Collection


class RegexInstrumentor(BaseInstrumentor):
    """Instrumentor for the regex module (PyPI regex).

    Call :meth:`instrument` explicitly (this package does not register auto-instrumentation
    entry points). Optional kwargs: ``tracer_provider``, ``meter_provider``,
    ``span_threshold_ms``, ``histogram_floor_ms``, ``capture_pattern``,
    ``capture_pattern_max_len``.
    """

    @override
    def instrumentation_dependencies(self) -> Collection[str]:
        return ("regex >= 2021.0",)

    @override
    def _instrument(self, **kwargs: Any) -> None:
        import regex

        config = InstrumentationConfig.from_kwargs(**kwargs)
        tracer = create_tracer(kwargs.get("tracer_provider"))
        meter = create_meter(kwargs.get("meter_provider"))
        histogram = create_duration_histogram(meter)
        errors = create_error_counter(meter)
        instrument_module(
            regex,
            tracer,
            histogram,
            errors,
            config,
            lambda: type(regex.compile("")),
            library_name="regex",
        )

    @override
    def _uninstrument(self, **kwargs: Any) -> None:
        import regex

        uninstrument_module(regex)
