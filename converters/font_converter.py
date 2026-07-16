"""Font file conversion: TTF, OTF, WOFF, WOFF2.

Uses ``fonttools`` (pure Python, pip-installable) which reads/writes all
four formats via its ``TTFont`` object model — no system font tools
required. WOFF2 support needs the optional ``brotli`` package that
fonttools depends on for that codec.
"""

from __future__ import annotations

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import MissingDependencyError
from ..core.registry import register

_FONT_FORMATS = frozenset({"ttf", "otf", "woff", "woff2"})

_FLAVOR = {"woff": "woff", "woff2": "woff2"}  # ttf/otf use flavor=None


class FontConverter(BaseConverter):
    name = "Font Converter"
    description = (
        "Converts between TTF, OTF, WOFF, and WOFF2 font files. "
        "Requires fonttools (and brotli for WOFF2)."
    )
    input_formats = _FONT_FORMATS
    output_formats = _FONT_FORMATS

    def check_available(self) -> tuple[bool, str]:
        try:
            import fontTools  # noqa: F401
        except ImportError:
            return False, "Install with: pip install fonttools brotli"
        return True, "OK"

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            try:
                from fontTools.ttLib import TTFont
            except ImportError as exc:
                raise MissingDependencyError(
                    "fonttools", "Install with: pip install fonttools brotli"
                ) from exc

            target = job.target_format.lower().lstrip(".")
            if target not in _FONT_FORMATS:
                raise ValueError(f"Unsupported font target format: {target}")

            if progress_cb:
                progress_cb(0.1, "Loading font")

            font = TTFont(str(job.source_path))

            if progress_cb:
                progress_cb(0.6, f"Writing {target}")

            font.flavor = _FLAVOR.get(target)  # None for ttf/otf, "woff"/"woff2" else
            try:
                font.save(str(job.output_path))
            except ImportError as exc:
                # fontTools raises ImportError here if brotli is missing for woff2
                raise MissingDependencyError(
                    "brotli", "Install with: pip install brotli"
                ) from exc

            if progress_cb:
                progress_cb(0.95, "Done")

        return self._run_timed(job, _do)


register(FontConverter())
