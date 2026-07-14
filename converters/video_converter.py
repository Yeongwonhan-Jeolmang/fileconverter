"""Video conversion by shelling out to the ffmpeg binary directly.

We avoid a heavy Python video library and instead drive ffmpeg via
subprocess, this keeps the dependency footprint small while supporting
essentially every container/codec ffmpeg supports, including:
  - video <-> video (mp4/avi/mov/mkv/webm)
  - video -> gif (animated preview export)
  - video -> mp3/wav (audio extraction)
"""

from __future__ import annotations

import re
import shutil
import subprocess

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import ConversionFailedError, MissingDependencyError
from ..core.registry import register

_VIDEO_FORMATS = frozenset({"mp4", "avi", "mov", "mkv", "webm", "flv", "wmv"})
_AUDIO_EXTRACT_FORMATS = frozenset({"mp3", "wav", "aac", "flac"})

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")
_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class VideoConverter(BaseConverter):
    name = "Video Converter"
    description = (
        "Converts between MP4, AVI, MOV, MKV, WEBM, FLV, WMV; exports GIFs and extracts audio tracks. "
        "Requires ffmpeg on PATH."
    )
    input_formats = _VIDEO_FORMATS
    output_formats = _VIDEO_FORMATS | {"gif"} | _AUDIO_EXTRACT_FORMATS

    def check_available(self) -> tuple[bool, str]:
        if not _ffmpeg_available():
            return False, "ffmpeg not found on PATH. Install from https://ffmpeg.org/download.html"
        return True, "OK"

    def convert(self, job: ConversionJob, progress_cb: ProgressCallback = None) -> ConversionResult:
        def _do() -> None:
            if not _ffmpeg_available():
                raise MissingDependencyError(
                    "ffmpeg", "Install from https://ffmpeg.org/download.html and ensure it is on PATH."
                )

            target = job.target_format.lower().lstrip(".")
            options = job.options
            cmd = ["ffmpeg", "-y", "-i", str(job.source_path)]

            if target in _AUDIO_EXTRACT_FORMATS:
                cmd += ["-vn"]
                if options.get("bitrate"):
                    cmd += ["-b:a", str(options["bitrate"])]
            elif target == "gif":
                fps = options.get("fps", 12)
                scale = options.get("resolution", "480:-1").replace("x", ":")
                cmd += ["-vf", f"fps={fps},scale={scale}:flags=lanczos", "-loop", "0"]
            else:
                resolution = options.get("resolution")
                if resolution:
                    cmd += ["-vf", f"scale={resolution.replace('x', ':')}"]
                fps = options.get("fps")
                if fps:
                    cmd += ["-r", str(fps)]
                bitrate = options.get("bitrate")
                if bitrate:
                    cmd += ["-b:v", str(bitrate)]
                codec = options.get("video_codec")
                if codec:
                    cmd += ["-c:v", str(codec)]

            cmd.append(str(job.output_path))

            if progress_cb:
                progress_cb(0.1, "Starting ffmpeg")

            self._run_with_progress(cmd, progress_cb)

        return self._run_timed(job, _do)

    def _run_with_progress(self, cmd: list[str], progress_cb: ProgressCallback) -> None:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        duration_seconds: float | None = None
        stderr_lines: list[str] = []

        assert process.stdout is not None
        for line in process.stdout:
            stderr_lines.append(line)
            if duration_seconds is None:
                match = _DURATION_RE.search(line)
                if match:
                    h, m, s = match.groups()
                    duration_seconds = int(h) * 3600 + int(m) * 60 + float(s)
            time_match = _TIME_RE.search(line)
            if time_match and duration_seconds and progress_cb:
                h, m, s = time_match.groups()
                elapsed = int(h) * 3600 + int(m) * 60 + float(s)
                fraction = min(0.95, 0.1 + 0.85 * (elapsed / duration_seconds))
                progress_cb(fraction, "Encoding")

        return_code = process.wait()
        if return_code != 0:
            tail = "".join(stderr_lines[-20:])
            raise ConversionFailedError(f"ffmpeg exited with code {return_code}:\n{tail}")


register(VideoConverter())
