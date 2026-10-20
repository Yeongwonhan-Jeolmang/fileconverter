"""Path helpers: glob expansion and recursive directory walking."""

from __future__ import annotations

import glob
from pathlib import Path


def _is_hidden(path: Path, base: Path) -> bool:
    """True if any component of ``path`` below ``base`` starts with a dot
    (e.g. ``.git``, ``.DS_Store``) — those are never conversion inputs."""

    try:
        parts = path.relative_to(base).parts
    except ValueError:
        parts = path.parts
    return any(part.startswith(".") for part in parts)


def expand_inputs(
    inputs: list[str], recursive: bool = False, keep_dirs: bool = False
) -> list[Path]:
    """Expand a list of file/dir/glob strings into concrete file paths.

    - A file path is used as-is.
    - A directory is expanded to its files (recursively if requested),
      skipping hidden files and folders.
    - A glob pattern (containing '*', '?', or '[') is expanded relative to
      the current working directory, or as-is if it's absolute. With
      ``recursive``, ``**`` matches any number of subdirectories, and a
      plain pattern like ``*.png`` also matches in every subdirectory.

    With ``keep_dirs``, a directory input is returned as-is instead of being
    expanded (used for "compress this folder into an archive").

    Raises ``FileNotFoundError`` for an input that is neither an existing
    path nor a glob pattern.
    """

    results: set[Path] = set()
    for raw in inputs:
        path = Path(raw).expanduser()
        # Check for a real path first, so files whose names happen to
        # contain glob characters (e.g. "photo [1].png") still work.
        if path.is_file():
            results.add(path)
            continue
        if path.is_dir() and keep_dirs:
            results.add(path)
            continue
        if path.is_dir():
            matches = path.rglob("*") if recursive else path.glob("*")
            results.update(
                p for p in matches if p.is_file() and not _is_hidden(p, path)
            )
            continue
        if any(ch in raw for ch in "*?["):
            pattern = str(path)
            matched = {Path(m) for m in glob.glob(pattern, recursive=recursive)}
            if recursive and "**" not in pattern:
                head, tail = str(path.parent), path.name
                matched.update(
                    Path(m) for m in glob.glob(str(Path(head) / "**" / tail), recursive=True)
                )
            # A pattern matching nothing isn't an error on its own (e.g.
            # "*.png" "*.jpg" with no JPGs); the caller reports an empty batch.
            results.update(p for p in matched if p.is_file())
            continue
        raise FileNotFoundError(f"No such file, directory, or pattern: {raw}")
    return sorted(results)
