# auto-forex-core

## Setup

```bash
uv sync
uv run pre-commit install
```

## Development

```bash
uv run ruff check .
uv run ruff format .
uv run ty check
uv run pytest
uv run pre-commit run --all-files
```
