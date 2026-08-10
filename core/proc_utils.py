"""Cross-platform helpers for running subprocesses that job cancellation
can actually stop.

Converters that shell out (ffmpeg, LibreOffice, Pandoc, Calibre's
``ebook-convert``, ...) should use :func:`run_killable` instead of calling
``subprocess.run``/``subprocess.Popen`` directly. Doing so lets the engine
kill the underlying process (and any children it spawned) the moment a job
is cancelled, instead of only discarding the result after the process runs
to completion on its own.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Optional

from .exceptions import JobCancelledError


def popen_killable(cmd: list[str], **kwargs) -> subprocess.Popen:
    """Start a subprocess in its own process group/session so
    :func:`kill_process_tree` can reliably stop it *and* any children it
    spawns (ffmpeg, LibreOffice, and Calibre all sometimes fork helpers)."""

    if sys.platform == "win32":
        # Needed so CTRL_BREAK_EVENT can be sent to this process (and only
        # this process's group) later, without affecting our own process.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs.setdefault("start_new_session", True)
    return subprocess.Popen(cmd, **kwargs)


def kill_process_tree(proc: subprocess.Popen, timeout: float = 3.0) -> None:
    """Best-effort: ask ``proc`` (and its process group) to exit gracefully,
    then force-kill it if it hasn't exited within ``timeout`` seconds.

    Safe to call multiple times / on an already-exited process.
    """

    if proc.poll() is not None:
        return

    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass

    try:
        proc.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass


class KillableProcessResult:
    """Minimal stand-in for ``subprocess.CompletedProcess`` returned by
    :func:`run_killable`."""

    def __init__(self, args: list[str], returncode: int, stdout: str, stderr: str):
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_killable(
    cmd: list[str],
    progress_cb=None,
    timeout: Optional[float] = None,
    **popen_kwargs,
) -> KillableProcessResult:
    """``subprocess.run``-alike that registers the process with the job's
    cancellation token (if ``progress_cb`` carries one) so cancelling the
    job kills the process instead of letting it run to completion unwatched.

    Raises :class:`~fileconverter.core.exceptions.JobCancelledError` if the
    process was killed because the job was cancelled. Raises
    ``subprocess.TimeoutExpired`` if ``timeout`` elapses first.
    """

    popen_kwargs.setdefault("stdout", subprocess.PIPE)
    popen_kwargs.setdefault("stderr", subprocess.PIPE)
    popen_kwargs.setdefault("text", True)

    proc = popen_killable(cmd, **popen_kwargs)

    register = getattr(progress_cb, "register_process", None)
    unregister = getattr(progress_cb, "unregister_process", None)
    is_cancelled = getattr(progress_cb, "is_cancelled", None)

    if register is not None:
        register(proc)

    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc)
            stdout, stderr = proc.communicate()
            raise
    finally:
        if unregister is not None:
            unregister()

    if is_cancelled is not None and is_cancelled() and proc.returncode not in (0, None):
        raise JobCancelledError("Job cancelled by user")

    return KillableProcessResult(cmd, proc.returncode, stdout or "", stderr or "")
