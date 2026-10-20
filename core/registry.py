"""Converter plugin registry.

Converters self-register via :func:`register`. The registry is populated by
importing ``fileconverter.converters`` (see that package's ``__init__.py``),
which discovers every ``*_converter.py`` module automatically.
"""

from __future__ import annotations

from typing import Iterable

from .base import BaseConverter

_CONVERTERS: list[BaseConverter] = []


def register(converter: BaseConverter) -> BaseConverter:
    """Register a converter instance. Returns it unchanged so it can be
    used as a decorator-friendly call: ``register(MyConverter())``."""

    _CONVERTERS.append(converter)
    return converter


def all_converters() -> list[BaseConverter]:
    return list(_CONVERTERS)


def find_converters(src_format: str, dst_format: str) -> list[BaseConverter]:
    """Return every registered converter able to perform this conversion,
    in registration order (first is used by default)."""

    src_format = src_format.lower().lstrip(".")
    dst_format = dst_format.lower().lstrip(".")
    return [c for c in _CONVERTERS if c.can_convert(src_format, dst_format)]


def find_converter(src_format: str, dst_format: str) -> BaseConverter | None:
    """First registered converter for this pair, preferring one whose
    dependencies are actually installed when several could handle it."""

    matches = find_converters(src_format, dst_format)
    if len(matches) > 1:
        for converter in matches:
            available, _reason = converter.safe_check_available()
            if available:
                return converter
    return matches[0] if matches else None


def supported_targets(src_format: str) -> list[str]:
    """All formats a given source format can be converted to."""

    src_format = src_format.lower().lstrip(".")
    targets: set[str] = set()
    for c in _CONVERTERS:
        if src_format in c.input_formats:
            # Ask each converter about each pair rather than assuming every
            # input can reach every output: some converters only support
            # specific pairs (e.g. VCF/ICS only convert to/from CSV).
            targets.update(t for t in c.output_formats if c.can_convert(src_format, t))
    targets.discard(src_format)
    return sorted(targets)


def all_input_formats() -> list[str]:
    formats: set[str] = set()
    for c in _CONVERTERS:
        formats.update(c.input_formats)
    return sorted(formats)


def conversion_matrix() -> dict[str, list[str]]:
    """Map every known input format to its reachable output formats —
    powers the GUI/CLI 'formats' listing."""

    return {fmt: supported_targets(fmt) for fmt in all_input_formats()}


def reset_registry_for_tests(converters: Iterable[BaseConverter] = ()) -> None:
    """Test helper: replace the global registry contents."""

    _CONVERTERS.clear()
    _CONVERTERS.extend(converters)
