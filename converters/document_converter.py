"""Document conversion: text, markdown, HTML, DOCX, PDF, RTF.

Layered strategy (most specific -> most general):
  1. Native, dependency-light paths for common pairs (txt/md/html/docx/pdf).
  2. If LibreOffice ("soffice") is found on PATH, use it as a universal
     fallback engine.
  3. If Pandoc is found on PATH, use it as a secondary fallback for
     text-based formats (md/html/rst/docx/odt/etc.).
"""

from __future__ import annotations

import html as html_lib
import shutil
import tempfile
from pathlib import Path

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import ConversionFailedError, MissingDependencyError
from ..core.proc_utils import run_killable
from ..core.registry import register

_TEXT_LIKE = frozenset({"txt", "md", "html", "htm"})
_OFFICE_LIKE = frozenset({"docx", "doc", "odt", "rtf", "pdf", "pptx", "ppt"})
_ALL_DOC_FORMATS = _TEXT_LIKE | _OFFICE_LIKE
_SLIDES = frozenset({"pptx", "ppt"})
# Targets for which a PDF must be opened as a *text* document (LibreOffice
# otherwise opens PDFs in Draw, which has no Word/ODT/RTF export filter).
_PDF_TO_WRITER_TARGETS = frozenset({"docx", "doc", "odt", "rtf", "txt"})


def _find_libreoffice() -> str | None:
    for candidate in ("soffice", "libreoffice"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _find_pandoc() -> str | None:
    return shutil.which("pandoc")


class DocumentConverter(BaseConverter):
    name = "Document Converter"
    description = (
        "Converts between TXT, Markdown, HTML, DOCX, RTF, ODT, PPTX and PDF. "
        "Uses native libraries for common pairs and auto-detects LibreOffice/Pandoc "
        "on your system as fallback engines for everything else."
    )
    input_formats = _ALL_DOC_FORMATS
    output_formats = _ALL_DOC_FORMATS

    def can_convert(self, src_format: str, dst_format: str) -> bool:
        src = src_format.lower().lstrip(".")
        dst = dst_format.lower().lstrip(".")
        # Same-format "conversions" (pdf -> pdf, docx -> docx) aren't
        # conversions; html <-> htm is just a rename.
        if {src, dst} <= {"html", "htm"} or src == dst:
            return False
        if not super().can_convert(src, dst):
            return False
        # Not every engine can do every pair: LibreOffice can't turn a text
        # document into slides (or vice versa), nothing here can write
        # Markdown from PDF/.doc, etc. Only advertise pairs that can work.
        if src in _SLIDES:
            return dst in _SLIDES or dst in ("pdf", "html", "htm")
        if dst in _SLIDES:
            return src in _SLIDES or (dst == "pptx" and src == "md")
        if dst == "md":
            return src in ("txt", "html", "htm", "docx", "odt", "rtf")
        return True

    def check_available(self) -> tuple[bool, str]:
        notes = []
        if _find_libreoffice():
            notes.append("LibreOffice found (full office format support)")
        else:
            notes.append("LibreOffice not found (install for docx/pdf/odt conversions)")
        if _find_pandoc():
            notes.append("Pandoc found (extra text format support)")
        return True, "; ".join(notes)

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            src_ext = job.src_format
            target = job.target_format.lower().lstrip(".")

            if progress_cb:
                progress_cb(0.1, f"Converting {src_ext} -> {target}")

            if self._try_native(job, src_ext, target, progress_cb):
                return

            # Try each external engine in turn; if one fails outright, still
            # give the next one a chance before reporting the first error.
            first_error: Exception | None = None
            for engine in (self._try_libreoffice, self._try_pandoc):
                try:
                    if engine(job, src_ext, target, progress_cb):
                        return
                except ConversionFailedError as exc:
                    first_error = first_error or exc
            if first_error is not None:
                raise first_error

            raise MissingDependencyError(
                "LibreOffice or Pandoc",
                f"No native path exists for {src_ext} -> {target}. Install LibreOffice "
                "(https://libreoffice.org) or Pandoc (https://pandoc.org) for full document support.",
            )

        return self._run_timed(job, _do)

    # ------------------------------------------------------------------
    def _try_native(
        self, job: ConversionJob, src_ext: str, target: str, progress_cb
    ) -> bool:
        if src_ext in ("txt",) and target in ("md", "html", "htm"):
            text = job.source_path.read_text(encoding="utf-8", errors="replace")
            if target == "md":
                job.output_path.write_text(text, encoding="utf-8")
            else:
                escaped = (
                    text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                )
                html = (
                    "<html><head><meta charset='utf-8'></head>"
                    f"<body><pre>{escaped}</pre></body></html>"
                )
                job.output_path.write_text(html, encoding="utf-8")
            return True

        if src_ext == "md" and target in ("html", "htm"):
            try:
                import markdown  # type: ignore
            except ImportError as exc:
                raise MissingDependencyError(
                    "markdown", "Install with: pip install markdown"
                ) from exc
            text = job.source_path.read_text(encoding="utf-8", errors="replace")
            html_body = markdown.markdown(
                text, extensions=["extra", "tables", "fenced_code"]
            )
            html = f"<html><head><meta charset='utf-8'></head><body>{html_body}</body></html>"
            job.output_path.write_text(html, encoding="utf-8")
            return True

        if src_ext in ("html", "htm") and target == "md":
            try:
                import html2text  # type: ignore
            except ImportError as exc:
                raise MissingDependencyError(
                    "html2text", "Install with: pip install html2text"
                ) from exc
            html = job.source_path.read_text(encoding="utf-8", errors="replace")
            converter = html2text.HTML2Text()
            job.output_path.write_text(converter.handle(html), encoding="utf-8")
            return True

        if src_ext in ("html", "htm", "md") and target == "txt":
            text = job.source_path.read_text(encoding="utf-8", errors="replace")
            if src_ext in ("html", "htm"):
                try:
                    from bs4 import BeautifulSoup  # type: ignore

                    text = BeautifulSoup(text, "html.parser").get_text()
                except ImportError:
                    pass
            job.output_path.write_text(text, encoding="utf-8")
            return True

        if src_ext == "docx" and target == "txt":
            try:
                import docx  # type: ignore
            except ImportError as exc:
                raise MissingDependencyError(
                    "python-docx", "Install with: pip install python-docx"
                ) from exc
            document = docx.Document(str(job.source_path))
            text = "\n".join(p.text for p in document.paragraphs)
            job.output_path.write_text(text, encoding="utf-8")
            return True

        if src_ext == "docx" and target in ("html", "htm"):
            try:
                import docx  # type: ignore
            except ImportError as exc:
                raise MissingDependencyError(
                    "python-docx", "Install with: pip install python-docx"
                ) from exc
            document = docx.Document(str(job.source_path))
            parts = []
            for p in document.paragraphs:
                text = html_lib.escape(p.text)
                style = (p.style.name if p.style is not None else "") or ""
                if style.startswith("Heading") and style[-1:].isdigit():
                    level = min(int(style[-1]), 6)
                    parts.append(f"<h{level}>{text}</h{level}>")
                elif style == "Title":
                    parts.append(f"<h1>{text}</h1>")
                else:
                    parts.append(f"<p>{text}</p>")
            html = (
                "<html><head><meta charset='utf-8'></head>"
                f"<body>{''.join(parts)}</body></html>"
            )
            job.output_path.write_text(html, encoding="utf-8")
            return True

        if src_ext in ("txt", "md") and target == "pdf":
            self._text_to_pdf(job)
            return True

        if src_ext == "pdf" and target == "txt":
            try:
                from pypdf import PdfReader  # type: ignore
            except ImportError as exc:
                raise MissingDependencyError(
                    "pypdf", "Install with: pip install pypdf"
                ) from exc
            reader = PdfReader(str(job.source_path))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            if not text.strip():
                raise ConversionFailedError(
                    "No extractable text found in this PDF (it may be a scanned "
                    "image). Try converting it to PNG instead, or OCR it first."
                )
            job.output_path.write_text(text, encoding="utf-8")
            return True

        return False

    def _text_to_pdf(self, job: ConversionJob) -> None:
        try:
            from reportlab.lib.pagesizes import LETTER  # type: ignore
            from reportlab.lib.utils import simpleSplit
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise MissingDependencyError(
                "reportlab", "Install with: pip install reportlab"
            ) from exc

        font_name, font_size, leading, margin = "Helvetica", 10, 14, 72
        text = job.source_path.read_text(encoding="utf-8", errors="replace")
        c = canvas.Canvas(str(job.output_path), pagesize=LETTER)
        c.setFont(font_name, font_size)
        width, height = LETTER
        max_width = width - 2 * margin
        y = height - margin
        for line in text.expandtabs(4).splitlines() or [""]:
            # Wrap by measured string width (not character count), so long
            # lines never run off the right edge of the page.
            wrapped_lines = simpleSplit(line, font_name, font_size, max_width) or [""]
            for wrapped in wrapped_lines:
                if y < margin:
                    c.showPage()
                    c.setFont(font_name, font_size)
                    y = height - margin
                c.drawString(margin, y, wrapped)
                y -= leading
        c.save()

    def _try_libreoffice(
        self, job: ConversionJob, src_ext: str, target: str, progress_cb
    ) -> bool:
        soffice = _find_libreoffice()
        if not soffice:
            return False
        if progress_cb:
            progress_cb(0.4, "Running LibreOffice headless conversion")
        # Convert into a private temp dir, then move the result into place:
        #  - LibreOffice always names its output "<source stem>.<target>", so
        #    writing straight into the output folder would clobber an existing
        #    file of that name (even when the overwrite policy said "rename"),
        #    or even the source itself for same-folder conversions.
        #  - A per-job user profile lets several LibreOffice conversions run
        #    in parallel; with a shared profile, all but one silently fail.
        with tempfile.TemporaryDirectory(prefix="fileconverter_lo_") as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            profile_url = (tmp_path / "profile").resolve().as_uri()
            cmd = [
                soffice,
                f"-env:UserInstallation={profile_url}",
                "--headless",
                "--norestore",
            ]
            if src_ext == "pdf" and target in _PDF_TO_WRITER_TARGETS:
                cmd.append("--infilter=writer_pdf_import")
            lo_target = "html" if target == "htm" else target
            cmd += [
                "--convert-to",
                lo_target,
                "--outdir",
                str(out_dir),
                str(job.source_path),
            ]
            proc = run_killable(cmd, progress_cb=progress_cb, timeout=180)
            if proc.returncode != 0:
                raise ConversionFailedError(
                    f"LibreOffice conversion failed: {proc.stderr.strip()}"
                )
            produced = list(out_dir.glob(f"*.{lo_target}")) if out_dir.exists() else []
            if not produced:
                # LibreOffice exits 0 even when it has no export filter for
                # the pair; surface its message instead of a vague failure.
                detail = (proc.stderr or proc.stdout).strip() or "no output produced"
                raise ConversionFailedError(
                    f"LibreOffice could not convert {src_ext} -> {target}: {detail}"
                )
            shutil.move(str(produced[0]), str(job.output_path))
        return job.output_path.exists()

    def _try_pandoc(
        self, job: ConversionJob, src_ext: str, target: str, progress_cb
    ) -> bool:
        pandoc = _find_pandoc()
        if not pandoc or src_ext not in _PANDOC_READERS:
            return False
        writer = _PANDOC_WRITERS.get(target)
        if writer is None:
            return False
        if progress_cb:
            progress_cb(0.4, "Running Pandoc")
        cmd = [
            pandoc,
            "-f",
            _PANDOC_READERS[src_ext],
            "-t",
            writer,
            "--standalone",
            str(job.source_path),
            "-o",
            str(job.output_path),
        ]
        # See _try_libreoffice: run_killable makes this cancellable.
        proc = run_killable(cmd, progress_cb=progress_cb, timeout=120)
        if proc.returncode != 0:
            raise ConversionFailedError(
                f"Pandoc conversion failed: {proc.stderr.strip()}"
            )
        return job.output_path.exists()


# Pandoc infers formats from extensions, but not for every one we use (it
# has no idea what ".txt" is), and it can't read PDF/legacy binary formats
# at all — so map explicitly and only try pairs it can actually do.
_PANDOC_READERS = {
    "md": "markdown",
    "txt": "markdown",
    "html": "html",
    "htm": "html",
    "docx": "docx",
    "odt": "odt",
    "rtf": "rtf",
}
_PANDOC_WRITERS = {
    "md": "markdown",
    "txt": "plain",
    "html": "html",
    "htm": "html",
    "docx": "docx",
    "odt": "odt",
    "rtf": "rtf",
    "pptx": "pptx",
}


register(DocumentConverter())
