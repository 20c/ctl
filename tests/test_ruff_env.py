"""ruff comes from the locked project environment — uv.lock is the single
source of its version (no pin in pyproject.toml or pre-commit; see #43).
This only guards that the environment actually provides it."""

from importlib import metadata


def test_ruff_installed_from_locked_environment():
    assert metadata.version("ruff")
