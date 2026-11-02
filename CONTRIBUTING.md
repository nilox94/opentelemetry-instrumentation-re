# Contributing

Pull requests are welcome.

Commit messages use [Conventional Commits](https://www.conventionalcommits.org/). The release process reads that format when it chooses the next version. See [RELEASING.md](RELEASING.md).

## Instrumentation

This package does not register `opentelemetry_instrumentor` entry points and it has no `instruments` extra. Installing it does not patch `re`. Call `ReInstrumentor().instrument()` (or `RegexInstrumentor` / `GoogleRe2Instrumentor`) yourself. Auto-instrumentation and `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS` do not apply.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/nilox94/opentelemetry-instrumentation-re.git
cd opentelemetry-instrumentation-re

uv sync --extra dev --extra test --extra regex --extra google-re2
```

## Git Hooks (prek)

[prek](https://prek.j178.dev/) runs Ruff and basic file checks before each commit. It is a dev dependency. After `uv sync --extra dev`:

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

## Benchmarks

[BENCHMARKS.md](BENCHMARKS.md) is how to read `benchmarks/bench.py`. From the repo root, after the test extra is installed (`regex` and `google-re2` are optional):

```bash
uv sync --extra test --extra regex --extra google-re2
uv run python benchmarks/bench.py
```

A pull request that changes the hot path gets the `benchmark` label before it is merged. Paste the job's `## Snapshot` block into `BENCHMARKS.md` on the same pull request.

## Linting and Type Checking

```bash
# Run Ruff linter
uv run ruff check

# Format code
uv run ruff format

# Run basedpyright type checker
uv run basedpyright
```
