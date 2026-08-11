"""FileConverter CLI — built with Click, progress bars via Rich.

Run ``fileconverter --help`` (or ``python -m fileconverter.cli.main --help``)
for full usage. Every subcommand also works via ``fileconverter <cmd> --help``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import click

from .. import converters  # noqa: F401 — side effect: registers all converters
from ..core import config as config_module
from ..core import history as history_module
from ..core import presets as presets_module
from ..core.base import ConversionJob, ConversionOptions
from ..core.engine import ConversionEngine, build_output_path, jobs_from_results_json
from ..core.exceptions import FileConverterError
from ..core.formats import detect_format
from ..core.logging_setup import setup_logging
from ..core.registry import all_converters, conversion_matrix, find_converter
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


def _echo_status(message: str, json_output: bool = False) -> None:
    """Like ``_echo``, but goes to stderr when ``json_output`` is set so
    status/summary lines never corrupt a stdout stream a caller is piping
    into ``jq`` or a file (e.g. ``convert ... --json-output > results.json``)."""

    if json_output:
        click.echo(message, err=True)
    else:
        _echo(message)


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
    "--dry-run",
    is_flag=True,
    help="Show what would be converted without doing it (source, output path, "
    "converter, and availability), then exit.",
)
@click.option(
    "--retry",
    "max_retries",
    default=0,
    type=int,
    help="Automatically retry failed conversions up to N extra times.",
)
@click.option(
    "--retry-delay",
    default=1.0,
    type=float,
    help="Seconds to wait between retry rounds (default: 1.0).",
)
@click.option(
    "--json-output",
    is_flag=True,
    help="Print machine-readable JSON results (for scripting; also enables 'fileconverter retry').",
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
    max_retries: int,
    retry_delay: float,
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
    overwrite_policy = (
        "rename" if cfg.overwrite_policy == "ask" else cfg.overwrite_policy
    )

    jobs: list[ConversionJob] = []
    skipped: list[Path] = []
    for f in files:
        output_path = build_output_path(
            f, target_format, out_dir, overwrite_policy=overwrite_policy
        )
        if output_path is None:
            skipped.append(f)
            continue
        jobs.append(
            ConversionJob(
                source_path=f,
                output_path=output_path,
                target_format=target_format,
                options=ConversionOptions.from_dict(options_dict),
            )
        )

    if skipped:
        _echo(
            f"Skipped {len(skipped)} file(s) whose output already exists "
            f"(overwrite_policy='{cfg.overwrite_policy}')."
        )

    if not jobs:
        raise click.ClickException(
            "Nothing left to convert after applying overwrite_policy."
        )

    if dry_run:
        _print_dry_run(jobs, target_format)
        return

    engine = ConversionEngine(
        max_workers=workers or cfg.max_workers, verify_output=cfg.verify_output
    )
    _run_jobs_and_report(
        engine,
        jobs,
        max_retries=max_retries,
        retry_delay=retry_delay,
        json_output=json_output,
    )


def _print_dry_run(jobs: list[ConversionJob], target_format: str) -> None:
    """Show exactly what a real run would do — source, output path, which
    converter would handle it, and whether that converter's dependencies
    are actually available — without converting anything."""

    availability_cache: dict[str, tuple[bool, str]] = {}

    def _converter_status(src_format: str) -> tuple[str, str]:
        converter = find_converter(src_format, target_format)
        if converter is None:
            return "-", "[red]no converter[/red]" if console else "NO CONVERTER"
        available, reason = availability_cache.setdefault(
            converter.name, converter.check_available()
        )
        if console:
            status = (
                "[green]ready[/green]"
                if available
                else f"[red]missing deps[/red] — {reason}"
            )
        else:
            status = "READY" if available else f"MISSING DEPS ({reason})"
        return converter.name, status

    if console:
        table = Table(title=f"Dry run — convert to '{target_format}'")
        table.add_column("Source")
        table.add_column("Output")
        table.add_column("Converter")
        table.add_column("Status")
        for job in jobs:
            src_format = detect_format(job.source_path)
            converter_name, status = _converter_status(src_format)
            table.add_row(
                str(job.source_path), str(job.output_path), converter_name, status
            )
        console.print(table)
        console.print(f"\n{len(jobs)} file(s) would be converted. Nothing was written.")
    else:
        for job in jobs:
            src_format = detect_format(job.source_path)
            converter_name, status = _converter_status(src_format)
            click.echo(
                f"[dry-run] {job.source_path} -> {job.output_path} "
                f"(converter: {converter_name}, {status})"
            )
        click.echo(f"\n{len(jobs)} file(s) would be converted. Nothing was written.")


def _run_jobs_and_report(
    engine: ConversionEngine,
    jobs: list[ConversionJob],
    max_retries: int = 0,
    retry_delay: float = 1.0,
    json_output: bool = False,
) -> None:
    """Shared batch-running logic for ``convert`` and ``retry``: renders a
    progress bar (or plain OK/FAILED lines), applies the retry-failed-only
    policy, prints a summary, and exits non-zero if anything still failed
    after retries."""

    results = []

    def on_retry(job: ConversionJob, attempt: int) -> None:
        if not json_output:
            _echo(f"[retry {attempt}] {job.source_path.name} failed, retrying...")

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

            engine.run_batch(
                jobs,
                on_progress=on_progress,
                on_done=on_done,
                max_retries=max_retries,
                retry_delay=retry_delay,
                on_retry=on_retry,
            )
    else:

        def on_done(result) -> None:
            results.append(result)
            status = "OK" if result.success else "FAILED"
            if not json_output:
                _echo(
                    f"[{status}] {result.job.source_path} -> {result.output_path or '?'}"
                )

        engine.run_batch(
            jobs,
            on_done=on_done,
            max_retries=max_retries,
            retry_delay=retry_delay,
            on_retry=on_retry,
        )

    engine.shutdown(wait=True)

    latest_by_id: dict[str, Any] = {}
    for r in results:
        latest_by_id[r.job.job_id] = r
    final_results = list(latest_by_id.values())

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
            for r in final_results
        ]
        click.echo(json.dumps(payload, indent=2))

    failed = sum(1 for r in final_results if not r.success)
    if failed:
        _echo_status(
            f"\n{failed} of {len(final_results)} conversions failed.", json_output
        )
        if not json_output:
            _echo(
                "Tip: re-run with --json-output > results.json, then "
                "'fileconverter retry results.json' to retry just the failures."
            )
        sys.exit(1)
    else:
        _echo_status(f"\nAll {len(final_results)} conversions succeeded.", json_output)


@cli.command("retry")
@click.argument("results_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--workers",
    default=None,
    type=int,
    help="Number of parallel conversion workers (default: from config).",
)
@click.option(
    "--retry",
    "max_retries",
    default=0,
    type=int,
    help="Automatically retry conversions that fail again, up to N extra times.",
)
@click.option(
    "--retry-delay", default=1.0, type=float, help="Seconds between retry rounds."
)
@click.option(
    "--json-output",
    is_flag=True,
    help="Print machine-readable JSON results (for scripting).",
)
def retry_cmd(
    results_file: str,
    workers: Optional[int],
    max_retries: int,
    retry_delay: float,
    json_output: bool,
) -> None:
    """Re-run only the failed conversions from a previous run's JSON results."""

    try:
        raw = json.loads(Path(results_file).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise click.ClickException(f"Could not read '{results_file}': {exc}")

    if not isinstance(raw, list):
        raise click.ClickException(
            f"'{results_file}' doesn't look like a --json-output results file "
            "(expected a JSON array)."
        )

    jobs = jobs_from_results_json(raw, only_failed=True)
    if not jobs:
        _echo_status(
            "No failed conversions found in that results file — nothing to retry.",
            json_output,
        )
        if json_output:
            click.echo("[]")
        return

    cfg = config_module.load_config()
    _echo_status(f"Retrying {len(jobs)} failed conversion(s)...", json_output)
    engine = ConversionEngine(
        max_workers=workers or cfg.max_workers, verify_output=cfg.verify_output
    )
    _run_jobs_and_report(
        engine,
        jobs,
        max_retries=max_retries,
        retry_delay=retry_delay,
        json_output=json_output,
    )


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
