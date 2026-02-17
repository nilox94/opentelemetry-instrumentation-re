"""Shared tracer creation for all instrumentors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry.trace import get_tracer

from opentelemetry_instrumentation_re.version import __version__

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer, TracerProvider

_SCHEMA_URL = "https://opentelemetry.io/schemas/1.11.0"


def create_tracer(
    tracer_provider: TracerProvider | None = None,
    *,
    module_name: str = "opentelemetry_instrumentation_re",
) -> Tracer:
    """Return a Tracer for this instrumentation library."""
    return get_tracer(
        module_name,
        __version__,
        tracer_provider=tracer_provider,
        schema_url=_SCHEMA_URL,
    )
