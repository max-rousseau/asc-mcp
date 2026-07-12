# Contributing

## Development Setup

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

## Testing

```bash
./.venv/bin/pytest
```

Tests live under `tests/`, split into `tests/unit/` and `tests/integration/`
(see `pytest` markers `unit` and `integration` in `pyproject.toml`). Coverage
is enforced at 85% (`--cov-fail-under=85`), reported for `src/asc_feedback_mcp`.

## Code Quality

```bash
./.venv/bin/black src tests
./.venv/bin/flake8 src tests
./.venv/bin/vulture src
./.venv/bin/bandit -c pyproject.toml -r src
```

All four are configured in `pyproject.toml` (`[tool.black]`, `[tool.flake8]`,
`[tool.vulture]`, `[tool.bandit]`) — run them before opening a pull request.
