"""
OpenTelemetry instrumentation for re-like modules (re, regex, re2).

Supports the stdlib re module and the optional regex and google-re2 packages.
Use ReInstrumentor for stdlib re; RegexInstrumentor or GoogleRe2Instrumentor
when your code uses those modules.

Usage (stdlib re)::

    import re
    from opentelemetry_instrumentation_re import ReInstrumentor

    ReInstrumentor().instrument()

    re.search(r"\\d+", "hello 42 world")
    re.compile(r"\\w+").findall("a b c")
"""

from opentelemetry_instrumentation_re.instrumentors.google_re2 import GoogleRe2Instrumentor
from opentelemetry_instrumentation_re.instrumentors.re import ReInstrumentor
from opentelemetry_instrumentation_re.instrumentors.regex import RegexInstrumentor
from opentelemetry_instrumentation_re.version import __version__

__all__ = [
    "ReInstrumentor",
    "RegexInstrumentor",
    "GoogleRe2Instrumentor",
    "__version__",
]
