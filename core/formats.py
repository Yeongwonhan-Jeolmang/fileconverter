"""Format detection helpers.

Detects a file's real format from its extension first, then falls back to
magic-byte sniffing so misnamed/extension-less files still convert
correctly.
"""

from __future__ import annotations

from pathlib import Path

# (offset, magic_bytes, format)
_MAGIC_SIGNATURES: list[tuple[int, bytes, str]] = [
    (0, b"\x89PNG\r\n\x1a\n", "png"),
    (0, b"\xff\xd8\xff", "jpg"),
    (0, b"GIF87a", "gif"),
    (0, b"GIF89a", "gif"),
    (0, b"BM", "bmp"),
    (8, b"WEBP", "webp"),
    (0, b"II*\x00", "tiff"),
    (0, b"MM\x00*", "tiff"),
    (0, b"%PDF-", "pdf"),
    (0, b"PK\x03\x04", "zip"),  # also docx/xlsx/pptx/ods/odt/epub — see below
    (0, b"\x1f\x8b", "gz"),
    (0, b"7z\xbc\xaf\x27\x1c", "7z"),
    (257, b"ustar", "tar"),
    (0, b"ID3", "mp3"),
    (0, b"RIFF", "wav"),  # RIFF also covers AVI; refined by extension when possible
    (0, b"fLaC", "flac"),
    (4, b"ftyp", "mp4"),
    (0, b"\x1a\x45\xdf\xa3", "mkv"),  # also webm (EBML)
]

# Zip-based formats disambiguated by looking at internal entry names.
_ZIP_SIGNATURES: dict[str, str] = {
    "word/document.xml": "docx",
    "xl/workbook.xml": "xlsx",
    "ppt/presentation.xml": "pptx",
    "content.xml": "odt",
    "mimetype": "epub",
}


def normalize_ext(ext_or_path: str | Path) -> str:
    """Return a lowercase extension without the leading dot.

    Accepts either a bare extension ("png", ".PNG") or a full path/filename
    ("photo.PNG", "/a/b/photo.png") and returns the normalized extension.
    """

    text = str(ext_or_path)
    if isinstance(ext_or_path, Path) or "/" in text or "\\" in text or "." in text:
        ext = Path(ext_or_path).suffix
    else:
        ext = text
    return ext.lower().lstrip(".")


def detect_format(path: Path) -> str:
    """Best-effort format detection: extension first, magic bytes fallback.

    Returns a lowercase extension-like string (e.g. "png", "docx") or ""
    if nothing could be determined.
    """

    path = Path(path)
    ext = normalize_ext(path)
    if ext:
        return ext
    return sniff_format(path) or ""


def sniff_format(path: Path) -> str | None:
    """Inspect the first bytes of a file to guess its format, ignoring the
    (possibly missing or wrong) extension."""

    path = Path(path)
    try:
        with open(path, "rb") as fh:
            head = fh.read(512)
    except OSError:
        return None

    for offset, magic, fmt in _MAGIC_SIGNATURES:
        if head[offset : offset + len(magic)] == magic:
            if fmt == "zip":
                disambiguated = _disambiguate_zip(path)
                return disambiguated or "zip"
            return fmt
    return None


def _disambiguate_zip(path: Path) -> str | None:
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    except Exception:
        return None
    for marker, fmt in _ZIP_SIGNATURES.items():
        if marker in names:
            return fmt
    return None
