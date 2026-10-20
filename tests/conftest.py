"""Shared pytest setup.

Every test runs with ``HOME`` pointed at a temporary directory so config,
presets, and the history database never touch the real
``~/.fileconverter``. The package's paths are computed from
``Path.home()`` at import time, so they're also patched per test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_importable() -> None:
    """Make ``import fileconverter`` work from a plain source checkout
    (the repo root *is* the package), without requiring ``pip install -e``."""

    try:
        import fileconverter  # noqa: F401
        return
    except ImportError:
        pass
    spec = importlib.util.spec_from_file_location(
        "fileconverter",
        _REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(_REPO_ROOT)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fileconverter"] = module
    spec.loader.exec_module(module)


_ensure_importable()

import fileconverter.converters  # noqa: E402,F401 — registers every converter
from fileconverter.core import config, history, logging_setup, presets  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / ".fileconverter"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", config_dir / "config.json")
    monkeypatch.setattr(history, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(history, "HISTORY_DB", config_dir / "history.sqlite3")
    monkeypatch.setattr(presets, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(presets, "PRESETS_FILE", config_dir / "presets.json")
    monkeypatch.setattr(logging_setup, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(logging_setup, "LOG_FILE", config_dir / "fileconverter.log")
    return home


@pytest.fixture
def work(tmp_path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path
