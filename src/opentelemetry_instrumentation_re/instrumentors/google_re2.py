"""Instrumentor for the google-re2 (re2) module."""

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


class GoogleRe2Instrumentor(BaseInstrumentor):
    """Instrumentor for the re2 module from the google-re2 package.

    Call :meth:`instrument` explicitly (this package does not register auto-instrumentation
    entry points). Optional kwargs: ``tracer_provider``, ``meter_provider``,
    ``span_threshold_ms``, ``histogram_floor_ms``, ``capture_pattern``,
    ``capture_pattern_max_len``.

    google-re2 names the haystack ``text``. ``string=`` raises ``TypeError``, as it does
    without instrumentation.
    """

    @override
    def instrumentation_dependencies(self) -> Collection[str]:
        return ("google-re2 >= 1.0",)

    @override
    def _instrument(self, **kwargs: Any) -> None:
        import re2

        config = InstrumentationConfig.from_kwargs(**kwargs)
        tracer = create_tracer(kwargs.get("tracer_provider"))
        meter = create_meter(kwargs.get("meter_provider"))
        histogram = create_duration_histogram(meter)
        errors = create_error_counter(meter)
        instrument_module(
            re2,
            tracer,
            histogram,
            errors,
            config,
            lambda: type(re2.compile("")),
            library_name="google_re2",
        )

    @override
    def _uninstrument(self, **kwargs: Any) -> None:
        import re2

        uninstrument_module(re2)
