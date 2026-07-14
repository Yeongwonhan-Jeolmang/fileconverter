"""Archive conversion & repacking.

Supports zip <-> tar/tar.gz/tar.bz2/tar.xz, plus optional 7z read/write via
``py7zr`` when installed. Also supports "folder -> archive" and
"archive -> folder" through the generic engine (source_path can be a
directory when used programmatically; the GUI/CLI expose this as
"Compress folder" / "Extract archive").
"""

from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Literal

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import MissingDependencyError
from ..core.registry import register

_ARCHIVE_FORMATS = frozenset({"zip", "tar", "gz", "tgz", "bz2", "xz", "7z"})

_TarWriteMode = Literal["w", "w:gz", "w:bz2", "w:xz"]
_TarReadMode = Literal["r", "r:gz", "r:bz2", "r:xz"]

_TAR_MODE_FOR_TARGET: dict[str, _TarWriteMode] = {
    "tar": "w",
    "gz": "w:gz",
    "tgz": "w:gz",
    "bz2": "w:bz2",
    "xz": "w:xz",
}
_TAR_MODE_FOR_SOURCE: dict[str, _TarReadMode] = {
    "tar": "r",
    "gz": "r:gz",
    "tgz": "r:gz",
    "bz2": "r:bz2",
    "xz": "r:xz",
}


class ArchiveConverter(BaseConverter):
    name = "Archive Converter"
    description = "Repacks between zip/tar/tar.gz/tar.bz2/tar.xz/7z; extracts and creates archives."
    input_formats = _ARCHIVE_FORMATS
    output_formats = _ARCHIVE_FORMATS

    def check_available(self) -> tuple[bool, str]:
        return True, "OK (7z support requires: pip install py7zr)"

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            src_ext = job.source_path.suffix.lower().lstrip(".")
            target = job.target_format.lower().lstrip(".")

            if progress_cb:
                progress_cb(0.05, "Extracting source archive")

            import tempfile

            with tempfile.TemporaryDirectory(prefix="fileconverter_") as tmp:
                tmp_path = Path(tmp)
                self._extract(job.source_path, src_ext, tmp_path)
                if progress_cb:
                    progress_cb(0.5, "Repacking to target format")
                self._pack(tmp_path, target, job.output_path)

            if progress_cb:
                progress_cb(0.95, "Done")

        return self._run_timed(job, _do)

    def _extract(self, source: Path, src_ext: str, dest_dir: Path) -> None:
        if src_ext == "zip":
            with zipfile.ZipFile(source) as zf:
                zf.extractall(dest_dir)
        elif src_ext == "7z":
            self._extract_7z(source, dest_dir)
        elif src_ext in _TAR_MODE_FOR_SOURCE:
            mode = _TAR_MODE_FOR_SOURCE[src_ext]
            with tarfile.open(source, mode) as tf:
                try:
                    tf.extractall(dest_dir, filter="data")
                except TypeError:
                    # Python < 3.12 doesn't support the `filter` kwarg.
                    tf.extractall(dest_dir)
        else:
            raise ValueError(f"Unsupported source archive format: {src_ext}")

    def _pack(self, source_dir: Path, target: str, output_path: Path) -> None:
        if target == "zip":
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in sorted(source_dir.rglob("*")):
                    if file.is_file():
                        zf.write(file, file.relative_to(source_dir))
        elif target == "7z":
            self._pack_7z(source_dir, output_path)
        elif target in _TAR_MODE_FOR_TARGET:
            mode = _TAR_MODE_FOR_TARGET[target]
            with tarfile.open(output_path, mode) as tf:
                for file in sorted(source_dir.rglob("*")):
                    if file.is_file():
                        tf.add(file, file.relative_to(source_dir))
        else:
            raise ValueError(f"Unsupported target archive format: {target}")

    def _extract_7z(self, source: Path, dest_dir: Path) -> None:
        try:
            import py7zr  # type: ignore
        except ImportError as exc:
            raise MissingDependencyError(
                "py7zr", "Install with: pip install py7zr"
            ) from exc
        with py7zr.SevenZipFile(source, mode="r") as archive:
            archive.extractall(path=dest_dir)

    def _pack_7z(self, source_dir: Path, output_path: Path) -> None:
        try:
            import py7zr  # type: ignore
        except ImportError as exc:
            raise MissingDependencyError(
                "py7zr", "Install with: pip install py7zr"
            ) from exc
        with py7zr.SevenZipFile(output_path, mode="w") as archive:
            archive.writeall(source_dir, arcname=".")


class FolderArchiveConverter(BaseConverter):
    """Special-case converter for 'folder' -> archive (compress a directory)."""

    name = "Folder Compressor"
    description = "Compresses a whole folder into an archive."
    input_formats = frozenset({"folder"})
    output_formats = _ARCHIVE_FORMATS

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            target = job.target_format.lower().lstrip(".")
            archive_helper = ArchiveConverter()
            archive_helper._pack(job.source_path, target, job.output_path)
            if progress_cb:
                progress_cb(0.95, "Compressed folder")

        return self._run_timed(job, _do)


register(ArchiveConverter())
register(FolderArchiveConverter())
