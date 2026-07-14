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
    signature_checks: dict[str, bytes] = {
        "png": b"\x89PNG",
        "pdf": b"%PDF",
        "gif": b"GIF8",
        "zip": b"PK\x03\x04",
        "docx": b"PK\x03\x04",
        "xlsx": b"PK\x03\x04",
    }
    expected = signature_checks.get(ext)
    if expected:
        with open(path, "rb") as fh:
            head = fh.read(len(expected))
        if head != expected:
            return False, f"Output file does not look like a valid {ext.upper()} file."
    return True, "OK"
