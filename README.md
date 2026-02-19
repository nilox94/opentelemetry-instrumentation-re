# OpenTelemetry instrumentation for Python regex libraries

[![Test](https://github.com/nilox94/opentelemetry-instrumentation-re/actions/workflows/test.yml/badge.svg)](https://github.com/nilox94/opentelemetry-instrumentation-re/actions/workflows/test.yml)

This library provides [OpenTelemetry instrumentation](https://opentelemetry.io/docs/concepts/instrumentation/) for three Python regex libraries: the standard library [`re`](https://docs.python.org/3/library/re.html), and the [`regex`](https://pypi.org/project/regex/) and [`google-re2`](https://pypi.org/project/google-re2/) packages.
It emits spans for all regex operations (see [Supported Operations](#supported-operations)) and for compiled pattern methods.

## Installation

Install the package; add the extras for the libraries you want to instrument:

```bash
pip install opentelemetry-instrumentation-re                    # stdlib re (always available)
pip install opentelemetry-instrumentation-re[regex]             # regex package
pip install opentelemetry-instrumentation-re[google-re2]        # google-re2 package
```

**Compatibility:** stdlib `re` works out of the box. To instrument `regex`, install version **`>= 2021.0`**; for `google-re2`, install version **`>= 1.0`**. All recent versions are supported.

## Usage

### Manual instrumentation

Instrument the library or libraries you use.
Each exposes the same operations; use the instrumentor that matches your imports.

**stdlib `re`:**

```python
import re
from opentelemetry_instrumentation_re import ReInstrumentor

ReInstrumentor().instrument()
re.search(r"\d+", "hello 42 world")
pattern = re.compile(r"\d+")
pattern.findall("a1 b2 c3")
```

**`regex` package**:

```python
import regex
from opentelemetry_instrumentation_re import RegexInstrumentor

RegexInstrumentor().instrument()
regex.search(r"\d+", "hello 42 world")
```

**`google-re2` package**:

```python
import re2
from opentelemetry_instrumentation_re import GoogleRe2Instrumentor

GoogleRe2Instrumentor().instrument()
re2.search(r"\d+", "hello 42 world")
```

You can instrument more than one of these in the same process if your application uses multiple regex libraries.

### Auto-instrumentation

If you already run your app with [OpenTelemetry Python auto-instrumentation](https://opentelemetry.io/docs/languages/python/automatic/), you don't need to change any code: install this package (and the `[regex]` and/or `[google-re2]` extras for the libraries you use).
The agent discovers and enables the instrumentors automatically.
To disable them, use `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS=re,regex,google_re2` as needed.
For setup of the agent itself, see the linked doc.

### Uninstrumenting

Call `uninstrument()` on the same instrumentor you used to stop tracing for that library:

```python
from opentelemetry_instrumentation_re import ReInstrumentor, RegexInstrumentor, GoogleRe2Instrumentor

ReInstrumentor().uninstrument()         # re
RegexInstrumentor().uninstrument()      # regex
GoogleRe2Instrumentor().uninstrument()  # google-re2
```

## Span Attributes

Spans are named `{library}.{operation}` (e.g. `re.search`, `regex.findall`, `google_re2.sub`).
The following attributes are added to spans:

- `re.operation` - operation name (e.g. `search`, `match`, `sub`, `findall`).
- `re.pattern` - full pattern string (may contain sensitive data; consider your export/backend policy).
- `re.string_length` - length of the input string.
- `re.match_count` - number of matches found (only for `findall` and `subn` operations).
- `re.library.name` - instrumented library: `re`, `regex`, or `google_re2`.

### Example Span

After calling `re.search(r"\d+", "hello 42 world")` with the stdlib `re` instrumentor, the following span is created:

```json
{
  "name": "re.search",
  "kind": "INTERNAL",
  "attributes": {
    "re.operation": "search",
    "re.pattern": "\\d+",
    "re.string_length": 14,
    "re.library.name": "re"
  }
}
```

Example with `re.findall(r"\d", "a1 b2 c3")`, which includes the `re.match_count` attribute:

```json
{
  "name": "re.findall",
  "kind": "INTERNAL",
  "attributes": {
    "re.operation": "findall",
    "re.pattern": "\\d",
    "re.string_length": 8,
    "re.match_count": 3,
    "re.library.name": "re"
  }
}
```

## Supported Operations

| Operation | Module-level Function | Compiled Pattern Method | Instrumented Libraries | Notes |
|-----------|----------------------|------------------------|------------------------|-------|
| `search` | `re.search()` | `pattern.search()` | `re`, `regex`, `google-re2` | |
| `match` | `re.match()` | `pattern.match()` | `re`, `regex`, `google-re2` | |
| `fullmatch` | `re.fullmatch()` | `pattern.fullmatch()` | `re`, `regex`, `google-re2` | |
| `split` | `re.split()` | `pattern.split()` | `re`, `regex`, `google-re2` | |
| `findall` | `re.findall()` | `pattern.findall()` | `re`, `regex`, `google-re2` | Includes `re.match_count` |
| `finditer` | `re.finditer()` | `pattern.finditer()` | `re`, `regex`, `google-re2` | |
| `sub` | `re.sub()` | `pattern.sub()` | `re`, `regex`, `google-re2` | |
| `subn` | `re.subn()` | `pattern.subn()` | `re`, `regex`, `google-re2` | Includes `re.match_count` |

## Learn more

- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/) - language overview and concepts.
- [Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/) - manual instrumentation and TracerProvider setup.
- [Python getting started](https://opentelemetry.io/docs/languages/python/getting-started/) - end-to-end setup with an exporter.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, running tests, linting, and **Git hooks (prek)**.
Maintainers: see [RELEASING.md](RELEASING.md) for how to publish releases.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow.

## License

Apache-2.0
