"""Path helpers: glob expansion and recursive directory walking."""

from __future__ import annotations

from pathlib import Path


def expand_inputs(inputs: list[str], recursive: bool = False) -> list[Path]:
    """Expand a list of file/dir/glob strings into concrete file paths.

    - A file path is used as-is.
    - A directory is expanded to its files (recursively if requested).
    - A glob pattern (containing '*', '?', or '[') is expanded via Path.glob
      relative to the current working directory.
    """

    results: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if any(ch in raw for ch in "*?[]"):
            base = Path(".")
            pattern = raw
            matches = base.rglob(pattern) if recursive else base.glob(pattern)
            results.extend(p for p in matches if p.is_file())
        elif path.is_dir():
            matches = path.rglob("*") if recursive else path.glob("*")
            results.extend(p for p in matches if p.is_file())
        elif path.is_file():
            results.append(path)
        else:
            raise FileNotFoundError(f"No such file, directory, or pattern: {raw}")
    return sorted(set(results))
