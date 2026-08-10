"""Persistent user configuration.

Stored at ``~/.fileconverter/config.json``. Both the GUI and CLI read/write
through this module so settings stay in sync between the two front-ends.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".fileconverter"
CONFIG_FILE = CONFIG_DIR / "config.json"

_VALID_THEMES = frozenset({"dark", "light", "system"})
_VALID_OVERWRITE_POLICIES = frozenset({"ask", "overwrite", "skip", "rename"})
_MAX_WORKERS_RANGE = (1, 64)
_logger = logging.getLogger("fileconverter")


@dataclass
class AppConfig:
    theme: str = "dark"  # "dark" | "light" | "system"
    default_output_dir: str | None = None  # None => same folder as input
    max_workers: int = 4
    overwrite_policy: str = "ask"  # "ask" | "overwrite" | "skip" | "rename"
    preserve_metadata: bool = True
    last_target_format: str | None = None
    recent_files: list[str] = field(default_factory=list)
    verify_output: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        validated, warnings = _validate_and_coerce(filtered)
        for message in warnings:
            _logger.warning("config: %s", message)
        return cls(**validated)


def _validate_and_coerce(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Check every field's type/range and coerce anything invalid back to
    its schema default, rather than letting bad data (a corrupted
    ``config.json``, or one hand-edited by the user) surface as a
    confusing crash somewhere far away — e.g. ``max_workers: "oops"``
    previously only failed once it reached ``ThreadPoolExecutor``.

    Returns ``(coerced_data, warnings)``; each warning describes exactly
    which field was invalid and what it was reset to, so a bad config file
    is fixable instead of a silent mystery.
    """

    result = dict(data)
    warnings: list[str] = []

    def _reset(key: str, reason: str, default: Any) -> None:
        warnings.append(f"field '{key}' {reason} — using default {default!r}.")
        result[key] = default

    if "theme" in result and result["theme"] not in _VALID_THEMES:
        _reset(
            "theme",
            f"has invalid value {result['theme']!r} (must be one of {sorted(_VALID_THEMES)})",
            "dark",
        )

    if "max_workers" in result:
        max_workers = result["max_workers"]
        lo, hi = _MAX_WORKERS_RANGE
        if isinstance(max_workers, bool) or not isinstance(max_workers, int):
            _reset("max_workers", f"is not an integer ({max_workers!r})", 4)
        elif not (lo <= max_workers <= hi):
            _reset(
                "max_workers",
                f"is out of range ({max_workers!r}, must be {lo}-{hi})",
                4,
            )

    if (
        "overwrite_policy" in result
        and result["overwrite_policy"] not in _VALID_OVERWRITE_POLICIES
    ):
        _reset(
            "overwrite_policy",
            f"has invalid value {result['overwrite_policy']!r} "
            f"(must be one of {sorted(_VALID_OVERWRITE_POLICIES)})",
            "ask",
        )

    for bool_key in ("preserve_metadata", "verify_output"):
        if bool_key in result and not isinstance(result[bool_key], bool):
            _reset(bool_key, f"is not a boolean ({result[bool_key]!r})", True)

    for str_or_none_key in ("default_output_dir", "last_target_format"):
        if str_or_none_key in result:
            value = result[str_or_none_key]
            if value is not None and not isinstance(value, str):
                _reset(str_or_none_key, f"is not a string or null ({value!r})", None)

    if "recent_files" in result:
        recent_files = result["recent_files"]
        if not isinstance(recent_files, list) or not all(
            isinstance(item, str) for item in recent_files
        ):
            _reset("recent_files", f"is not a list of strings ({recent_files!r})", [])

    return result, warnings


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists():
        return AppConfig()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _logger.warning(
            "config: could not read %s (%s) — using defaults.", CONFIG_FILE, exc
        )
        return AppConfig()
    if not isinstance(data, dict):
        _logger.warning(
            "config: %s did not contain a JSON object — using defaults.", CONFIG_FILE
        )
        return AppConfig()
    return AppConfig.from_dict(data)


def save_config(config: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")


def add_recent_file(config: AppConfig, path: str, limit: int = 20) -> AppConfig:
    files = [path] + [p for p in config.recent_files if p != path]
    config.recent_files = files[:limit]
    return config
