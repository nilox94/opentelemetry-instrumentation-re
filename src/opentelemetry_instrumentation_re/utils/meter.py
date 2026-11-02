"""Shared meter creation for histogram recording."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry.metrics import get_meter

from opentelemetry_instrumentation_re.version import __version__

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter, Histogram, Meter, MeterProvider


def create_meter(
    meter_provider: MeterProvider | None = None,
    *,
    module_name: str = "opentelemetry_instrumentation_re",
) -> Meter:
    return get_meter(module_name, __version__, meter_provider=meter_provider)


def create_duration_histogram(meter: Meter) -> Histogram:
    return meter.create_histogram(
        "re.operation.duration",
        unit="s",
        description="Duration of regex operations at or above histogram_floor_ms",
        # Starts above the default 100 µs floor so the first bucket is not always empty.
        explicit_bucket_boundaries_advisory=(
            0.00025,
            0.0005,
            0.001,
            0.0025,
            0.005,
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1.0,
            2.5,
        ),
    )


def create_error_counter(meter: Meter) -> Counter:
    return meter.create_counter(
        "re.operation.errors",
        unit="{error}",
        description="Regex operations that raised",
    )
