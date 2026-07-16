"""Structured data conversion: YAML, JSON, TOML, XML.

Pure "data document" conversion — parses the source into a plain Python
dict/list tree, then re-serializes into the target format. No external
binaries required; PyYAML and toml/tomli(-w) are pure-Python pip packages.

Options:
  - xml_root: str — root element name when writing XML (default "root")
  - indent: int — indent width for JSON/XML output (default 2)
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
            src_ext = job.source_path.suffix.lower().lstrip(".")
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
        indent = options.get("indent", 2)
        if target == "json":
            import json

            job.output_path.write_text(
                json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8"
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
            job.output_path.write_bytes(tomli_w.dumps(data).encode("utf-8"))
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
            if not children:
                return elem.text.strip() if elem.text and elem.text.strip() else None
            obj: dict = {}
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
            return obj

        return {root.tag: _elem_to_obj(root)}

    def _data_to_xml(self, data, root_name: str, indent: int) -> str:
        from xml.etree import ElementTree as ET
        from xml.dom import minidom

        def _build(parent, key, value):
            if isinstance(value, dict):
                el = ET.SubElement(parent, str(key))
                for k, v in value.items():
                    _build(el, k, v)
            elif isinstance(value, list):
                for item in value:
                    _build(parent, key, item)
            else:
                el = ET.SubElement(parent, str(key))
                el.text = "" if value is None else str(value)

        if isinstance(data, dict) and len(data) == 1 and root_name not in data:
            # data already shaped like {actual_root: {...}} (e.g. from XML source)
            inner_key, inner_val = next(iter(data.items()))
            root = ET.Element(inner_key)
            if isinstance(inner_val, dict):
                for k, v in inner_val.items():
                    _build(root, k, v)
            else:
                root.text = "" if inner_val is None else str(inner_val)
        else:
            root = ET.Element(root_name)
            if isinstance(data, dict):
                for k, v in data.items():
                    _build(root, k, v)
            elif isinstance(data, list):
                for item in data:
                    _build(root, "item", item)
            else:
                root.text = str(data)

        rough = ET.tostring(root, encoding="unicode")
        pretty = minidom.parseString(rough).toprettyxml(indent=" " * indent)
        # Drop the extra blank lines minidom tends to add.
        return "\n".join(line for line in pretty.splitlines() if line.strip())


register(DataConverter())
