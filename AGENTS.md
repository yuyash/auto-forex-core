# Core Package Guide

`core` is the AutoForexV2 domain library.

## Responsibilities

- Provide reusable domain models, calculations, backtesting logic, and trading
  task primitives.
- Keep logic deterministic and testable where possible.
- Use `pydantic` for structured domain/config data and `numpy`/`pandas` for
  market data and backtesting workflows.

## Boundaries

- Do not depend on `api`, `server`, `web`, `openapi`, `protobuf`, or `oanda`.
- Do not perform network I/O, OANDA calls, FastAPI handling, or gRPC handling.
- Keep process orchestration outside this package.

## Commands

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run ty check
uv run pytest
```
