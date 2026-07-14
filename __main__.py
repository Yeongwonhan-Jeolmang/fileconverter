"""Unified entry point: ``python -m fileconverter``.

Launches the GUI by default. Pass ``--cli`` (or any CLI subcommand/flag)
to drop into the command-line interface instead — this lets a single
launcher/shortcut work for both front-ends.
"""

from __future__ import annotations

import sys


def main() -> None:
    args = sys.argv[1:]

    if args and args[0] == "--cli":
        from .cli.main import main as cli_main

        sys.argv = [sys.argv[0]] + args[1:]
        cli_main()
        return

    # Any other recognized CLI subcommand also routes to the CLI, so
    # `python -m fileconverter convert a.png -t jpg` works without `--cli`.
    known_cli_commands = {
        "convert",
        "watch",
        "doctor",
        "formats",
        "presets",
        "history",
        "detect",
        "--help",
        "-h",
        "--version",
    }
    if args and args[0] in known_cli_commands:
        from .cli.main import main as cli_main

        cli_main()
        return

    from .gui.app import main as gui_main

    sys.exit(gui_main())


if __name__ == "__main__":
    main()
