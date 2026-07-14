"""Multi-threaded conversion engine.

Both the CLI and GUI submit :class:`ConversionJob` objects here. The engine
resolves a converter from the registry, runs it on a thread pool, verifies
the output, records history, and reports progress back through callbacks
so front-ends never talk to converters directly.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from typing import Callable, Optional

from . import checksums, history
from .base import ConversionJob, ConversionResult
from .exceptions import UnsupportedConversionError
from .formats import detect_format
from .logging_setup import get_logger
from .registry import find_converter

JobProgressCallback = Callable[[str, float, str], None]
"""Signature: callback(job_id, fraction_complete, message) -> None"""

JobDoneCallback = Callable[[ConversionResult], None]


class CancelledError(Exception):
    """Raised internally when a job is cancelled mid-flight."""


class _CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


class ConversionEngine:
    """Owns a thread pool and coordinates running conversion jobs."""

    def __init__(self, max_workers: int = 4, verify_output: bool = True):
        self.max_workers = max(1, max_workers)
        self.verify_output = verify_output
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="fc-worker"
        )
        self._tokens: dict[str, _CancellationToken] = {}
        self._lock = threading.Lock()
        self.logger = get_logger()

    def cancel(self, job_id: str) -> None:
        with self._lock:
            token = self._tokens.get(job_id)
        if token:
            token.cancel()

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def submit(
        self,
        job: ConversionJob,
        on_progress: Optional[JobProgressCallback] = None,
        on_done: Optional[JobDoneCallback] = None,
    ) -> Future:
        token = _CancellationToken()
        with self._lock:
            self._tokens[job.job_id] = token

        def _task() -> ConversionResult:
            result = self._run_job(job, token, on_progress)
            if on_done:
                on_done(result)
            return result

        return self._executor.submit(_task)

    def run_batch(
        self,
        jobs: list[ConversionJob],
        on_progress: Optional[JobProgressCallback] = None,
        on_done: Optional[JobDoneCallback] = None,
    ) -> list[ConversionResult]:
        futures = [self.submit(job, on_progress, on_done) for job in jobs]
        return [f.result() for f in futures]

    # ------------------------------------------------------------------
    def _run_job(
        self,
        job: ConversionJob,
        token: _CancellationToken,
        on_progress: Optional[JobProgressCallback],
    ) -> ConversionResult:
        start = time.monotonic()
        src_format = detect_format(job.source_path)

        def progress(fraction: float, message: str = "") -> None:
            if token.is_cancelled():
                raise CancelledError("Job cancelled by user")
            if on_progress:
                on_progress(job.job_id, fraction, message)

        try:
            if not job.source_path.exists():
                raise FileNotFoundError(f"Source file not found: {job.source_path}")

            converter = find_converter(src_format, job.target_format)
            if converter is None:
                raise UnsupportedConversionError(src_format, job.target_format)

            job.output_path.parent.mkdir(parents=True, exist_ok=True)
            progress(0.0, f"Starting {converter.name}")

            result = converter.convert(job, progress_cb=progress)
            duration = time.monotonic() - start
            result.duration_seconds = duration

            if result.success and self.verify_output and result.output_path:
                ok, reason = checksums.verify_output_file(result.output_path)
                if not ok:
                    result.success = False
                    result.error = f"Output verification failed: {reason}"

            progress(1.0, "Done" if result.success else f"Failed: {result.error}")
            history.record(
                source_path=str(job.source_path),
                output_path=str(result.output_path) if result.output_path else None,
                source_format=src_format,
                target_format=job.target_format,
                success=result.success,
                duration_seconds=duration,
                error=result.error,
            )
            if not result.success:
                self.logger.warning(
                    "Conversion failed for %s: %s", job.source_path, result.error
                )
            return result

        except CancelledError as exc:
            duration = time.monotonic() - start
            history.record(
                str(job.source_path),
                None,
                src_format,
                job.target_format,
                False,
                duration,
                str(exc),
            )
            return ConversionResult(
                job=job,
                success=False,
                message="Cancelled",
                error=str(exc),
                duration_seconds=duration,
            )
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start
            error_message = f"{type(exc).__name__}: {exc}"
            self.logger.exception("Unhandled error converting %s", job.source_path)
            history.record(
                str(job.source_path),
                None,
                src_format,
                job.target_format,
                False,
                duration,
                error_message,
            )
            return ConversionResult(
                job=job,
                success=False,
                message="Failed",
                error=error_message,
                duration_seconds=duration,
            )


def build_output_path(
    source_path: Path, target_format: str, output_dir: Optional[Path] = None
) -> Path:
    """Compute a sensible output path: same stem, new extension, in
    ``output_dir`` if given, else alongside the source file."""

    source_path = Path(source_path)
    target_format = target_format.lower().lstrip(".")
    directory = Path(output_dir) if output_dir else source_path.parent
    candidate = directory / f"{source_path.stem}.{target_format}"
    return _avoid_overwrite(candidate, source_path)


def _avoid_overwrite(candidate: Path, source_path: Path) -> Path:
    if candidate.resolve() != source_path.resolve() and not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    n = 1
    while True:
        alt = candidate.with_name(f"{stem} ({n}){suffix}")
        if not alt.exists() and alt.resolve() != source_path.resolve():
            return alt
        n += 1
