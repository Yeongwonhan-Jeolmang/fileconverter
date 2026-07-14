"""Audio conversion via pydub (wraps the ffmpeg/avconv binary).

Requires an ffmpeg (or libav) binary on PATH — this is checked explicitly
and reported with a clear, actionable error rather than a cryptic
subprocess failure.
"""

from __future__ import annotations

import shutil
from typing import cast

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import MissingDependencyError
from ..core.registry import register

_AUDIO_FORMATS = frozenset({"mp3", "wav", "ogg", "flac", "aac", "m4a", "wma", "aiff"})


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class AudioConverter(BaseConverter):
    name = "Audio Converter"
    description = "Converts between MP3, WAV, OGG, FLAC, AAC, M4A, WMA, AIFF. Requires ffmpeg on PATH."
    input_formats = _AUDIO_FORMATS
    output_formats = _AUDIO_FORMATS

    def check_available(self) -> tuple[bool, str]:
        if not _ffmpeg_available():
            return (
                False,
                "ffmpeg not found on PATH. Install from https://ffmpeg.org/download.html",
            )
        try:
            import pydub  # noqa: F401
        except ImportError:
            return False, "Install with: pip install pydub"
        return True, "OK"

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            if not _ffmpeg_available():
                raise MissingDependencyError(
                    "ffmpeg",
                    "Install from https://ffmpeg.org/download.html and ensure it is on PATH.",
                )
            try:
                from pydub import AudioSegment
            except ImportError as exc:
                raise MissingDependencyError(
                    "pydub", "Install with: pip install pydub"
                ) from exc

            src_ext = job.source_path.suffix.lower().lstrip(".")
            target = job.target_format.lower().lstrip(".")
            options = job.options

            if progress_cb:
                progress_cb(0.1, "Decoding audio")

            audio_format = "m4a" if src_ext == "m4a" else src_ext
            segment = cast(
                AudioSegment,
                AudioSegment.from_file(job.source_path, format=audio_format),
            )

            sample_rate = options.get("sample_rate")
            if sample_rate:
                segment = segment.set_frame_rate(int(sample_rate))

            channels = options.get("channels")
            if channels:
                segment = segment.set_channels(int(channels))

            gain_db = options.get("gain_db")
            if gain_db:
                segment = segment.apply_gain(float(gain_db))

            export_kwargs: dict = {}
            bitrate = options.get("bitrate")
            if bitrate:
                export_kwargs["bitrate"] = str(bitrate)

            if progress_cb:
                progress_cb(0.6, "Encoding output")

            export_format = "mp4" if target == "m4a" else target
            segment.export(job.output_path, format=export_format, **export_kwargs)

            if progress_cb:
                progress_cb(0.95, "Done")

        return self._run_timed(job, _do)


register(AudioConverter())
