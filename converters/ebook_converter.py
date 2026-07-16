"""E-book conversion: EPUB, MOBI, AZW3, FB2 (and plain TXT/HTML export).

Layered strategy (most specific -> most general), mirroring
document_converter.py:
  1. Native, dependency-light path for EPUB -> TXT/HTML using ``ebooklib``
     + ``beautifulsoup4`` (both already pip-installable, no binaries).
  2. If Calibre's ``ebook-convert`` CLI is found on PATH, use it as a
     universal fallback engine for every other pair (mobi/azw3/fb2/epub).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import ConversionFailedError, MissingDependencyError
from ..core.registry import register

_EBOOK_FORMATS = frozenset({"epub", "mobi", "azw3", "fb2", "txt", "html"})


def _find_ebook_convert() -> str | None:
    return shutil.which("ebook-convert")


class EbookConverter(BaseConverter):
    name = "Ebook Converter"
    description = (
        "Converts between EPUB, MOBI, AZW3, FB2, TXT, and HTML. "
        "Uses ebooklib natively for EPUB text/HTML extraction, and "
        "auto-detects Calibre's ebook-convert on PATH for everything else."
    )
    input_formats = _EBOOK_FORMATS
    output_formats = _EBOOK_FORMATS

    def check_available(self) -> tuple[bool, str]:
        has_ebooklib = True
        try:
            import ebooklib  # noqa: F401
        except ImportError:
            has_ebooklib = False
        has_calibre = _find_ebook_convert() is not None
        if has_ebooklib or has_calibre:
            note = []
            if not has_ebooklib:
                note.append("pip install ebooklib beautifulsoup4 (for EPUB extraction)")
            if not has_calibre:
                note.append("install Calibre for MOBI/AZW3/FB2 support")
            return True, "OK" + (f" (optional: {'; '.join(note)})" if note else "")
        return False, (
            "Install with: pip install ebooklib beautifulsoup4, "
            "or install Calibre (provides ebook-convert) for full format coverage."
        )

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            src_ext = job.source_path.suffix.lower().lstrip(".")
            target = job.target_format.lower().lstrip(".")

            if progress_cb:
                progress_cb(0.1, f"Converting {src_ext} -> {target}")

            if src_ext == "epub" and target in ("txt", "html"):
                try:
                    self._epub_to_text_like(job, target)
                    if progress_cb:
                        progress_cb(0.95, "Done")
                    return
                except ImportError:
                    pass  # fall through to Calibre below

            calibre = _find_ebook_convert()
            if calibre:
                self._calibre_convert(calibre, job)
            else:
                raise MissingDependencyError(
                    "ebook-convert",
                    "Install Calibre (provides the 'ebook-convert' CLI) for this "
                    "conversion pair, or 'pip install ebooklib beautifulsoup4' "
                    "for EPUB -> TXT/HTML.",
                )

            if progress_cb:
                progress_cb(0.95, "Done")

        return self._run_timed(job, _do)

    def _epub_to_text_like(self, job: ConversionJob, target: str) -> None:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        book = epub.read_epub(str(job.source_path))
        parts: list[str] = []
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                if target == "txt":
                    text = soup.get_text(separator="\n").strip()
                    if text:
                        parts.append(text)
                else:  # html
                    parts.append(str(soup))

        if not parts:
            raise ConversionFailedError("No readable content found in EPUB.")

        if target == "txt":
            job.output_path.write_text("\n\n".join(parts), encoding="utf-8")
        else:
            html_doc = (
                "<html><head><meta charset='utf-8'></head><body>"
                + "\n<hr/>\n".join(parts)
                + "</body></html>"
            )
            job.output_path.write_text(html_doc, encoding="utf-8")

    def _calibre_convert(self, calibre_bin: str, job: ConversionJob) -> None:
        cmd = [calibre_bin, str(job.source_path), str(job.output_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ConversionFailedError(
                f"ebook-convert failed: {result.stderr.strip() or result.stdout.strip()}"
            )


register(EbookConverter())
