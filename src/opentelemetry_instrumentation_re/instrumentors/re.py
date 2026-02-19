"""Instrumentor for the stdlib re module."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor

from opentelemetry_instrumentation_re._compat import override
from opentelemetry_instrumentation_re.core import instrument_module, uninstrument_module
from opentelemetry_instrumentation_re.utils.tracer import create_tracer

if TYPE_CHECKING:
    from collections.abc import Collection

logger = logging.getLogger(__name__)


class ReInstrumentor(BaseInstrumentor):
    """Instrumentor for the re (regex) module.

    This instrumentor adds OpenTelemetry tracing to Python's standard library
    `re` module, creating spans for regex operations like search, match,
    findall, sub, etc.

    Example::

        from opentelemetry_instrumentation_re import ReInstrumentor

        ReInstrumentor().instrument()
        import re
        re.search(r"\\d+", "hello 42 world")
        ReInstrumentor().uninstrument()

    See :class:`opentelemetry.instrumentation.instrumentor.BaseInstrumentor`.
    """

    @override
    def instrumentation_dependencies(self) -> Collection[str]:
        return ()  # stdlib re has no package dependency

    @override
    def _instrument(self, **kwargs: Any) -> None:
        tracer = create_tracer(kwargs.get("tracer_provider"))
        try:
            instrument_module(re, tracer, lambda: re.Pattern, library_name="re")
        except Exception as e:
            logger.warning("Failed to instrument re: %s", e, exc_info=True)

    @override
    def _uninstrument(self, **kwargs: Any) -> None:
        uninstrument_module(re)
