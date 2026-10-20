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

    def cancel_all(self) -> None:
        """Cancel every job that is queued or running on this engine."""

        with self._lock:
            tokens = list(self._tokens.values())
        for token in tokens:
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
            try:
                result = self._run_job(job, token, on_progress)
            finally:
                # Drop the token once the job is finished so a long-running
                # GUI session doesn't accumulate one per job ever submitted.
                with self._lock:
                    if self._tokens.get(job.job_id) is token:
                        del self._tokens[job.job_id]
            if on_done:
                try:
                    on_done(result)
                except Exception:  # noqa: BLE001 — a UI callback bug must not lose the result
                    self.logger.exception("on_done callback raised for %s", job.job_id)
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

            # Retry real failures only — a job the user cancelled should stay
            # cancelled rather than being started again.
            failed_jobs = [
                job
                for job in pending
                if not results_by_id[job.job_id].success
                and results_by_id[job.job_id].message != "Cancelled"
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
        job.source_format = src_format
        output_existed_before = job.output_path.exists()

        def cleanup_partial_output() -> None:
            # Never leave a truncated/half-written file behind after a
            # failure or cancel — but only remove a file this job created.
            if output_existed_before:
                return
            try:
                if job.output_path.is_file():
                    job.output_path.unlink()
            except OSError:
                pass

        def progress(fraction: float, message: str = "") -> None:
            if token.is_cancelled():
                raise CancelledError("Job cancelled by user")
            if on_progress:
                try:
                    on_progress(job.job_id, fraction, message)
                except Exception:  # noqa: BLE001 — a UI callback bug must not fail the job
                    self.logger.exception("on_progress callback raised for %s", job.job_id)

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

            if not result.success and token.is_cancelled():
                # The subprocess was killed by cancel() and exited non-zero;
                # report it as a cancellation rather than a conversion error.
                raise CancelledError("Job cancelled by user")

            if on_progress:
                # Report completion directly rather than via progress(): a
                # cancel that arrives after the output was fully written
                # shouldn't retroactively turn a finished job into "Cancelled".
                try:
                    on_progress(
                        job.job_id,
                        1.0,
                        "Done" if result.success else f"Failed: {result.error}",
                    )
                except Exception:  # noqa: BLE001
                    self.logger.exception("on_progress callback raised for %s", job.job_id)
            _record_history(
                source_path=str(job.source_path),
                output_path=str(result.output_path) if result.output_path else None,
                source_format=src_format,
                target_format=job.target_format,
                success=result.success,
                duration_seconds=duration,
                error=result.error,
            )
            if not result.success:
                cleanup_partial_output()
                result.output_path = None
                self.logger.warning(
                    "Conversion failed for %s: %s", job.source_path, result.error
                )
            return result

        except CancelledError as exc:
            duration = time.monotonic() - start
            cleanup_partial_output()
            _record_history(
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
            cleanup_partial_output()
            _record_history(
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


def _record_history(*args: Any, **kwargs: Any) -> None:
    """Record to the history DB without ever letting a history failure
    (locked/corrupt DB, read-only home dir, ...) change a job's outcome."""

    try:
        history.record(*args, **kwargs)
    except Exception:  # noqa: BLE001
        get_logger().exception("Could not write conversion history entry")


_OVERWRITE_POLICIES = frozenset({"ask", "overwrite", "skip", "rename"})


def _output_stem(source_path: Path) -> str:
    """Output file stem for ``source_path``. Multi-part archive suffixes are
    stripped as a whole so ``backup.tar.gz`` -> ``backup.zip``, not
    ``backup.tar.zip``."""

    name = source_path.name
    lowered = name.lower()
    for multi in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if lowered.endswith(multi) and len(name) > len(multi):
            return name[: -len(multi)]
    return source_path.stem if source_path.suffix else name


def _output_suffix(target_format: str) -> str:
    """File suffix for a target format; the tar flavours get their
    conventional double extension (``gz`` -> ``.tar.gz``)."""

    return {"gz": "tar.gz", "bz2": "tar.bz2", "xz": "tar.xz"}.get(
        target_format, target_format
    )


def _default_output_candidate(
    source_path: Path, target_format: str, output_dir: Optional[Path]
) -> Path:
    directory = Path(output_dir) if output_dir else source_path.parent
    if target_format == "folder":
        # Extracting an archive: a folder named after it, no extension.
        return directory / _output_stem(source_path)
    return directory / f"{_output_stem(source_path)}.{_output_suffix(target_format)}"


def build_output_path(
    source_path: Path,
    target_format: str,
    output_dir: Optional[Path] = None,
    overwrite_policy: str = "rename",
    reserved: Optional[set[Path]] = None,
) -> Optional[Path]:
    """Compute a sensible output path: same stem, new extension, in
    ``output_dir`` if given, else alongside the source file.

    ``reserved`` is an optional set of output paths already claimed by
    *other jobs in the same batch* (which don't exist on disk yet). Pass the
    same set for every file in a batch so two sources with the same stem
    (``a/photo.png`` and ``b/photo.png`` into one ``--output-dir``) don't
    both get ``photo.jpg`` and silently overwrite each other. The chosen
    path is added to the set.
    """

    source_path = Path(source_path)
    target_format = target_format.lower().lstrip(".")
    candidate = _default_output_candidate(source_path, target_format, output_dir)
    reserved_resolved = {p.resolve() for p in reserved} if reserved else set()

    same_as_source = candidate.resolve() == source_path.resolve()
    taken_in_batch = candidate.resolve() in reserved_resolved
    conflict = same_as_source or taken_in_batch or candidate.exists()

    if not conflict:
        result: Optional[Path] = candidate
    elif overwrite_policy == "overwrite" and not same_as_source and not taken_in_batch:
        result = candidate
    elif overwrite_policy == "skip" and not taken_in_batch:
        result = None
    else:
        # "rename", "ask" (unresolved), "overwrite" when the candidate *is*
        # the source file, and any clash with another job in this batch
        # all fall back to the safe, non-destructive default.
        result = _avoid_overwrite(candidate, source_path, reserved_resolved)

    if result is not None and reserved is not None:
        reserved.add(result)
    return result


def output_conflict(
    source_path: Path, target_format: str, output_dir: Optional[Path] = None
) -> Optional[Path]:
    """Return the output path a plain conversion *would* land on if it
    already exists (or would collide with the source file itself), else
    ``None``. Used by front ends to decide whether an ``overwrite_policy ==
    "ask"`` conflict-resolution prompt is actually needed for a given file,
    without committing to a rename/overwrite/skip decision yet."""

    source_path = Path(source_path)
    target_format = target_format.lower().lstrip(".")
    candidate = _default_output_candidate(source_path, target_format, output_dir)
    if candidate.resolve() == source_path.resolve() or candidate.exists():
        return candidate
    return None


def jobs_from_results_json(
    entries: list[dict[str, Any]], only_failed: bool = True
) -> list[ConversionJob]:
    """Rebuild :class:`ConversionJob` objects from a previous run's
    ``--json-output`` payload (see ``cli.main convert``).
    """

    jobs: list[ConversionJob] = []
    reserved: set[Path] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if only_failed and entry.get("success"):
            continue
        source = entry.get("source")
        target_format = entry.get("target_format")
        if not source or not target_format:
            continue
        source_path = Path(source)
        output = entry.get("output")
        output_path = (
            Path(output)
            if output
            else build_output_path(source_path, target_format, reserved=reserved)
        )
        if output_path is None:
            continue
        # Results files written by newer versions carry the original
        # options, so a retry converts with the same quality/preset settings
        # as the first attempt instead of silently falling back to defaults.
        options = entry.get("options")
        jobs.append(
            ConversionJob(
                source_path=source_path,
                output_path=output_path,
                target_format=target_format,
                options=ConversionOptions.from_dict(
                    options if isinstance(options, dict) else None
                ),
            )
        )
    return jobs


def _avoid_overwrite(
    candidate: Path, source_path: Path, reserved: Optional[set[Path]] = None
) -> Path:
    reserved = reserved or set()
    source_resolved = source_path.resolve()

    def _free(path: Path) -> bool:
        resolved = path.resolve()
        return (
            not path.exists()
            and resolved != source_resolved
            and resolved not in reserved
        )

    if _free(candidate):
        return candidate
    # Keep multi-part suffixes together: "backup (1).tar.gz", not "backup.tar (1).gz".
    name = candidate.name
    stem, suffix = candidate.stem, candidate.suffix
    for multi in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.lower().endswith(multi):
            stem, suffix = name[: -len(multi)], name[-len(multi):]
            break
    n = 1
    while True:
        alt = candidate.with_name(f"{stem} ({n}){suffix}")
        if _free(alt):
            return alt
        n += 1
