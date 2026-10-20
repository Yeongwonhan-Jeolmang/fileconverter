"""Folder watching: automatically convert files dropped into a directory.

Uses lightweight polling (no extra dependencies): the folder is re-scanned
every ``poll_interval`` seconds, and a new file is only converted once its
size has stopped changing, so half-written files aren't picked up.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from .base import ConversionJob, ConversionOptions
from .engine import ConversionEngine, build_output_path
from .formats import detect_format
from .logging_setup import get_logger
from .registry import find_converter

# In-progress downloads / editor lock files that should never be converted.
_IGNORED_SUFFIXES = frozenset(
    {"part", "partial", "crdownload", "download", "tmp", "temp", "swp", "lock"}
)
_IGNORED_NAMES = frozenset({"thumbs.db", "desktop.ini"})

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
        overwrite_policy: str = "rename",
    ):
        self.folder = Path(folder)
        self.target_format = target_format.lower().lstrip(".")
        self.engine = engine
        self.options = options or {}
        self.output_dir = Path(output_dir) if output_dir else None
        self.poll_interval = poll_interval
        self.on_new_job = on_new_job
        self.overwrite_policy = (
            "rename" if overwrite_policy == "ask" else overwrite_policy
        )
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
            except Exception:  # noqa: BLE001 — keep watching no matter what
                get_logger().exception("Folder watcher scan failed for %s", self.folder)
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
            if self._should_ignore(path):
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

    def _should_ignore(self, path: Path) -> bool:
        name = path.name
        suffix = path.suffix.lower().lstrip(".")
        if name.startswith((".", "~$")) or name.lower() in _IGNORED_NAMES:
            return True
        if suffix in _IGNORED_SUFFIXES:
            return True
        # Already in the target format (including outputs we wrote here).
        if suffix == self.target_format or name.lower().endswith(
            f".tar.{self.target_format}"
        ):
            return True
        return False

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
        if find_converter(detect_format(path), self.target_format) is None:
            # Nothing can convert this file type to the target; don't
            # flood the history with guaranteed failures.
            get_logger().info(
                "Watcher: no converter for %s -> %s, ignoring.", path.name, self.target_format
            )
            return
        output_path = build_output_path(
            path,
            self.target_format,
            self.output_dir,
            overwrite_policy=self.overwrite_policy,
        )
        if output_path is None:
            # overwrite_policy == "skip" and the output already exists.
            return
        job = ConversionJob(
            source_path=path,
            output_path=output_path,
            target_format=self.target_format,
            options=ConversionOptions.from_dict(self.options),
        )
        if self.on_new_job:
            self.on_new_job(path)
        self.engine.submit(job)
