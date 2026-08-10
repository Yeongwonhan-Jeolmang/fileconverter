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
from typing import Any, Callable, Optional

from . import checksums, history
from .base import ConversionJob, ConversionOptions, ConversionResult
from .exceptions import JobCancelledError, UnsupportedConversionError
from .formats import detect_format
from .logging_setup import get_logger
from .proc_utils import kill_process_tree
from .registry import find_converter

JobProgressCallback = Callable[[str, float, str], None]
"""Signature: callback(job_id, fraction_complete, message) -> None"""

JobDoneCallback = Callable[[ConversionResult], None]
RetryCallback = Callable[[ConversionJob, int], None]
"""Signature: callback(job, attempt_number) -> None, called before each retry."""

# Kept as an alias for backwards compatibility — code (and any external
# callers) that does ``except CancelledError`` continues to work unchanged.
CancelledError = JobCancelledError


class _CancellationToken:
    """Tracks whether a job has been cancelled, and — if a converter has
    registered a running subprocess — makes sure that subprocess actually
    gets killed on cancel, rather than being left to run to completion."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._process: Any = None
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            proc = self._process
        if proc is not None:
            kill_process_tree(proc)

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def register_process(self, proc: Any) -> None:
        """Converters call this (indirectly, via the progress callback)
        right after starting a subprocess so a subsequent ``cancel()`` can
        kill it. If the job was already cancelled before registration
        happens, the process is killed immediately."""

        with self._lock:
            self._process = proc
            already_cancelled = self._event.is_set()
        if already_cancelled:
            kill_process_tree(proc)

    def unregister_process(self) -> None:
        with self._lock:
            self._process = None


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

    def set_max_workers(self, max_workers: int) -> None:
        """Resize the underlying thread pool. Safe to call between batches
        (e.g. when the user changes the 'workers' setting in the GUI)."""

        max_workers = max(1, max_workers)
        if max_workers == self.max_workers:
            return
        old_executor = self._executor
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="fc-worker"
        )
        old_executor.shutdown(wait=False)

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
        max_retries: int = 0,
        retry_delay: float = 1.0,
        on_retry: Optional[RetryCallback] = None,
    ) -> list[ConversionResult]:
        """Run every job, then — if ``max_retries`` > 0 — automatically
        re-run only the ones that failed, up to ``max_retries`` extra
        attempts each, waiting ``retry_delay`` seconds between rounds.

        This is what powers "retry failed only" for a batch: a transient
        failure (a LibreOffice hiccup, a locked file, ffmpeg briefly
        unavailable) doesn't require the caller to re-select files or
        re-run everything that already succeeded. ``on_retry``, if given,
        is called once per job before each retry attempt with
        ``(job, attempt_number)``.

        Returns exactly one :class:`ConversionResult` per input job (its
        most recent attempt), in the same order as ``jobs``.
        """

        results_by_id: dict[str, ConversionResult] = {}
        pending = list(jobs)
        attempt = 0

        while pending:
            futures = {
                job.job_id: self.submit(job, on_progress, on_done) for job in pending
            }
            for job_id, future in futures.items():
                results_by_id[job_id] = future.result()

            if attempt >= max_retries:
                break

            failed_jobs = [
                job for job in pending if not results_by_id[job.job_id].success
            ]
            if not failed_jobs:
                break

            attempt += 1
            if on_retry:
                for job in failed_jobs:
                    on_retry(job, attempt)
            if retry_delay:
                time.sleep(retry_delay)
            pending = failed_jobs

        return [results_by_id[job.job_id] for job in jobs]

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

        # Converters that shell out (video/ebook/document converters, via
        # core.proc_utils.run_killable) look for these attributes so they
        # can register a running subprocess for cancellation. This is the
        # bridge between "job.cancel() was called" and "the ffmpeg/
        # soffice/pandoc/ebook-convert process actually gets killed" —
        # without it, cancelling only discards the result while the
        # subprocess keeps running to completion in the background.
        progress.register_process = token.register_process  # type: ignore[attr-defined]
        progress.unregister_process = token.unregister_process  # type: ignore[attr-defined]
        progress.is_cancelled = token.is_cancelled  # type: ignore[attr-defined]

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


def jobs_from_results_json(
    entries: list[dict[str, Any]], only_failed: bool = True
) -> list[ConversionJob]:
    """Rebuild :class:`ConversionJob` objects from a previous run's
    ``--json-output`` payload (see ``cli.main convert``).

    This is what powers "resume a batch": run a big batch once with
    ``--json-output``, save the results, then feed them back in here to
    get jobs for just the ones that failed (``only_failed=True``, the
    default) without re-selecting files or re-running everything that
    already succeeded.
    """

    jobs: list[ConversionJob] = []
    for entry in entries:
        if only_failed and entry.get("success"):
            continue
        source = entry.get("source")
        target_format = entry.get("target_format")
        if not source or not target_format:
            continue
        source_path = Path(source)
        output = entry.get("output")
        output_path = (
            Path(output) if output else build_output_path(source_path, target_format)
        )
        jobs.append(
            ConversionJob(
                source_path=source_path,
                output_path=output_path,
                target_format=target_format,
                options=ConversionOptions(),
            )
        )
    return jobs


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
