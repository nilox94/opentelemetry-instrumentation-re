"""Compatibility shims for older Python versions."""

from __future__ import annotations

try:
    from typing import override
except ImportError:
    from typing_extensions import override  # noqa: F401

__all__ = ["override"]
