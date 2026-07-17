
# Developing ctl

Dependencies and virtualenvs are managed with [uv](https://docs.astral.sh/uv/).

## setup

```sh
uv sync --all-extras
```

## linting and formatting

```sh
uv run ruff check .
uv run ruff format .
```

## tests

```sh
uv run pytest tests/
```

To test against a specific Python version (uv downloads the interpreter on
demand), use `uv run --python`:

```sh
uv run --python 3.10 pytest tests/
uv run --python 3.14 pytest tests/
```

CI runs the full 3.10–3.14 matrix on every push.
