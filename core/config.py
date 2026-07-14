"""Persistent user configuration.

Stored at ``~/.fileconverter/config.json``. Both the GUI and CLI read/write
through this module so settings stay in sync between the two front-ends.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".fileconverter"
CONFIG_FILE = CONFIG_DIR / "config.json"


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
        return cls(**filtered)


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists():
        return AppConfig()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return AppConfig.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return AppConfig()


def save_config(config: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")


def add_recent_file(config: AppConfig, path: str, limit: int = 20) -> AppConfig:
    files = [path] + [p for p in config.recent_files if p != path]
    config.recent_files = files[:limit]
    return config
