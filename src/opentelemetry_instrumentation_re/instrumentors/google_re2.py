"""Instrumentor for the google-re2 (re2) module."""

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


def _instrument_google_re2(tracer: Tracer) -> None:
    try:
        import re2
    except ImportError as e:
        logger.debug("Skipping google-re2 instrumentation: module not installed (%s)", e)
        return
    try:
        instrument_module(re2, tracer, lambda: type(re2.compile("")), library_name="google_re2")
    except Exception as e:
        logger.warning("Failed to instrument google-re2: %s", e, exc_info=True)


def _uninstrument_google_re2() -> None:
    try:
        import re2
    except ImportError as e:
        logger.debug("Skipping google-re2 uninstrument: module not installed (%s)", e)
        return
    uninstrument_module(re2)


class GoogleRe2Instrumentor(BaseInstrumentor):
    """Instrumentor for the re2 module from the google-re2 package.

    Only instruments if google-re2 is installed (module name is also re2).
    Use when your code uses the official Google RE2 Python bindings.
    """

    @override
    def instrumentation_dependencies(self) -> Collection[str]:
        return ("google-re2 >= 1.0",)

    @override
    def _instrument(self, **kwargs: Any) -> None:
        _instrument_google_re2(create_tracer(kwargs.get("tracer_provider")))

    @override
    def _uninstrument(self, **kwargs: Any) -> None:
        _uninstrument_google_re2()
