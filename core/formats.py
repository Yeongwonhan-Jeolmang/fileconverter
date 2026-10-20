"""Format detection helpers.

Detects a file's real format from its extension first, then falls back to
magic-byte sniffing so misnamed/extension-less files still convert
correctly.
"""

from __future__ import annotations

from pathlib import Path

FOLDER_FORMAT = "folder"
"""Pseudo-format reported for directories (used by "compress folder")."""

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
    (0, b"OggS", "ogg"),
    (4, b"ftyp", "mp4"),  # ISO-BMFF; refined by the brand — see _refine_ftyp
    (0, b"\x1a\x45\xdf\xa3", "mkv"),  # also webm (EBML)
]

# Zip-based formats disambiguated by looking at internal entry names.
_ZIP_SIGNATURES: dict[str, str] = {
    "word/document.xml": "docx",
    "xl/workbook.xml": "xlsx",
    "ppt/presentation.xml": "pptx",
}

# ODF documents and EPUBs both store their MIME type in a "mimetype" entry,
# so read it rather than guessing from entry names (an .ods and an .odt
# both contain "content.xml").
_ZIP_MIMETYPES: dict[str, str] = {
    "application/epub+zip": "epub",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
}

# ISO base media file format "major brand" -> format. Anything not listed
# (isom, mp41, mp42, avc1, ...) is treated as plain mp4.
_FTYP_BRANDS: dict[bytes, str] = {
    b"heic": "heic",
    b"heix": "heic",
    b"hevc": "heic",
    b"heim": "heic",
    b"heis": "heic",
    b"mif1": "heif",
    b"msf1": "heif",
    b"avif": "avif",
    b"qt  ": "mov",
    b"M4A ": "m4a",
    b"M4B ": "m4a",
    b"M4V ": "m4v",
    b"3gp4": "3gp",
    b"3gp5": "3gp",
    b"3g2a": "3g2",
}


def normalize_ext(ext_or_path: str | Path) -> str:
    """Return a lowercase extension without the leading dot.

    Accepts either a bare extension ("png", ".PNG") or a full path/filename
    ("photo.PNG", "/a/b/photo.png") and returns the normalized extension.
    """

    text = str(ext_or_path)
    is_bare_ext = (
        not isinstance(ext_or_path, Path)
        and "/" not in text
        and "\\" not in text
        and text.count(".") <= 1
        and (text.startswith(".") or "." not in text)
    )
    # (".PNG" has to be special-cased: pathlib treats it as a hidden file
    # with *no* suffix, so it used to normalize to "".)
    ext = text if is_bare_ext else Path(ext_or_path).suffix
    return ext.lower().lstrip(".")


def detect_format(path: Path) -> str:
    """Best-effort format detection: extension first, magic bytes fallback.

    Directories are reported as ``"folder"`` so they can be routed to the
    folder -> archive converter.
    """

    path = Path(path)
    if path.is_dir():
        return FOLDER_FORMAT

    ext = normalize_ext(path)
    if not ext:
        return sniff_format(path) or ""

    if path.is_file():
        sniffed = sniff_format(path)
        if (
            sniffed
            and sniffed != ext
            and sniffed not in _WEAK_SNIFF_FORMATS
            and not _formats_are_related(ext, sniffed)
        ):
            return sniffed
    return ext


_WEAK_SNIFF_FORMATS = frozenset({"bmp"})


_RELATED_FORMAT_GROUPS: list[frozenset[str]] = [
    frozenset({"zip", "docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "jar"}),
    frozenset({"jpg", "jpeg"}),
    frozenset({"tif", "tiff"}),
    frozenset({"heic", "heif"}),
    frozenset({"mp4", "mov", "m4a", "m4v", "m4b", "3gp", "3g2", "aac"}),
    frozenset({"wav", "avi"}),
    frozenset({"mkv", "webm"}),
    frozenset({"gz", "tgz"}),
    frozenset({"ogg", "oga", "ogv", "opus"}),
    # MP3s tagged with ID3 sometimes carry other audio inside; trust the
    # extension for audio-ish files rather than calling them all "mp3".
    frozenset({"mp3", "flac", "wav", "aiff", "aac", "m4a", "ogg", "wma"}),
]


def _formats_are_related(ext: str, sniffed: str) -> bool:
    """True if ``ext`` and ``sniffed`` are different labels for what is
    effectively the same underlying container (or simply indistinguishable
    with byte-signature sniffing alone), so a mismatch between them
    shouldn't be treated as a "wrong extension"."""

    return any(ext in group and sniffed in group for group in _RELATED_FORMAT_GROUPS)


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
                return _disambiguate_zip(path) or "zip"
            if fmt == "mp4":
                return _FTYP_BRANDS.get(head[8:12], "mp4")
            return fmt
    return None


def _disambiguate_zip(path: Path) -> str | None:
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "mimetype" in names:
                mimetype = zf.read("mimetype").decode("ascii", "replace").strip()
                if mimetype in _ZIP_MIMETYPES:
                    return _ZIP_MIMETYPES[mimetype]
    except Exception:
        return None
    for marker, fmt in _ZIP_SIGNATURES.items():
        if marker in names:
            return fmt
    return None
