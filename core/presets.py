"""Named conversion presets (e.g. "Web-optimized JPEG").

Presets bundle a target format + option set under a friendly name so users
don't have to re-type the same flags in the CLI or re-fill the same fields
in the GUI every time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import CONFIG_DIR
from .exceptions import PresetError

PRESETS_FILE = CONFIG_DIR / "presets.json"

BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "web-optimized-jpeg": {
        "target_format": "jpg",
        "options": {"quality": 80, "resize": [1920, 1080], "preserve_metadata": False},
    },
    "lossless-png": {
        "target_format": "png",
        "options": {"preserve_metadata": True},
    },
    "podcast-mp3": {
        "target_format": "mp3",
        "options": {"bitrate": "128k", "sample_rate": 44100},
    },
    "archival-pdf": {
        "target_format": "pdf",
        "options": {"preserve_metadata": True},
    },
    "compact-mp4": {
        "target_format": "mp4",
        "options": {"bitrate": "1500k", "resolution": "1280x720", "fps": 30},
    },
}


@dataclass
class Preset:
    name: str
    target_format: str
    options: dict[str, Any] = field(default_factory=dict)


def _load_raw() -> dict[str, dict[str, Any]]:
    if not PRESETS_FILE.exists():
        return {}
    try:
        return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(data: dict[str, dict[str, Any]]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_presets() -> list[Preset]:
    merged = {**BUILTIN_PRESETS, **_load_raw()}
    return [Preset(name=n, target_format=v["target_format"], options=v.get("options", {})) for n, v in merged.items()]


def get_preset(name: str) -> Preset:
    merged = {**BUILTIN_PRESETS, **_load_raw()}
    if name not in merged:
        raise PresetError(f"No such preset: '{name}'. Run 'fileconverter presets' to list available presets.")
    v = merged[name]
    return Preset(name=name, target_format=v["target_format"], options=v.get("options", {}))


def save_preset(name: str, target_format: str, options: dict[str, Any]) -> None:
    if not name or "/" in name or "\\" in name:
        raise PresetError("Preset name must be a non-empty string without path separators.")
    data = _load_raw()
    data[name] = {"target_format": target_format, "options": options}
    _save_raw(data)


def delete_preset(name: str) -> None:
    if name in BUILTIN_PRESETS:
        raise PresetError(f"'{name}' is a built-in preset and cannot be deleted.")
    data = _load_raw()
    if name not in data:
        raise PresetError(f"No such custom preset: '{name}'.")
    del data[name]
    _save_raw(data)
