# OpenTelemetry instrumentation for Python's `re` module

This library provides OpenTelemetry instrumentation for Python's standard library
[`re`](https://docs.python.org/3/library/re.html) (regular expression) module,
emitting spans for matching operations (search, match, fullmatch, split, findall,
finditer, sub, subn) and for compiled pattern methods.

## Installation

```bash
pip install opentelemetry-instrumentation-re
```

## Usage

### Basic Usage

```python
import re
from opentelemetry_instrumentation_re import ReInstrumentor

# Instrument the re module
ReInstrumentor().instrument()

# All re operations are now traced
re.search(r"\d+", "hello 42 world")
re.match(r"hello", "hello world")
re.findall(r"\w+", "a b c")

# Compiled patterns are also instrumented
pattern = re.compile(r"\d+")
pattern.search("test 123")
pattern.findall("a1 b2 c3")
```

### Uninstrumenting

```python
from opentelemetry_instrumentation_re import ReInstrumentor

# Stop tracing re operations
ReInstrumentor().uninstrument()
```

## Span Attributes

The following attributes are added to spans:

- `re.function` - operation name (e.g. `search`, `match`, `sub`, `findall`).
- `re.pattern` - full pattern string (may contain sensitive data).
- `re.string_length` - length of the input string.
- `re.match_count` - number of matches (only for `findall` and `subn` operations).

### Example Span

After calling `re.search(r"\d+", "hello 42 world")`, the following span is created:

```json
{
  "name": "re.search",
  "kind": "INTERNAL",
  "attributes": {
    "re.function": "search",
    "re.pattern": "\\d+",
    "re.string_length": 14
  }
}
```

Example with `re.findall(r"\d", "a1 b2 c3")`, which includes `re.match_count`:

```json
{
  "name": "re.findall",
  "kind": "INTERNAL",
  "attributes": {
    "re.function": "findall",
    "re.pattern": "\\d+",
    "re.string_length": 8,
    "re.match_count": 3
  }
}
```

## Supported Operations

### Module-level Functions
- `re.search()`
- `re.match()`
- `re.fullmatch()`
- `re.split()`
- `re.findall()` (includes `re.match_count`)
- `re.finditer()`
- `re.sub()`
- `re.subn()` (includes `re.match_count`)

### Compiled Pattern Methods
All methods on `re.Pattern` objects returned by `re.compile()`:
- `pattern.search()`
- `pattern.match()`
- `pattern.fullmatch()`
- `pattern.split()`
- `pattern.findall()` (includes `re.match_count`)
- `pattern.finditer()`
- `pattern.sub()`
- `pattern.subn()` (includes `re.match_count`)

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/nilox94/opentelemetry-instrumentation-re.git
cd opentelemetry-instrumentation-re

# Install dependencies
uv sync --extra dev
```
