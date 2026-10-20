"""Integrity helpers: checksum computation and output verification.

After a conversion, the engine can optionally re-open the output file to
confirm it is well-formed (not just "a file exists").
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_of(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def verify_output_file(path: Path, min_size_bytes: int = 1) -> tuple[bool, str]:
    """Cheap sanity check: file exists, is non-empty, and format-specific
    magic bytes look right when we recognize the extension."""

    path = Path(path)
    if not path.exists():
        return False, "Output file was not created."
    size = path.stat().st_size
    if size < min_size_bytes:
        return False, "Output file is empty."

    ext = path.suffix.lower().lstrip(".")
    expected = _SIGNATURE_CHECKS.get(ext)
    if expected:
        offset, magic = expected
        with open(path, "rb") as fh:
            head = fh.read(offset + len(magic))
        if head[offset : offset + len(magic)] != magic:
            return False, f"Output file does not look like a valid {ext.upper()} file."
    return True, "OK"


_ZIP_MAGIC = (0, b"PK\x03\x04")
_GZIP_MAGIC = (0, b"\x1f\x8b")

# extension -> (byte offset, expected magic bytes)
_SIGNATURE_CHECKS: dict[str, tuple[int, bytes]] = {
    "png": (0, b"\x89PNG"),
    "jpg": (0, b"\xff\xd8\xff"),
    "jpeg": (0, b"\xff\xd8\xff"),
    "gif": (0, b"GIF8"),
    "bmp": (0, b"BM"),
    "webp": (8, b"WEBP"),
    "pdf": (0, b"%PDF"),
    "zip": _ZIP_MAGIC,
    "docx": _ZIP_MAGIC,
    "xlsx": _ZIP_MAGIC,
    "pptx": _ZIP_MAGIC,
    "odt": _ZIP_MAGIC,
    "ods": _ZIP_MAGIC,
    "epub": _ZIP_MAGIC,
    "gz": _GZIP_MAGIC,
    "tgz": _GZIP_MAGIC,
    "7z": (0, b"7z\xbc\xaf\x27\x1c"),
    "flac": (0, b"fLaC"),
    "ogg": (0, b"OggS"),
    "wav": (0, b"RIFF"),
}
