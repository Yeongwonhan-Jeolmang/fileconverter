"""Folder watching: automatically convert files dropped into a directory.

Uses the optional ``watchdog`` package when available for efficient,
event-driven watching. Falls back to simple polling so the feature still
works with zero extra dependencies installed.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .engine import ConversionEngine, build_output_path
from .base import ConversionJob, ConversionOptions

FileHandlerCallback = Callable[[Path], None]


class FolderWatcher:
    """Watches ``folder`` and converts new/modified files to ``target_format``.

    Usage:
        watcher = FolderWatcher(folder, target_format="pdf", engine=engine)
        watcher.start()
        ...
        watcher.stop()
    """

    def __init__(
        self,
        folder: Path,
        target_format: str,
        engine: ConversionEngine,
        options: Optional[dict] = None,
        output_dir: Optional[Path] = None,
        poll_interval: float = 2.0,
        on_new_job: Optional[FileHandlerCallback] = None,
        settle_checks: int = 2,
    ):
        self.folder = Path(folder)
        self.target_format = target_format.lower().lstrip(".")
        self.engine = engine
        self.options = options or {}
        self.output_dir = Path(output_dir) if output_dir else None
        self.poll_interval = poll_interval
        self.on_new_job = on_new_job
        self.settle_checks = max(1, settle_checks)

        self._seen: set[str] = set()
        # path -> (last observed size, number of consecutive polls at that size)
        self._pending_sizes: dict[str, tuple[int, int]] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        # Snapshot existing files so we only react to *new* arrivals.
        self._seen = {str(p) for p in self.folder.iterdir() if p.is_file()}
        self._pending_sizes = {}
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._scan_once()
            except OSError:
                pass
            self._stop_event.wait(self.poll_interval)

    def _scan_once(self) -> None:
        current_keys: set[str] = set()
        for path in self.folder.iterdir():
            if not path.is_file():
                continue
            key = str(path)
            current_keys.add(key)
            if key in self._seen:
                continue
            if path.suffix.lower().lstrip(".") == self.target_format:
                self._seen.add(key)
                continue
            if self._has_settled(key, path):
                self._seen.add(key)
                self._pending_sizes.pop(key, None)
                self._dispatch(path)

        # Stop tracking files that disappeared before settling (e.g. a
        # temp/partial file that got renamed or removed).
        for key in list(self._pending_sizes):
            if key not in current_keys:
                self._pending_sizes.pop(key, None)

    def _has_settled(self, key: str, path: Path) -> bool:
        """True once ``path``'s size has been identical across
        ``self.settle_checks`` consecutive polls, i.e. it looks like
        whatever is writing it has finished."""

        try:
            size = path.stat().st_size
        except OSError:
            return False

        last_size, streak = self._pending_sizes.get(key, (None, 0))
        if size == last_size:
            streak += 1
        else:
            streak = 1
        self._pending_sizes[key] = (size, streak)
        return streak >= self.settle_checks

    def _dispatch(self, path: Path) -> None:
        output_path = build_output_path(path, self.target_format, self.output_dir)
        job = ConversionJob(
            source_path=path,
            output_path=output_path,
            target_format=self.target_format,
            options=ConversionOptions.from_dict(self.options),
        )
        if self.on_new_job:
            self.on_new_job(path)
        self.engine.submit(job)
