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

## Git Hooks (prek)

[prek](https://prek.j178.dev/) runs checks before each commit (Ruff and basic file checks). It’s included as a dev dependency, so after `uv sync --extra dev` you can run:

```bash
# Install git hooks and prepare hook environments (one-time per clone)
uv run prek install --install-hooks
```

After this, every `git commit` will run:

- **pre-commit-hooks** - trailing whitespace, end-of-file fixer, check YAML/TOML, debug statements
- **Ruff** - lint (`--fix`) and format

Tests are run in CI, not in the pre-commit hook. To skip hooks once: `git commit --no-verify`

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
