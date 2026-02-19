"""Package metadata for opentelemetry-instrumentation-re.

Instrumentation dependencies are declared per instrumentor (ReInstrumentor,
RegexInstrumentor, GoogleRe2Instrumentor) via instrumentation_dependencies(),
not via a single package-level list.
"""

from __future__ import annotations

_supports_metrics = False
