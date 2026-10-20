"""Audio conversion by driving the ffmpeg binary directly.

This used to go through ``pydub``, which (a) no longer imports on Python
3.13+ (it relies on the removed ``audioop`` module), (b) decodes the whole
file into memory, and (c) passed the file extension straight to ffmpeg's
``-f`` flag, which broke AAC and WMA output (ffmpeg calls those muxers
``adts`` and ``asf``). Calling ffmpeg ourselves fixes all three and also
gives audio jobs real progress reporting and cancellation.

Options:
  - bitrate: str — e.g. "192k"
  - sample_rate: int — e.g. 44100
  - channels: int — 1 (mono) or 2 (stereo)
  - gain_db: float — volume adjustment in decibels, e.g. -3 or 6
  - audio_codec: str — override ffmpeg's default codec, e.g. "libopus"
"""

from __future__ import annotations

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.ffmpeg_utils import FFMPEG_INSTALL_HINT, find_ffmpeg, require_ffmpeg, run_ffmpeg
from ..core.registry import register

_AUDIO_FORMATS = frozenset({"mp3", "wav", "ogg", "flac", "aac", "m4a", "wma", "aiff", "opus"})

# Target extension -> ffmpeg muxer name (they don't always match).
_MUXER_FOR_TARGET = {
    "mp3": "mp3",
    "wav": "wav",
    "ogg": "ogg",
    "flac": "flac",
    "aac": "adts",
    "m4a": "ipod",
    "wma": "asf",
    "aiff": "aiff",
    "opus": "opus",
}


def build_audio_args(target: str, options) -> list[str]:
    """ffmpeg output arguments shared by audio conversion and video -> audio
    extraction."""

    args = ["-vn"]  # drop cover art / video streams
    # ffmpeg picks a sensible default codec per container (libmp3lame for
    # mp3, aac for m4a, ...); "audio_codec" lets the user override it.
    codec = options.get("audio_codec")
    if codec:
        args += ["-c:a", str(codec)]
    bitrate = options.get("bitrate")
    if bitrate:
        args += ["-b:a", str(bitrate)]
    sample_rate = options.get("sample_rate")
    if sample_rate:
        args += ["-ar", str(int(sample_rate))]
    channels = options.get("channels")
    if channels:
        args += ["-ac", str(int(channels))]
    gain_db = options.get("gain_db")
    if gain_db:
        args += ["-af", f"volume={float(gain_db)}dB"]
    muxer = _MUXER_FOR_TARGET.get(target)
    if muxer:
        args += ["-f", muxer]
    return args


class AudioConverter(BaseConverter):
    name = "Audio Converter"
    description = (
        "Converts between MP3, WAV, OGG, OPUS, FLAC, AAC, M4A, WMA, AIFF. "
        "Requires ffmpeg on PATH."
    )
    input_formats = _AUDIO_FORMATS
    output_formats = _AUDIO_FORMATS

    def check_available(self) -> tuple[bool, str]:
        if find_ffmpeg() is None:
            return False, f"ffmpeg not found on PATH. {FFMPEG_INSTALL_HINT}"
        return True, "OK"

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            ffmpeg = require_ffmpeg()
            target = job.target_format.lower().lstrip(".")
            cmd = [ffmpeg, "-hide_banner", "-y", "-i", str(job.source_path)]
            cmd += build_audio_args(target, job.options)
            cmd.append(str(job.output_path))

            if progress_cb:
                progress_cb(0.1, "Encoding audio")
            run_ffmpeg(cmd, progress_cb)

        return self._run_timed(job, _do)


register(AudioConverter())
