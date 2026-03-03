# Contributing

## Local setup

```bash
uv sync --group dev
uv run pre-commit install
```

## Required checks

Run these before opening a pull request:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/xolt
uv run pytest
uv run python -m build
```

## Pull requests

- Keep changes focused.
- Add or update tests for behavior changes.
- Update docs and examples when public behavior changes.
- Do not introduce new backend or runtime adapters without a clear public interface boundary.
