"""Structured data conversion: YAML, JSON, TOML, XML.

Pure "data document" conversion — parses the source into a plain Python
dict/list tree, then re-serializes into the target format. No external
binaries required; PyYAML and toml/tomli(-w) are pure-Python pip packages.

Options:
  - xml_root: str — root element name when writing XML (default "root")
  - indent: int — indent width for JSON/XML output (default 2)

XML mapping (same convention as the popular ``xmltodict`` library, so the
JSON/YAML you get is familiar and round-trips back to equivalent XML):
  - attributes become keys prefixed with "@"  (``<a id="1">`` -> ``{"@id": "1"}``)
  - an element's text becomes "#text" when it also has attributes/children
  - repeated child elements become a list
"""

from __future__ import annotations

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import MissingDependencyError
from ..core.registry import register

_DATA_FORMATS = frozenset({"yaml", "yml", "json", "toml", "xml"})


class DataConverter(BaseConverter):
    name = "Data Converter"
    description = (
        "Converts between YAML, JSON, TOML, and XML data documents. "
        "Requires PyYAML for YAML and toml/tomli+tomli-w for TOML."
    )
    input_formats = _DATA_FORMATS
    output_formats = _DATA_FORMATS

    def can_convert(self, src_format: str, dst_format: str) -> bool:
        src = src_format.lower().lstrip(".")
        dst = dst_format.lower().lstrip(".")
        if {src, dst} <= {"yaml", "yml"}:
            return False  # same format, just a different extension
        return super().can_convert(src, dst)

    def check_available(self) -> tuple[bool, str]:
        missing = []
        try:
            import yaml  # noqa: F401
        except ImportError:
            missing.append("pyyaml")
        try:
            import tomllib  # noqa: F401  (Python 3.11+, stdlib)
        except ImportError:
            try:
                # pyrefly: ignore[missing-import]  (only reached on Python <3.11)
                import tomli as tomllib
            except ImportError:
                missing.append("tomli")
        try:
            import tomli_w  # noqa: F401
        except ImportError:
            missing.append("tomli-w")
        if missing:
            return False, f"Install with: pip install {' '.join(missing)}"
        return True, "OK"

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            src_ext = job.src_format
            if src_ext == "yml":
                src_ext = "yaml"
            target = job.target_format.lower().lstrip(".")
            if target == "yml":
                target = "yaml"
            options = job.options

            if progress_cb:
                progress_cb(0.1, f"Reading {src_ext}")

            data = self._read(job, src_ext)

            if progress_cb:
                progress_cb(0.6, f"Writing {target}")

            self._write(data, job, target, options)

            if progress_cb:
                progress_cb(0.95, "Done")

        return self._run_timed(job, _do)

    def _read(self, job: ConversionJob, src_ext: str):
        text = job.source_path.read_text(encoding="utf-8")
        if src_ext == "json":
            import json

            return json.loads(text)
        if src_ext == "yaml":
            try:
                import yaml
            except ImportError as exc:
                raise MissingDependencyError(
                    "pyyaml", "Install with: pip install pyyaml"
                ) from exc
            return yaml.safe_load(text)
        if src_ext == "toml":
            try:
                import tomllib  # Python 3.11+
            except ImportError:
                try:
                    # pyrefly: ignore[missing-import]  (only reached on Python <3.11)
                    import tomli as tomllib
                except ImportError as exc:
                    raise MissingDependencyError(
                        "tomli", "Install with: pip install tomli"
                    ) from exc
            return tomllib.loads(text)
        if src_ext == "xml":
            return self._xml_to_data(text)
        raise ValueError(f"Unsupported data source format: {src_ext}")

    def _write(self, data, job: ConversionJob, target: str, options) -> None:
        indent = int(options.get("indent", 2))
        if target == "json":
            import json

            # default=str: TOML and YAML have native date/datetime values,
            # which json can't serialize on its own; write them as ISO text.
            job.output_path.write_text(
                json.dumps(data, indent=indent, ensure_ascii=False, default=_json_default),
                encoding="utf-8",
            )
        elif target == "yaml":
            try:
                import yaml
            except ImportError as exc:
                raise MissingDependencyError(
                    "pyyaml", "Install with: pip install pyyaml"
                ) from exc
            job.output_path.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        elif target == "toml":
            try:
                import tomli_w
            except ImportError as exc:
                raise MissingDependencyError(
                    "tomli-w", "Install with: pip install tomli-w"
                ) from exc
            if not isinstance(data, dict):
                raise ValueError("TOML requires a top-level mapping/object.")
            job.output_path.write_text(
                tomli_w.dumps(_strip_nulls(data)), encoding="utf-8"
            )
        elif target == "xml":
            root_name = options.get("xml_root", "root")
            xml_text = self._data_to_xml(data, root_name, indent)
            job.output_path.write_text(xml_text, encoding="utf-8")
        else:
            raise ValueError(f"Unsupported data target format: {target}")

    # -- XML helpers (uses stdlib xml.etree, no extra dependency) --------
    def _xml_to_data(self, text: str):
        from xml.etree import ElementTree as ET

        root = ET.fromstring(text)

        def _elem_to_obj(elem):
            children = list(elem)
            text_value = elem.text.strip() if elem.text and elem.text.strip() else None
            if not children and not elem.attrib:
                return text_value
            obj: dict = {f"@{k}": v for k, v in elem.attrib.items()}
            for child in children:
                value = _elem_to_obj(child)
                if child.tag in obj:
                    existing = obj[child.tag]
                    if isinstance(existing, list):
                        existing.append(value)
                    else:
                        obj[child.tag] = [existing, value]
                else:
                    obj[child.tag] = value
            if text_value is not None:
                obj["#text"] = text_value
            return obj

        return {root.tag: _elem_to_obj(root)}

    def _data_to_xml(self, data, root_name: str, indent: int) -> str:
        from xml.etree import ElementTree as ET
        from xml.dom import minidom

        def _fill(el, value):
            """Populate element ``el`` from ``value``."""
            if isinstance(value, dict):
                for k, v in value.items():
                    key = str(k)
                    if key.startswith("@"):
                        el.set(_xml_name(key[1:]), _xml_text(v))
                    elif key == "#text":
                        el.text = _xml_text(v)
                    else:
                        _build(el, key, v)
            elif isinstance(value, list):
                for item in value:
                    _build(el, "item", item)
            else:
                el.text = _xml_text(value)

        def _build(parent, key, value):
            if isinstance(value, list):
                # A list under a key becomes repeated <key> elements.
                for item in value:
                    _build(parent, key, item)
                return
            _fill(ET.SubElement(parent, _xml_name(key)), value)

        if (
            isinstance(data, dict)
            and len(data) == 1
            and not isinstance(next(iter(data.values())), list)
        ):
            # Data already shaped like {actual_root: ...} (e.g. from an XML
            # source): use that key as the root element. (A single key that
            # holds a *list* can't be a root — XML has exactly one root
            # element — so that case wraps it in root_name instead.)
            inner_key, inner_val = next(iter(data.items()))
            root = ET.Element(_xml_name(inner_key))
            _fill(root, inner_val)
        else:
            root = ET.Element(_xml_name(root_name))
            _fill(root, data)

        rough = ET.tostring(root, encoding="unicode")
        pretty = minidom.parseString(rough).toprettyxml(indent=" " * indent)
        # Drop the extra blank lines minidom tends to add.
        return "\n".join(line for line in pretty.splitlines() if line.strip()) + "\n"


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _strip_nulls(value):
    """TOML has no null; drop None values instead of crashing on them."""

    if isinstance(value, dict):
        return {k: _strip_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_nulls(v) for v in value if v is not None]
    return value


def _xml_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _xml_name(name) -> str:
    """Turn an arbitrary key into a valid XML element/attribute name
    (JSON keys like "first name" or "2024" aren't valid tags)."""

    import re

    text = re.sub(r"[^\w.\-]", "_", str(name), flags=re.UNICODE)
    if not text or not (text[0].isalpha() or text[0] == "_"):
        text = f"_{text}"
    if text.lower().startswith("xml"):
        text = f"_{text}"
    return text


register(DataConverter())
