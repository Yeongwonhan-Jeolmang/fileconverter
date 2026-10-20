"""Shared helpers for converters that drive the ``ffmpeg`` binary.

Both the audio and video converters run ffmpeg the same way: as a killable
subprocess (so cancelling a job really stops it), parsing its stderr for
``Duration:`` / ``time=`` to report progress, and keeping only the tail of
its output for error messages (so a multi-hour encode doesn't buffer
megabytes of log lines in memory).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import deque
from typing import Optional

from .base import ProgressCallback
from .exceptions import ConversionFailedError, JobCancelledError, MissingDependencyError
from .proc_utils import kill_process_tree, popen_killable

FFMPEG_INSTALL_HINT = (
    "Install from https://ffmpeg.org/download.html and ensure it is on PATH."
)

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_TIME_RE = re.compile(r"time=\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def find_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def require_ffmpeg() -> str:
    path = find_ffmpeg()
    if path is None:
        raise MissingDependencyError("ffmpeg", FFMPEG_INSTALL_HINT)
    return path


def _seconds(match: "re.Match[str]") -> float:
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def run_ffmpeg(
    cmd: list[str],
    progress_cb: ProgressCallback = None,
    start_fraction: float = 0.1,
    end_fraction: float = 0.95,
    message: str = "Encoding",
) -> None:
    """Run an ffmpeg command line to completion, reporting progress through
    ``progress_cb`` and raising on failure/cancellation."""

    process = popen_killable(
        cmd,
        stdin=subprocess.DEVNULL,  # never let ffmpeg wait on an "Overwrite? [y/N]" prompt
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    register = getattr(progress_cb, "register_process", None)
    unregister = getattr(progress_cb, "unregister_process", None)
    is_cancelled = getattr(progress_cb, "is_cancelled", None)
    if register is not None:
        register(process)

    duration_seconds: Optional[float] = None
    tail: deque[str] = deque(maxlen=25)
    cancelled = False
    span = end_fraction - start_fraction

    try:
        assert process.stdout is not None
        # Text mode uses universal newlines, so ffmpeg's "\r"-separated
        # progress updates arrive here as individual lines.
        for line in process.stdout:
            tail.append(line)
            if duration_seconds is None:
                match = _DURATION_RE.search(line)
                if match:
                    duration_seconds = _seconds(match) or None
            time_match = _TIME_RE.search(line)
            if time_match and duration_seconds and progress_cb:
                elapsed = _seconds(time_match)
                fraction = start_fraction + span * min(1.0, elapsed / duration_seconds)
                try:
                    progress_cb(fraction, message)
                except JobCancelledError:
                    cancelled = True
                    kill_process_tree(process)
                    break
    finally:
        if unregister is not None:
            unregister()

    return_code = process.wait()

    if cancelled or (
        return_code != 0 and is_cancelled is not None and is_cancelled()
    ):
        raise JobCancelledError("Job cancelled by user")

    if return_code != 0:
        raise ConversionFailedError(
            f"ffmpeg exited with code {return_code}:\n{''.join(tail).strip()}"
        )
