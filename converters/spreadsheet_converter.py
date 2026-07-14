"""Spreadsheet / tabular data conversion via pandas.

Supports csv, tsv, xlsx, xls (read), json, parquet (optional, needs
pyarrow), and ods (optional, needs odfpy). Options:
  - delimiter: override CSV/TSV delimiter
  - sheet_name: select a sheet when reading xlsx/xls/ods
  - json_orient: pandas JSON orientation (default "records")
"""

from __future__ import annotations

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import MissingDependencyError
from ..core.registry import register

_TABULAR_FORMATS = frozenset({"csv", "tsv", "xlsx", "xls", "json", "parquet", "ods"})

_DEFAULT_DELIMITER = {"csv": ",", "tsv": "\t"}


class SpreadsheetConverter(BaseConverter):
    name = "Spreadsheet Converter"
    description = "Converts between CSV, TSV, Excel (xlsx/xls), JSON, Parquet, and ODS."
    input_formats = _TABULAR_FORMATS
    output_formats = _TABULAR_FORMATS

    def check_available(self) -> tuple[bool, str]:
        try:
            import pandas  # noqa: F401

            return True, "OK"
        except ImportError:
            return False, "Install with: pip install pandas openpyxl"

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            try:
                import pandas as pd
            except ImportError as exc:
                raise MissingDependencyError(
                    "pandas", "Install with: pip install pandas openpyxl"
                ) from exc

            src_ext = job.source_path.suffix.lower().lstrip(".")
            target = job.target_format.lower().lstrip(".")
            options = job.options

            if progress_cb:
                progress_cb(0.1, f"Reading {src_ext}")

            df = self._read(pd, job, src_ext, options)

            if progress_cb:
                progress_cb(0.6, f"Writing {target}")

            self._write(df, job, target, options)

            if progress_cb:
                progress_cb(0.95, "Done")

        return self._run_timed(job, _do)

    def _read(self, pd, job: ConversionJob, src_ext: str, options):
        sheet_name = options.get("sheet_name", 0)
        if src_ext in ("csv", "tsv"):
            delimiter = options.get("delimiter", _DEFAULT_DELIMITER.get(src_ext, ","))
            return pd.read_csv(job.source_path, delimiter=delimiter)
        if src_ext in ("xlsx", "xls"):
            return pd.read_excel(job.source_path, sheet_name=sheet_name)
        if src_ext == "ods":
            try:
                return pd.read_excel(
                    job.source_path, sheet_name=sheet_name, engine="odf"
                )
            except ImportError as exc:
                raise MissingDependencyError(
                    "odfpy", "Install with: pip install odfpy"
                ) from exc
        if src_ext == "json":
            return pd.read_json(
                job.source_path, orient=options.get("json_orient", "records")
            )
        if src_ext == "parquet":
            try:
                return pd.read_parquet(job.source_path)
            except ImportError as exc:
                raise MissingDependencyError(
                    "pyarrow", "Install with: pip install pyarrow"
                ) from exc
        raise ValueError(f"Unsupported spreadsheet source format: {src_ext}")

    def _write(self, df, job: ConversionJob, target: str, options) -> None:
        if target in ("csv", "tsv"):
            delimiter = options.get("delimiter", _DEFAULT_DELIMITER.get(target, ","))
            df.to_csv(job.output_path, sep=delimiter, index=False)
        elif target == "xlsx":
            df.to_excel(
                job.output_path,
                index=False,
                sheet_name=str(options.get("sheet_name") or "Sheet1"),
            )
        elif target == "xls":
            raise ValueError("Writing legacy .xls is not supported; use .xlsx instead.")
        elif target == "ods":
            try:
                df.to_excel(job.output_path, index=False, engine="odf")
            except ImportError as exc:
                raise MissingDependencyError(
                    "odfpy", "Install with: pip install odfpy"
                ) from exc
        elif target == "json":
            df.to_json(
                job.output_path, orient=options.get("json_orient", "records"), indent=2
            )
        elif target == "parquet":
            try:
                df.to_parquet(job.output_path, index=False)
            except ImportError as exc:
                raise MissingDependencyError(
                    "pyarrow", "Install with: pip install pyarrow"
                ) from exc
        else:
            raise ValueError(f"Unsupported spreadsheet target format: {target}")


register(SpreadsheetConverter())
