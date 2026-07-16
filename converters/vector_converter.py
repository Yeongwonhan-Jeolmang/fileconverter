"""Vector graphics conversion: SVG <-> PNG/PDF, and DXF -> SVG.

Uses ``cairosvg`` for SVG rasterization/PDF export (pure Python wheel with
a bundled cairo, no manual system install needed on most platforms) and
``ezdxf`` for reading CAD DXF files.

Options:
  - scale: float — output scale factor for SVG rasterization (default 1.0)
  - width / height: int — explicit target pixel size for PNG output
  - background: str — background color for PNG (default None/transparent)
"""

from __future__ import annotations

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import MissingDependencyError
from ..core.registry import register

_RASTER_FROM_SVG = frozenset({"png", "pdf"})
_INPUT_FORMATS = frozenset({"svg", "dxf"})
_OUTPUT_FORMATS = frozenset({"png", "pdf", "svg"})


class VectorConverter(BaseConverter):
    name = "Vector Graphics Converter"
    description = (
        "Converts SVG to PNG or PDF, and DXF (CAD) drawings to SVG. "
        "Requires cairosvg (SVG rendering) and/or ezdxf (DXF reading)."
    )
    input_formats = _INPUT_FORMATS
    output_formats = _OUTPUT_FORMATS

    def check_available(self) -> tuple[bool, str]:
        missing = []
        try:
            import cairosvg  # noqa: F401
        except ImportError:
            missing.append("cairosvg")
        try:
            import ezdxf  # noqa: F401
        except ImportError:
            missing.append("ezdxf")
        if missing:
            return False, f"Install with: pip install {' '.join(missing)}"
        return True, "OK"

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            src_ext = job.source_path.suffix.lower().lstrip(".")
            target = job.target_format.lower().lstrip(".")
            options = job.options

            if progress_cb:
                progress_cb(0.1, f"Reading {src_ext}")

            if src_ext == "svg" and target in _RASTER_FROM_SVG:
                self._svg_to_raster(job, target, options)
            elif src_ext == "dxf" and target == "svg":
                self._dxf_to_svg(job)
            else:
                raise ValueError(
                    f"Unsupported vector conversion: {src_ext} -> {target}"
                )

            if progress_cb:
                progress_cb(0.95, "Done")

        return self._run_timed(job, _do)

    def _svg_to_raster(self, job: ConversionJob, target: str, options) -> None:
        try:
            import cairosvg
        except ImportError as exc:
            raise MissingDependencyError(
                "cairosvg", "Install with: pip install cairosvg"
            ) from exc

        scale = options.get("scale", 1.0)
        kwargs = {"url": str(job.source_path), "scale": scale}
        if options.get("width"):
            kwargs["output_width"] = options.get("width")
        if options.get("height"):
            kwargs["output_height"] = options.get("height")
        if options.get("background"):
            kwargs["background_color"] = options.get("background")

        if target == "png":
            cairosvg.svg2png(write_to=str(job.output_path), **kwargs)
        elif target == "pdf":
            kwargs.pop("background_color", None)  # PDF has no background concept
            cairosvg.svg2pdf(write_to=str(job.output_path), **kwargs)

    def _dxf_to_svg(self, job: ConversionJob) -> None:
        try:
            import ezdxf
            from ezdxf.addons.drawing import RenderContext, Frontend
            from ezdxf.addons.drawing.svg import SVGBackend
            from ezdxf.addons.drawing.layout import Page
        except ImportError as exc:
            raise MissingDependencyError(
                "ezdxf", "Install with: pip install ezdxf"
            ) from exc

        doc = ezdxf.readfile(str(job.source_path))
        msp = doc.modelspace()
        backend = SVGBackend()
        Frontend(RenderContext(doc), backend).draw_layout(msp)
        # Page size is auto-fitted to the drawing's extents (units in mm).
        page = Page(0, 0)
        svg_string = backend.get_string(page)
        job.output_path.write_text(svg_string, encoding="utf-8")


register(VectorConverter())
