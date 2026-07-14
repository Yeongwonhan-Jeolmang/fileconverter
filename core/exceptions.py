"""Exception hierarchy for FileConverter.

Keeping a dedicated hierarchy lets the CLI/GUI show precise, actionable
error messages instead of raw tracebacks.
"""

from __future__ import annotations


class FileConverterError(Exception):
    """Base class for all FileConverter errors."""


class UnsupportedConversionError(FileConverterError):
    """Raised when no converter can handle a given source -> target pair."""

    def __init__(self, src_format: str, dst_format: str):
        self.src_format = src_format
        self.dst_format = dst_format
        super().__init__(
            f"No converter registered for '{src_format}' -> '{dst_format}'."
        )


class MissingDependencyError(FileConverterError):
    """Raised when a converter needs an optional package or external binary
    that is not installed (e.g. ffmpeg, LibreOffice, py7zr)."""

    def __init__(self, dependency: str, hint: str | None = None):
        self.dependency = dependency
        self.hint = hint
        message = f"Missing required dependency: '{dependency}'."
        if hint:
            message += f" {hint}"
        super().__init__(message)


class ConversionFailedError(FileConverterError):
    """Raised when a conversion was attempted but failed midway."""


class InvalidInputError(FileConverterError):
    """Raised when the input file is missing, unreadable, or malformed."""


class PresetError(FileConverterError):
    """Raised for preset load/save/validation issues."""
