"""Conversion history log backed by SQLite.

Every conversion (success or failure) is recorded so the GUI can show a
browsable history and the CLI can export it (``fileconverter history``).
"""

from __future__ import annotations

import csv
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import CONFIG_DIR

HISTORY_DB = CONFIG_DIR / "history.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    source_path TEXT NOT NULL,
    output_path TEXT,
    source_format TEXT,
    target_format TEXT,
    success INTEGER NOT NULL,
    duration_seconds REAL,
    error TEXT
);
"""


@dataclass
class HistoryEntry:
    id: int
    timestamp: float
    source_path: str
    output_path: Optional[str]
    source_format: Optional[str]
    target_format: Optional[str]
    success: bool
    duration_seconds: Optional[float]
    error: Optional[str]


def _connect() -> sqlite3.Connection:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB)
    conn.execute(_SCHEMA)
    return conn


def record(
    source_path: str,
    output_path: str | None,
    source_format: str | None,
    target_format: str | None,
    success: bool,
    duration_seconds: float | None,
    error: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO history
               (timestamp, source_path, output_path, source_format,
                target_format, success, duration_seconds, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                str(source_path),
                str(output_path) if output_path else None,
                source_format,
                target_format,
                1 if success else 0,
                duration_seconds,
                error,
            ),
        )


def recent(limit: int = 100) -> list[HistoryEntry]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM history ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        HistoryEntry(
            id=r[0],
            timestamp=r[1],
            source_path=r[2],
            output_path=r[3],
            source_format=r[4],
            target_format=r[5],
            success=bool(r[6]),
            duration_seconds=r[7],
            error=r[8],
        )
        for r in rows
    ]


def clear() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM history")


def export_csv(path: str | Path, limit: int = 10_000) -> Path:
    path = Path(path)
    entries = recent(limit=limit)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "timestamp",
                "source_path",
                "output_path",
                "source_format",
                "target_format",
                "success",
                "duration_seconds",
                "error",
            ]
        )
        for e in entries:
            writer.writerow(
                [
                    e.timestamp,
                    e.source_path,
                    e.output_path,
                    e.source_format,
                    e.target_format,
                    e.success,
                    e.duration_seconds,
                    e.error,
                ]
            )
    return path
