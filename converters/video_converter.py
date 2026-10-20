"""Video conversion by shelling out to the ffmpeg binary directly.

We avoid a heavy Python video library and instead drive ffmpeg via
subprocess, this keeps the dependency footprint small while supporting
essentially every container/codec ffmpeg supports, including:
  - video <-> video (mp4/avi/mov/mkv/webm/flv/wmv/m4v)
  - video -> gif (animated preview export, with a generated palette)
  - video -> mp3/wav/aac/flac/m4a/ogg (audio extraction)

Options:
  - resolution: str — e.g. "1280x720" (use -1 for one side to keep aspect)
  - fps: int — output frame rate
  - bitrate: str — video bitrate (audio bitrate when extracting audio)
  - video_codec: str — override ffmpeg's default video codec
"""

from __future__ import annotations

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.ffmpeg_utils import FFMPEG_INSTALL_HINT, find_ffmpeg, require_ffmpeg, run_ffmpeg
from ..core.registry import register
from .audio_converter import build_audio_args

_VIDEO_FORMATS = frozenset({"mp4", "avi", "mov", "mkv", "webm", "flv", "wmv", "m4v"})
_AUDIO_EXTRACT_FORMATS = frozenset({"mp3", "wav", "aac", "flac", "m4a", "ogg"})


def _scale_filter(resolution: str) -> str:
    """"1280x720" / "1280:720" / "1280x-1" -> an ffmpeg scale filter. A
    fixed size is fitted inside the box (aspect ratio preserved) and
    rounded to even dimensions, which most encoders (e.g. H.264) require."""

    width, _, height = str(resolution).lower().replace(":", "x").partition("x")
    width, height = width.strip() or "-1", height.strip() or "-1"
    if width == "-1" or height == "-1":
        width = "-2" if width == "-1" else width
        height = "-2" if height == "-1" else height
        return f"scale={width}:{height}"
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )


class VideoConverter(BaseConverter):
    name = "Video Converter"
    description = (
        "Converts between MP4, AVI, MOV, MKV, WEBM, FLV, WMV, M4V; exports GIFs and "
        "extracts audio tracks. Requires ffmpeg on PATH."
    )
    input_formats = _VIDEO_FORMATS
    output_formats = _VIDEO_FORMATS | {"gif"} | _AUDIO_EXTRACT_FORMATS

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
            options = job.options
            cmd = [ffmpeg, "-hide_banner", "-y", "-i", str(job.source_path)]

            if target in _AUDIO_EXTRACT_FORMATS:
                cmd += build_audio_args(target, options)
            elif target == "gif":
                fps = options.get("fps") or 12
                scale = _scale_filter(options.get("resolution") or "480x-1")
                # Generate a palette from the clip itself — far better colours
                # than ffmpeg's default fixed 256-colour palette.
                cmd += [
                    "-vf",
                    f"fps={fps},{scale}:flags=lanczos,split[a][b];"
                    "[a]palettegen[p];[b][p]paletteuse",
                    "-loop",
                    "0",
                ]
            else:
                resolution = options.get("resolution")
                if resolution:
                    cmd += ["-vf", _scale_filter(resolution)]
                fps = options.get("fps")
                if fps:
                    cmd += ["-r", str(fps)]
                bitrate = options.get("bitrate")
                if bitrate:
                    cmd += ["-b:v", str(bitrate)]
                codec = options.get("video_codec")
                if codec:
                    cmd += ["-c:v", str(codec)]
                if target in ("mp4", "mov", "m4v"):
                    # Put the index at the front so the file can start
                    # playing before it's fully downloaded/read.
                    cmd += ["-movflags", "+faststart"]

            cmd.append(str(job.output_path))

            if progress_cb:
                progress_cb(0.1, "Starting ffmpeg")
            run_ffmpeg(cmd, progress_cb)

        return self._run_timed(job, _do)


register(VideoConverter())
