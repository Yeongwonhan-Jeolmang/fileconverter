"""FileConverter CLI — built with Click, progress bars via Rich.

Run ``fileconverter --help`` (or ``python -m fileconverter.cli.main --help``)
for full usage. Every subcommand also works via ``fileconverter <cmd> --help``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from .. import converters  # noqa: F401 — side effect: registers all converters
from ..core import config as config_module
from ..core import history as history_module
from ..core import presets as presets_module
from ..core.base import ConversionJob, ConversionOptions
from ..core.engine import ConversionEngine, build_output_path
from ..core.exceptions import FileConverterError
from ..core.formats import detect_format
from ..core.logging_setup import setup_logging
from ..core.registry import all_converters, conversion_matrix
from ..utils.paths import expand_inputs

try:
    from rich.console import Console
    from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
    from rich.table import Table

    console: Optional[Console] = Console()
except ImportError:  # Rich is optional; CLI still works with plain prints.
    console = None


def _echo(message: str) -> None:
    if console:
        console.print(message)
    else:
        click.echo(message)


def _parse_option_kv(pairs: tuple[str, ...]) -> dict:
    options: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise click.BadParameter(f"Option '{pair}' must be in key=value form")
        key, value = pair.split("=", 1)
        options[key] = _coerce(value)
    return options


def _coerce(value: str):
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    if "," in value and all(v.strip().lstrip("-").isdigit() for v in value.split(",")):
        return [int(v) for v in value.split(",")]
    return value


@click.group()
@click.option("--verbose", is_flag=True, help="Enable verbose logging to stderr.")
@click.version_option(package_name="fileconverter")
def cli(verbose: bool) -> None:
    """FileConverter — convert images, documents, spreadsheets, audio,
    video, and archives from the command line."""

    setup_logging(verbose=verbose)


@cli.command()
@click.argument("inputs", nargs=-1, required=True)
@click.option(
    "-t",
    "--to",
    "target_format",
    default=None,
    help="Target format, e.g. 'pdf', 'mp3', 'png'. Required unless --preset supplies one.",
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Output directory (default: alongside each source file).",
)
@click.option(
    "-r", "--recursive", is_flag=True, help="Recurse into directories / glob patterns."
)
@click.option(
    "--preset", default=None, help="Apply a saved preset (see 'fileconverter presets')."
)
@click.option(
    "-O",
    "--option",
    "raw_options",
    multiple=True,
    help="Converter option as key=value. Repeatable.",
)
@click.option(
    "--workers",
    default=None,
    type=int,
    help="Number of parallel conversion workers (default: from config).",
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be converted without doing it."
)
@click.option(
    "--json-output",
    is_flag=True,
    help="Print machine-readable JSON results (for scripting).",
)
def convert(
    inputs: tuple[str, ...],
    target_format: Optional[str],
    output_dir: Optional[str],
    recursive: bool,
    preset: Optional[str],
    raw_options: tuple[str, ...],
    workers: Optional[int],
    dry_run: bool,
    json_output: bool,
) -> None:
    """Convert one or more files (supports globs and directories).

    Examples:

      fileconverter convert photo.png -t jpg

      fileconverter convert ./docs -t pdf --recursive

      fileconverter convert "*.csv" -t xlsx -o ./out

      fileconverter convert episode.wav -t mp3 --preset podcast-mp3
    """

    cfg = config_module.load_config()
    options_dict = _parse_option_kv(raw_options)

    if preset:
        try:
            preset_obj = presets_module.get_preset(preset)
        except FileConverterError as exc:
            raise click.ClickException(str(exc))
        target_format = target_format or preset_obj.target_format
        merged = {**preset_obj.options, **options_dict}
        options_dict = merged

    if not target_format:
        raise click.ClickException(
            "Target format required: pass -t/--to, or --preset with a preset that defines one."
        )

    try:
        files = expand_inputs(list(inputs), recursive=recursive)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))

    if not files:
        raise click.ClickException("No matching input files found.")

    out_dir = Path(output_dir) if output_dir else None
    jobs = [
        ConversionJob(
            source_path=f,
            output_path=build_output_path(f, target_format, out_dir),
            target_format=target_format,
            options=ConversionOptions.from_dict(options_dict),
        )
        for f in files
    ]

    if dry_run:
        for job in jobs:
            _echo(f"[dry-run] {job.source_path}  ->  {job.output_path}")
        return

    engine = ConversionEngine(
        max_workers=workers or cfg.max_workers, verify_output=cfg.verify_output
    )
    results = []

    if console and not json_output:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress_ui:
            task_ids = {
                job.job_id: progress_ui.add_task(job.source_path.name, total=100)
                for job in jobs
            }

            def on_progress(job_id: str, fraction: float, message: str) -> None:
                progress_ui.update(
                    task_ids[job_id],
                    completed=fraction * 100,
                    description=f"{Path(job_id.split('->')[0]).name}: {message}",
                )

            def on_done(result) -> None:
                results.append(result)

            engine.run_batch(jobs, on_progress=on_progress, on_done=on_done)
    else:

        def on_done(result) -> None:
            results.append(result)
            status = "OK" if result.success else "FAILED"
            if not json_output:
                _echo(
                    f"[{status}] {result.job.source_path} -> {result.output_path or '?'}"
                )

        engine.run_batch(jobs, on_done=on_done)

    engine.shutdown(wait=True)

    if json_output:
        payload = [
            {
                "source": str(r.job.source_path),
                "output": str(r.output_path) if r.output_path else None,
                "target_format": r.job.target_format,
                "success": r.success,
                "error": r.error,
                "duration_seconds": r.duration_seconds,
            }
            for r in results
        ]
        click.echo(json.dumps(payload, indent=2))

    failed = sum(1 for r in results if not r.success)
    if failed:
        _echo(f"\n{failed} of {len(results)} conversions failed.")
        sys.exit(1)
    else:
        _echo(f"\nAll {len(results)} conversions succeeded.")


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option(
    "-t",
    "--to",
    "target_format",
    required=True,
    help="Target format to convert new files to.",
)
@click.option("-o", "--output-dir", type=click.Path(file_okay=False), default=None)
@click.option("--interval", default=2.0, type=float, help="Poll interval in seconds.")
def watch(
    folder: str, target_format: str, output_dir: Optional[str], interval: float
) -> None:
    """Watch a folder and auto-convert any new files that appear in it.

    Press Ctrl+C to stop watching.
    """

    from ..core.watcher import FolderWatcher

    cfg = config_module.load_config()
    engine = ConversionEngine(
        max_workers=cfg.max_workers, verify_output=cfg.verify_output
    )
    out_dir = Path(output_dir) if output_dir else None

    def announce(path: Path) -> None:
        _echo(f"Detected new file: {path.name} -- converting to {target_format}")

    watcher = FolderWatcher(
        Path(folder),
        target_format,
        engine,
        output_dir=out_dir,
        poll_interval=interval,
        on_new_job=announce,
    )
    _echo(
        f"Watching '{folder}' for new files (target format: {target_format}). Press Ctrl+C to stop."
    )
    watcher.start()
    try:
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        _echo("\nStopping watcher...")
        watcher.stop()
        engine.shutdown(wait=True)


@cli.command()
def doctor() -> None:
    """Check which converters and optional external tools are available."""

    if console:
        table = Table(title="FileConverter — Environment Check")
        table.add_column("Converter")
        table.add_column("Formats")
        table.add_column("Status")
        for conv in all_converters():
            available, reason = conv.check_available()
            status = (
                "[green]Available[/green]"
                if available
                else f"[red]Missing[/red] — {reason}"
            )
            formats = ", ".join(sorted(conv.input_formats | conv.output_formats))
            table.add_row(conv.name, formats, status if available else status)
        console.print(table)
    else:
        for conv in all_converters():
            available, reason = conv.check_available()
            click.echo(f"{conv.name}: {'OK' if available else 'MISSING'} ({reason})")


@cli.command()
def formats() -> None:
    """List every supported source format and its reachable targets."""

    matrix = conversion_matrix()
    if console:
        table = Table(title="Supported Conversions")
        table.add_column("From")
        table.add_column("To")
        for fmt, targets in sorted(matrix.items()):
            table.add_row(fmt, ", ".join(targets) if targets else "-")
        console.print(table)
    else:
        for fmt, targets in sorted(matrix.items()):
            click.echo(f"{fmt} -> {', '.join(targets) if targets else '(none)'}")


@cli.group()
def presets() -> None:
    """Manage conversion presets."""


@presets.command("list")
def presets_list() -> None:
    """List all built-in and custom presets."""

    for p in presets_module.list_presets():
        _echo(f"{p.name}: target={p.target_format} options={p.options}")


@presets.command("save")
@click.argument("name")
@click.option("-t", "--to", "target_format", required=True)
@click.option("-O", "--option", "raw_options", multiple=True)
def presets_save(name: str, target_format: str, raw_options: tuple[str, ...]) -> None:
    """Save a new custom preset."""

    options = _parse_option_kv(raw_options)
    presets_module.save_preset(name, target_format, options)
    _echo(f"Saved preset '{name}'.")


@presets.command("delete")
@click.argument("name")
def presets_delete(name: str) -> None:
    """Delete a custom preset."""

    presets_module.delete_preset(name)
    _echo(f"Deleted preset '{name}'.")


@cli.command()
@click.option("--limit", default=50, help="Number of recent entries to show.")
@click.option(
    "--export",
    "export_path",
    type=click.Path(),
    default=None,
    help="Export full history to a CSV file.",
)
@click.option("--clear", is_flag=True, help="Clear all history.")
def history(limit: int, export_path: Optional[str], clear: bool) -> None:
    """View, export, or clear the conversion history log."""

    if clear:
        history_module.clear()
        _echo("History cleared.")
        return

    if export_path:
        path = history_module.export_csv(export_path)
        _echo(f"Exported history to {path}")
        return

    entries = history_module.recent(limit=limit)
    if console:
        table = Table(title="Conversion History")
        table.add_column("When")
        table.add_column("Source")
        table.add_column("Target")
        table.add_column("Status")
        import datetime

        for e in entries:
            when = datetime.datetime.fromtimestamp(e.timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            status = (
                "[green]OK[/green]"
                if e.success
                else f"[red]FAILED[/red] {e.error or ''}"
            )
            table.add_row(
                when, Path(e.source_path).name, e.target_format or "-", status
            )
        console.print(table)
    else:
        for e in entries:
            click.echo(
                f"{e.source_path} -> {e.target_format}: {'OK' if e.success else 'FAILED'}"
            )


@cli.command()
@click.argument("path", type=click.Path())
def detect(path: str) -> None:
    """Detect the real format of a file (extension + magic-byte sniffing)."""

    fmt = detect_format(Path(path))
    _echo(f"{path}: {fmt or 'unknown'}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
