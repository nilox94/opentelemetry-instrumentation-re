"""Packaging and discovery tests."""

from __future__ import annotations

from importlib.metadata import entry_points

from opentelemetry_instrumentation_re import __version__


def test_no_auto_instrumentation_entry_points() -> None:
    group = entry_points(group="opentelemetry_instrumentor")
    ours = [ep for ep in group if ep.value.startswith("opentelemetry_instrumentation_re")]
    assert ours == []


def test_version_matches_pyproject() -> None:
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    version = None
    for line in pyproject.read_text().splitlines():
        if line.startswith("version = "):
            version = line.split("=", 1)[1].strip().strip('"')
            break
    assert version is not None
    assert __version__ == version
