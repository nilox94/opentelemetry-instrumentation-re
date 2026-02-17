"""Instrumentor for the regex (PyPI) module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, override

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor

from opentelemetry_instrumentation_re.core import instrument_module, uninstrument_module
from opentelemetry_instrumentation_re.utils.tracer import create_tracer

if TYPE_CHECKING:
    from collections.abc import Collection

    from opentelemetry.trace import Tracer

logger = logging.getLogger(__name__)


def _instrument_regex(tracer: Tracer) -> None:
    try:
        import regex
    except ImportError as e:
        logger.debug("Skipping regex instrumentation: module not installed (%s)", e)
        return
    try:
        instrument_module(regex, tracer, lambda: type(regex.compile("")), library_name="regex")
    except Exception as e:
        logger.warning("Failed to instrument regex: %s", e, exc_info=True)


def _uninstrument_regex() -> None:
    try:
        import regex
    except ImportError as e:
        logger.debug("Skipping regex uninstrument: module not installed (%s)", e)
        return
    uninstrument_module(regex)


class RegexInstrumentor(BaseInstrumentor):
    """Instrumentor for the regex module (PyPI regex).

    Only instruments if the regex module is installed. Use when your code
    uses ``import regex`` instead of stdlib ``re``.
    """

    @override
    def instrumentation_dependencies(self) -> Collection[str]:
        return ("regex",)

    @override
    def _instrument(self, **kwargs: Any) -> None:
        _instrument_regex(create_tracer(kwargs.get("tracer_provider")))

    @override
    def _uninstrument(self, **kwargs: Any) -> None:
        _uninstrument_regex()
