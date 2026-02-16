# Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/nilox94/opentelemetry-instrumentation-re.git
cd opentelemetry-instrumentation-re

# Install dependencies
uv sync --extra dev
```

## Running Tests

```bash
# Install test dependencies
uv sync --extra test

# Run tests
uv run pytest tests/

# Run with coverage
uv run pytest --cov=src/opentelemetry_instrumentation_re tests/
```

## Linting and Type Checking

```bash
# Run Ruff linter
uv run ruff check

# Format code
uv run ruff format

# Run basedpyright type checker
uv run basedpyright
```
