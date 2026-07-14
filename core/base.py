"""Core data structures and the BaseConverter contract that every format
plugin implements.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

ProgressCallback = Optional[Callable[[float, str], None]]
"""Signature: callback(fraction_complete: 0.0-1.0, message: str) -> None"""


@dataclass
class ConversionOptions:
    """Free-form, converter-specific options.

    Common keys used across converters (all optional):
      - quality: int (1-100) — lossy image/audio/video quality
      - resize: tuple[int, int] — target (width, height) for images/video
      - bitrate: str — e.g. "192k" for audio/video
      - sample_rate: int — audio sample rate in Hz
      - fps: int — video frame rate
      - resolution: str — e.g. "1280x720"
      - delimiter: str — spreadsheet delimiter override
      - sheet_name: str | int — spreadsheet sheet selector
      - page_range: str — e.g. "1-3,5" for PDFs
      - overwrite: bool — allow overwriting an existing output file
      - preserve_metadata: bool — keep EXIF/ID3/document metadata when possible
    """

    values: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.values

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "ConversionOptions":
        return cls(values=dict(data or {}))


@dataclass
class ConversionJob:
    """A single unit of work: convert one file to one target format."""

    source_path: Path
    output_path: Path
    target_format: str
    options: ConversionOptions = field(default_factory=ConversionOptions)
    job_id: str = ""

    def __post_init__(self) -> None:
        self.source_path = Path(self.source_path)
        self.output_path = Path(self.output_path)
        if not self.job_id:
            self.job_id = f"{self.source_path.name}->{self.target_format}-{id(self)}"


@dataclass
class ConversionResult:
    """Outcome of running a :class:`ConversionJob`."""

    job: ConversionJob
    success: bool
    message: str = ""
    error: Optional[str] = None
    duration_seconds: float = 0.0
    output_path: Optional[Path] = None

    @property
    def source_path(self) -> Path:
        return self.job.source_path


class BaseConverter:
    """Subclass this for every new format converter.

    Required class attributes:
      - name: human-readable converter name, e.g. "Image Converter"
      - input_formats: lowercase extensions this converter can read (no dot)
      - output_formats: lowercase extensions this converter can write (no dot)

    Required method:
      - convert(job, progress_cb) -> ConversionResult
    """

    name: str = "Unnamed Converter"
    input_formats: frozenset[str] = frozenset()
    output_formats: frozenset[str] = frozenset()
    #  Human-readable description shown in GUI/CLI "formats" listings.
    description: str = ""

    def can_convert(self, src_format: str, dst_format: str) -> bool:
        src_format = src_format.lower().lstrip(".")
        dst_format = dst_format.lower().lstrip(".")
        return src_format in self.input_formats and dst_format in self.output_formats

    def check_available(self) -> tuple[bool, str]:
        """Return (available, reason). Override to check optional deps
        (e.g. ffmpeg on PATH) without raising. Used by ``doctor`` command."""

        return True, "OK"

    def convert(self, job: ConversionJob, progress_cb: ProgressCallback = None) -> ConversionResult:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------
    def _run_timed(self, job: ConversionJob, fn: Callable[[], Any]) -> ConversionResult:
        """Run ``fn`` (the actual conversion body), timing it and wrapping
        any exception into a failed ConversionResult instead of raising."""

        start = time.monotonic()
        try:
            fn()
            duration = time.monotonic() - start
            return ConversionResult(
                job=job,
                success=True,
                message=f"Converted successfully in {duration:.2f}s",
                duration_seconds=duration,
                output_path=job.output_path,
            )
        except Exception as exc:  # noqa: BLE001 — convert to structured result
            duration = time.monotonic() - start
            return ConversionResult(
                job=job,
                success=False,
                message="Conversion failed",
                error=f"{type(exc).__name__}: {exc}",
                duration_seconds=duration,
            )
