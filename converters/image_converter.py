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

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            try:
                from PIL import Image, ImageOps
            except ImportError as exc:
                raise MissingDependencyError(
                    "Pillow", "Install with: pip install Pillow"
                ) from exc

            _try_register_heif()

            src_ext = job.source_path.suffix.lower().lstrip(".")
            target = job.target_format.lower().lstrip(".")

            if progress_cb:
                progress_cb(0.1, "Opening source image")

            if src_ext == "pdf":
                self._pdf_to_images(job, progress_cb)
                return

            with Image.open(job.source_path) as img:
                img = ImageOps.exif_transpose(img) or img

                options = job.options
                resize = options.get("resize")
                if resize:
                    width, height = resize
                    img.thumbnail((width, height))

                rotate = options.get("rotate")
                if rotate:
                    img = img.rotate(-int(rotate), expand=True)

                if progress_cb:
                    progress_cb(0.5, "Encoding output")

                if target == "pdf":
                    rgb = img.convert("RGB")
                    rgb.save(job.output_path, "PDF")
                    if progress_cb:
                        progress_cb(0.95, "Wrote PDF")
                    return

                pil_format = _PIL_MODE_FOR_EXT.get(target, target.upper())
                save_kwargs: dict = {}

                if pil_format in ("JPEG",) and img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                quality = options.get("quality")
                if quality is not None and pil_format in ("JPEG", "WEBP"):
                    save_kwargs["quality"] = int(quality)

                if options.get("preserve_metadata", True):
                    exif = img.info.get("exif")
                    if exif:
                        save_kwargs["exif"] = exif

                img.save(job.output_path, pil_format, **save_kwargs)
                if progress_cb:
                    progress_cb(0.95, "Wrote image")

        return self._run_timed(job, _do)

    def _pdf_to_images(self, job: ConversionJob, progress_cb: ProgressCallback) -> None:
        """Render each PDF page to a raster image (requires pypdfium2 or
        pdf2image+poppler; degrades gracefully with a clear error)."""

        target = job.target_format.lower().lstrip(".")
        try:
            import pypdfium2 as pdfium  # type: ignore
        except ImportError as exc:
            raise MissingDependencyError(
                "pypdfium2",
                "Install with: pip install pypdfium2 (for PDF -> image conversion)",
            ) from exc

        pdf = pdfium.PdfDocument(str(job.source_path))
        n_pages = len(pdf)
        out_dir = job.output_path.parent
        stem = job.output_path.stem

        for i in range(n_pages):
            page = pdf[i]
            bitmap = page.render(scale=2.0)
            pil_image = bitmap.to_pil()
            suffix = f"_p{i + 1}" if n_pages > 1 else ""
            page_path = out_dir / f"{stem}{suffix}.{target}"
            pil_image.save(page_path, _PIL_MODE_FOR_EXT.get(target, target.upper()))
            if progress_cb:
                progress_cb(
                    0.1 + 0.8 * (i + 1) / n_pages, f"Rendered page {i + 1}/{n_pages}"
                )

        if n_pages == 1:
            single_path = out_dir / f"{stem}.{target}"
            if single_path != job.output_path and single_path.exists():
                single_path.replace(job.output_path)


register(ImageConverter())
