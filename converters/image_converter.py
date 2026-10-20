"""Image conversion via Pillow.

Supports the common raster formats plus image -> PDF/ICO packaging.
Bonus features vs. a bare Pillow wrapper:
  - resize (with aspect-ratio-preserving "fit" mode)
  - rotate / auto-orient using EXIF
  - quality control for lossy formats
  - EXIF/metadata preservation toggle
  - multi-page/animated GIF -> PDF (one page per frame)
  - optional HEIC/HEIF support if ``pillow-heif`` is installed
"""

from __future__ import annotations

from pathlib import Path

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import MissingDependencyError
from ..core.registry import register

_RASTER_FORMATS = frozenset(
    {"png", "jpg", "jpeg", "bmp", "gif", "webp", "tiff", "tif", "ico"}
)

_PIL_MODE_FOR_EXT = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "bmp": "BMP",
    "gif": "GIF",
    "webp": "WEBP",
    "tiff": "TIFF",
    "tif": "TIFF",
    "ico": "ICO",
}


def _try_register_heif() -> None:
    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
    except ImportError:
        pass


class ImageConverter(BaseConverter):
    name = "Image Converter"
    description = (
        "Converts between raster image formats and to/from single & multi-page PDF."
    )
    input_formats = _RASTER_FORMATS | {"heic", "heif", "pdf"}
    output_formats = _RASTER_FORMATS | {"pdf"}

    def check_available(self) -> tuple[bool, str]:
        try:
            import PIL  # noqa: F401

            return True, "OK"
        except ImportError:
            return False, "Install with: pip install Pillow"

    def can_convert(self, src_format: str, dst_format: str) -> bool:
        src = src_format.lower().lstrip(".")
        dst = dst_format.lower().lstrip(".")
        # PDF -> PDF through this converter would rasterize every page (and
        # destroy selectable text); it isn't a meaningful conversion.
        if src == "pdf" and dst == "pdf":
            return False
        return super().can_convert(src, dst)

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        produced: list[Path] = []

        def _do() -> None:
            try:
                from PIL import Image, ImageOps
            except ImportError as exc:
                raise MissingDependencyError(
                    "Pillow", "Install with: pip install Pillow"
                ) from exc

            _try_register_heif()

            src_ext = job.src_format
            target = job.target_format.lower().lstrip(".")
            options = job.options

            if progress_cb:
                progress_cb(0.1, "Opening source image")

            if src_ext == "pdf":
                produced.extend(self._pdf_to_images(job, progress_cb))
                return

            with Image.open(job.source_path) as source:
                n_frames = getattr(source, "n_frames", 1)
                if target == "pdf" and n_frames > 1:
                    # Multi-page TIFF / animated GIF -> one PDF page per frame.
                    frames = []
                    for i in range(n_frames):
                        source.seek(i)
                        frames.append(
                            _flatten_alpha(self._apply_transforms(source.copy(), options))
                        )
                    if progress_cb:
                        progress_cb(0.6, f"Writing {n_frames}-page PDF")
                    frames[0].save(
                        job.output_path, "PDF", save_all=True, append_images=frames[1:]
                    )
                    return

                exif = source.info.get("exif")
                img = ImageOps.exif_transpose(source) or source
                img = self._apply_transforms(img, options)

                if progress_cb:
                    progress_cb(0.5, "Encoding output")

                if target == "pdf":
                    _flatten_alpha(img).save(job.output_path, "PDF")
                    if progress_cb:
                        progress_cb(0.95, "Wrote PDF")
                    return

                pil_format = _PIL_MODE_FOR_EXT.get(target, target.upper())
                save_kwargs: dict = {}

                if pil_format == "JPEG":
                    # JPEG has no alpha channel and only supports a few modes;
                    # composite transparency onto white instead of letting it
                    # turn black (or failing outright for LA/I;16/etc.).
                    img = _flatten_alpha(img)

                quality = options.get("quality")
                if quality is not None and pil_format in ("JPEG", "WEBP"):
                    save_kwargs["quality"] = max(1, min(100, int(quality)))

                if options.get("preserve_metadata", True):
                    # After exif_transpose the orientation tag is reset, so
                    # prefer the transposed image's EXIF when it has one.
                    exif = img.info.get("exif") or exif
                    if exif and pil_format in ("JPEG", "WEBP", "PNG", "TIFF"):
                        save_kwargs["exif"] = exif

                img.save(job.output_path, pil_format, **save_kwargs)
                if progress_cb:
                    progress_cb(0.95, "Wrote image")

        result = self._run_timed(job, _do)
        if result.success and produced:
            result.output_path = produced[0]
            if len(produced) > 1:
                result.message += f" ({len(produced)} pages written)"
        return result

    @staticmethod
    def _apply_transforms(img, options):
        resize = options.get("resize")
        if resize:
            width, height = _parse_size(resize)
            img.thumbnail((width, height))
        rotate = options.get("rotate")
        if rotate:
            img = img.rotate(-int(rotate), expand=True)
        return img

    def _pdf_to_images(
        self, job: ConversionJob, progress_cb: ProgressCallback
    ) -> list[Path]:
        """Render PDF pages to raster images (requires pypdfium2).

        A single-page PDF is written to ``job.output_path``. A multi-page
        PDF is written as ``<stem>_p1.<ext>``, ``<stem>_p2.<ext>``, ... next
        to it. Options: ``page_range`` (e.g. ``"1-3,5"``) and ``dpi``
        (default 144)."""

        target = job.target_format.lower().lstrip(".")
        try:
            import pypdfium2 as pdfium  # type: ignore
        except ImportError as exc:
            raise MissingDependencyError(
                "pypdfium2",
                "Install with: pip install pypdfium2 (for PDF -> image conversion)",
            ) from exc

        dpi = float(job.options.get("dpi") or 144)
        pil_format = _PIL_MODE_FOR_EXT.get(target, target.upper())
        out_dir = job.output_path.parent
        stem = job.output_path.stem
        written: list[Path] = []

        pdf = pdfium.PdfDocument(str(job.source_path))
        try:
            pages = _parse_page_range(job.options.get("page_range"), len(pdf))
            for n, index in enumerate(pages, start=1):
                page = pdf[index]
                try:
                    pil_image = page.render(scale=dpi / 72).to_pil()
                finally:
                    page.close()
                if pil_format == "JPEG":
                    pil_image = _flatten_alpha(pil_image)
                if len(pages) == 1:
                    page_path = job.output_path
                else:
                    page_path = out_dir / f"{stem}_p{index + 1}.{target}"
                pil_image.save(page_path, pil_format)
                written.append(page_path)
                if progress_cb:
                    progress_cb(
                        0.1 + 0.8 * n / len(pages), f"Rendered page {n}/{len(pages)}"
                    )
        finally:
            pdf.close()
        return written


def _flatten_alpha(img):
    """Return an RGB/L/CMYK copy of ``img``, compositing any transparency
    onto a white background."""

    from PIL import Image

    if img.mode in ("RGB", "L", "CMYK"):
        return img
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    if img.mode in ("RGBA", "LA", "PA"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def _parse_size(value) -> tuple[int, int]:
    """Accept ``[w, h]``, ``(w, h)``, ``"WxH"`` or ``"W,H"``."""

    if isinstance(value, str):
        parts = value.lower().replace("x", ",").split(",")
    else:
        parts = list(value)
    if len(parts) != 2:
        raise ValueError(f"resize must be width and height, got {value!r}")
    width, height = (int(p) for p in parts)
    if width <= 0 or height <= 0:
        raise ValueError(f"resize dimensions must be positive, got {value!r}")
    return width, height


def _parse_page_range(spec, n_pages: int) -> list[int]:
    """Turn ``"1-3,5"`` (1-based, inclusive) into 0-based page indices.
    ``None``/empty means every page."""

    if spec in (None, ""):
        return list(range(n_pages))
    if isinstance(spec, int):
        spec = str(spec)
    elif isinstance(spec, (list, tuple)):  # e.g. "-O page_range=1,3" parses to [1, 3]
        spec = ",".join(str(p) for p in spec)
    pages: list[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_text, hi_text = part.split("-", 1)
            lo = int(lo_text) if lo_text.strip() else 1
            hi = int(hi_text) if hi_text.strip() else n_pages
        else:
            lo = hi = int(part)
        for page in range(max(1, lo), min(n_pages, hi) + 1):
            if page - 1 not in pages:
                pages.append(page - 1)
    if not pages:
        raise ValueError(f"page_range {spec!r} selects no pages (PDF has {n_pages}).")
    return pages


register(ImageConverter())
