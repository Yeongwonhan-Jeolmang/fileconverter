# FileConverter

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

A modular, professional-grade file conversion toolkit with both a **GUI** (primary) and a **CLI**. Convert images, documents, spreadsheets, audio, video, and archives.

Runs on Windows, macOS, and Linux. Works as a normal Python package, or as a **standalone executable** you can hand to someone who has never installed Python.

---

## Table of contents

- [Why this converter](#why-this-converter)
- [Supported formats](#supported-formats)
- [Quick start](#quick-start)
- [Installing only what you need](#installing-only-what-you-need)
- [Using the GUI](#using-the-gui)
- [Using the CLI](#using-the-cli)
- [Presets](#presets)
- [Folder watching](#folder-watching)
- [Conversion history](#conversion-history)
- [Configuration](#configuration)
- [Building a standalone executable](#building-a-standalone-executable)
- [Architecture](#architecture)
- [Adding a new format (plugin guide)](#adding-a-new-format-plugin-guide)
- [Running the test suite](#running-the-test-suite)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Why this converter

Most file converters are single-purpose (only images, or only via a website that uploads your files somewhere). FileConverter is different:

- **One tool, six domains.** Images, documents, spreadsheets, audio, video, and archives all share one engine, one queue, and one history log.
- **100% local.** Nothing is uploaded anywhere. Your files never leave your machine.
- **Plugin architecture.** Every format family is an isolated, swappable module (see [Architecture](#architecture)). Adding a new format never touches the engine, GUI, or CLI.
- **Batch & recursive by default.** Convert a whole folder tree in one command, with real parallelism.
- **Presets.** Save "Web-optimized JPEG", "Podcast MP3", or your own custom option sets and reuse them instantly.
- **Folder watching.** Point it at a "drop folder" and it auto-converts anything you save into it — great for scanner/export folders.
- **Automatic fallback engines.** If a document conversion has no lightweight native path, FileConverter automatically detects and uses LibreOffice or Pandoc on your system, instead of just failing.
- **Output verification.** After each conversion, the output file is sanity-checked (not just "does a file exist") — catches truncated/corrupt results other converters miss.
- **Full conversion history**, browsable and exportable to CSV, so you can always answer "what did I convert, when, and did it succeed?"
- **A real `doctor` command** that tells you exactly which optional engines (ffmpeg, LibreOffice, Pandoc, 7-Zip) are installed and what's missing, with install instructions — instead of a cryptic crash mid-conversion.
- **Format auto-detection.** Files with missing or wrong extensions are still identified correctly via magic-byte sniffing.
- **Scriptable.** The CLI has a `--json-output` mode designed for pipelines and other programs to consume.

## Supported formats

| Domain | Formats | Extra engine required? |
|---|---|---|
| **Images** | PNG, JPG/JPEG, BMP, GIF, WEBP, TIFF, ICO, HEIC/HEIF (read), PDF (image ⇄ PDF, multi-page) | None (Pillow only). PDF→image needs `pypdfium2`. HEIC needs `pillow-heif`. |
| **Documents** | TXT, Markdown, HTML, DOCX, PDF, RTF, ODT, PPTX | None for TXT/MD/HTML/simple PDF. Full DOCX/ODT/PPTX/PDF fidelity uses **LibreOffice** or **Pandoc** if installed (auto-detected). |
| **Spreadsheets** | CSV, TSV, XLSX, XLS (read), JSON, Parquet, ODS | `pandas` + `openpyxl` (Parquet needs `pyarrow`, ODS needs `odfpy`). |
| **Audio** | MP3, WAV, OGG, FLAC, AAC, M4A, WMA, AIFF | **ffmpeg** binary on PATH + `pydub`. |
| **Video** | MP4, AVI, MOV, MKV, WEBM, FLV, WMV, GIF export, audio extraction | **ffmpeg** binary on PATH. |
| **Archives** | ZIP, TAR, TAR.GZ, TAR.BZ2, TAR.XZ, 7Z, folder → archive, archive → folder | 7Z needs `py7zr`; everything else is in the standard library. |
| **Data** | YAML, JSON, TOML, XML | `pyyaml` for YAML, `tomli`/`tomli-w` for TOML. XML uses the standard library. |
| **Vector graphics** | SVG → PNG/PDF, DXF → SVG | `cairosvg` for SVG rendering, `ezdxf` for reading DXF. |
| **Fonts** | TTF, OTF, WOFF, WOFF2 | `fonttools` (WOFF2 also needs `brotli`). |
| **Ebooks** | EPUB, MOBI, AZW3, FB2, TXT, HTML | EPUB → TXT/HTML needs `ebooklib` + `beautifulsoup4`. MOBI/AZW3/FB2 and everything else use **Calibre**'s `ebook-convert` CLI if it's on PATH. |
| **Contacts & calendar** | VCF (vCard) ⇄ CSV, ICS (iCalendar) ⇄ CSV | `vobject`. Note: VCF and ICS only convert to/from CSV, not to each other. |

Run `fileconverter formats` any time to see the exact matrix your installed environment currently supports, and `fileconverter doctor` to see what's missing.

## Quick start

Requires **Python 3.10+** (skip this if you're using a [prebuilt executable](#building-a-standalone-executable)).

```bash
# 1. Get the code, then from the file-converter/ folder:
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install everything (GUI + all format families):
pip install -e ".[all]"

# 3. Launch the GUI (default):
python -m fileconverter

# ...or use the CLI:
python -m fileconverter --cli convert photo.png -t jpg
```

If you installed with `pip install -e .` (console scripts), you can also just run:

```bash
fileconverter-gui          # GUI
fileconverter convert ...  # CLI
```

Audio and video conversion additionally require the **ffmpeg** binary to be on your system `PATH`:

- **Windows:** [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html) (or `winget install ffmpeg`)
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg` (Debian/Ubuntu) or your distro's equivalent

Full DOCX/ODT/PPTX ⇄ PDF fidelity additionally benefits from **LibreOffice** (free, [libreoffice.org](https://www.libreoffice.org/)) being installed — FileConverter auto-detects it, no configuration needed.

MOBI/AZW3/FB2 ebook conversions additionally benefit from **Calibre** (free, [calibre-ebook.com](https://calibre-ebook.com/)) being installed — FileConverter auto-detects its `ebook-convert` CLI on PATH, no configuration needed. EPUB → TXT/HTML works without it.

## Installing only what you need

The core package (`pip install -e .`) only pulls in `click` and `rich` — enough for the CLI to run and report which converters are unavailable. Install format families à la carte with extras:

```bash
pip install -e ".[gui]"          # GUI front-end (PySide6)
pip install -e ".[images]"       # Pillow, pypdfium2
pip install -e ".[images-heic]"  # + HEIC/HEIF support
pip install -e ".[documents]"    # python-docx, pypdf, reportlab, markdown, html2text, bs4
pip install -e ".[spreadsheets]" # pandas, openpyxl, odfpy, pyarrow
pip install -e ".[audio]"        # pydub (still needs the ffmpeg binary separately)
pip install -e ".[archives]"     # py7zr (zip/tar work with zero extras)
pip install -e ".[watch]"        # watchdog (folder watching still works without it, just polls)
pip install -e ".[data]"         # pyyaml, tomli/tomli-w (JSON/XML work with zero extras)
pip install -e ".[vector]"       # cairosvg, ezdxf
pip install -e ".[fonts]"        # fonttools, brotli
pip install -e ".[ebooks]"       # ebooklib, beautifulsoup4 (MOBI/AZW3/FB2 still need Calibre separately)
pip install -e ".[contacts-calendar]"  # vobject
pip install -e ".[all]"          # everything above
pip install -e ".[dev]"          # pytest, pyinstaller, black, ruff — for contributors
```

Or use the plain requirements files if you're not using an editable install:

```bash
pip install -r requirements.txt      # everything, including the GUI
pip install -r requirements-cli.txt  # a light CLI-only starter set
```

## Using the GUI

Launch with `python -m fileconverter` (GUI is the default) or `fileconverter-gui`.

1. **Drag & drop** files or whole folders onto the drop zone, or use **Add Files** / **Add Folder**.
2. Each row gets its detected source format and a **target format dropdown** pre-filled with every format it can legally convert to.
3. Optionally set an **output directory** (default: alongside each source file) and the number of parallel **workers**.
4. Optionally type advanced, per-batch options as JSON, e.g. `{"quality": 85, "bitrate": "192k"}` — see [Converter options reference](#converter-options-reference).
5. Click **Convert All**. Each row shows live progress and a final status.
6. Use the **Tools** menu for dependency checks (**Doctor**), **Conversion History**, and **Manage Presets**. Use **View → Toggle Dark / Light Theme** to switch themes (saved automatically).

## Using the CLI

```text
fileconverter --help
```

### Convert files

```bash
# Single file
fileconverter convert photo.png -t jpg

# Multiple files
fileconverter convert a.png b.png c.png -t webp

# Glob pattern
fileconverter convert "*.csv" -t xlsx -o ./converted

# Whole folder, recursively
fileconverter convert ./scans -t pdf --recursive

# With options
fileconverter convert clip.mov -t mp4 -O bitrate=1500k -O resolution=1280x720 -O fps=30

# Dry run (see what would happen, convert nothing)
fileconverter convert ./docs -t pdf --recursive --dry-run

# Machine-readable output for scripting
fileconverter convert *.png -t jpg --json-output > results.json
```

### Other commands

```bash
fileconverter doctor                     # check installed converters & optional engines
fileconverter formats                    # list every supported source -> target pairing
fileconverter detect somefile            # detect real format via extension + magic bytes
fileconverter watch ./drop-folder -t pdf # auto-convert new files that appear in a folder
fileconverter presets list               # show built-in + custom presets
fileconverter presets save my-preset -t jpg -O quality=75
fileconverter presets delete my-preset
fileconverter history                    # show recent conversions
fileconverter history --export out.csv   # export full history to CSV
fileconverter history --clear            # wipe history
```

### Converter options reference

Pass options with `-O key=value` (CLI) or as a JSON object (GUI's advanced options box). Values are auto-coerced to int/float/bool/list where possible.

| Option | Applies to | Example |
|---|---|---|
| `quality` | images (JPEG/WEBP), audio via bitrate | `-O quality=80` |
| `resize` | images | `-O resize=1920,1080` |
| `rotate` | images | `-O rotate=90` |
| `preserve_metadata` | images, documents | `-O preserve_metadata=false` |
| `bitrate` | audio, video | `-O bitrate=192k` |
| `sample_rate` | audio | `-O sample_rate=44100` |
| `channels` | audio | `-O channels=2` |
| `gain_db` | audio | `-O gain_db=-3` |
| `resolution` | video | `-O resolution=1280x720` |
| `fps` | video | `-O fps=30` |
| `video_codec` | video | `-O video_codec=libx264` |
| `delimiter` | spreadsheets (csv/tsv) | `-O delimiter=;` |
| `sheet_name` | spreadsheets (xlsx/xls/ods) | `-O sheet_name=Sheet2` |
| `json_orient` | spreadsheets (json) | `-O json_orient=records` |

## Presets

Presets bundle a target format + option set under a name, so you don't retype the same flags every time.

Built-in presets: `web-optimized-jpeg`, `lossless-png`, `podcast-mp3`, `archival-pdf`, `compact-mp4`.

```bash
fileconverter presets list
fileconverter convert vacation.png -t jpg --preset web-optimized-jpeg
fileconverter presets save my-podcast -t mp3 -O bitrate=96k -O sample_rate=22050
```

Custom presets are stored in `~/.fileconverter/presets.json`.

## Folder watching

Point FileConverter at a folder; anything new that shows up gets converted automatically. Useful for scanner output folders, browser download folders, or a shared "convert-me" drop folder.

```bash
fileconverter watch ~/Downloads/to-convert -t pdf
```

Uses efficient event-based watching if `watchdog` is installed, otherwise falls back to lightweight polling (still fully functional, just checks every couple of seconds).

## Conversion history

Every conversion (success or failure) is logged to a local SQLite database at `~/.fileconverter/history.sqlite3`.

```bash
fileconverter history               # last 50 conversions
fileconverter history --limit 500   # more history
fileconverter history --export history.csv
fileconverter history --clear
```

The GUI's **Tools → Conversion History** shows the same data.

## Configuration

Settings persist at `~/.fileconverter/config.json` and are shared between the GUI and CLI:

```json
{
  "theme": "dark",
  "default_output_dir": null,
  "max_workers": 4,
  "overwrite_policy": "ask",
  "preserve_metadata": true,
  "last_target_format": "jpg",
  "recent_files": [],
  "verify_output": true
}
```

You generally don't need to edit this by hand — the GUI updates it automatically (theme toggle, worker count, last-used format).

## Building a standalone executable

For end users who don't have Python installed, build a native executable with [PyInstaller](https://pyinstaller.org/):

```bash
# Windows (from an elevated or regular shell, in file-converter/)
build_scripts\build_windows.bat

# macOS
bash build_scripts/build_macos.sh

# Linux
bash build_scripts/build_linux.sh
```

Each script installs build dependencies and produces:

- `dist/FileConverter/` (Windows/Linux) or `FileConverter.app` (macOS) — the **GUI**, windowed, no console.
- `dist/fileconverter-cli/` — the **CLI**, as a console executable.

Copy either output folder anywhere (a USB stick, another machine of the same OS) and run it directly — no Python installation needed on the target machine. Audio/video conversion on the target machine still requires the `ffmpeg` binary to be present on its `PATH` (PyInstaller does not bundle ffmpeg since it's a separate, large, license-distinct binary — see [Troubleshooting](#troubleshooting) for a bundling recipe if you want a single self-contained folder).

## Architecture

```text
fileconverter/
├── core/                  # Front-end-agnostic engine (no GUI/CLI imports)
│   ├── base.py             # BaseConverter contract, ConversionJob/Result
│   ├── registry.py          # Converter plugin registry & lookup
│   ├── engine.py             # Thread-pooled conversion engine, output verification
│   ├── formats.py             # Extension + magic-byte format detection
│   ├── config.py               # Persistent user settings
│   ├── history.py               # SQLite conversion history log
│   ├── presets.py                 # Named option-set presets
│   ├── watcher.py                   # Folder watching (auto-convert new files)
│   ├── checksums.py                   # Output integrity verification
│   ├── exceptions.py                   # Structured exception hierarchy
│   └── logging_setup.py                 # Shared logging config
├── converters/             # One file per format family — the plugins
│   ├── image_converter.py
│   ├── document_converter.py
│   ├── spreadsheet_converter.py
│   ├── audio_converter.py
│   ├── video_converter.py
│   ├── archive_converter.py
│   ├── data_converter.py
│   ├── vector_converter.py
│   ├── font_converter.py
│   ├── ebook_converter.py
│   └── contact_calendar_converter.py
├── gui/                    # PySide6 desktop front-end
│   ├── app.py               # Main window
│   ├── theme.py               # Dark/light QSS stylesheets
│   └── widgets/                 # DropArea, QueueTable
├── cli/                    # Click-based command-line front-end
│   └── main.py
└── utils/                  # Small shared helpers (glob/dir expansion)
```

**Design principles:**

- `core/` never imports from `gui/` or `cli/` — the engine is fully reusable and unit-testable on its own.
- Every converter subclasses `BaseConverter` and declares `input_formats` / `output_formats`; the engine picks the right one automatically via the registry — front-ends never talk to converters directly.
- The registry is populated by **auto-import**: `fileconverter/converters/__init__.py` discovers every `*_converter.py` file at import time. Adding a format is a one-file change (see below).
- The GUI runs conversions on a background `QThread` so the window never freezes, with progress relayed back via Qt signals (thread-safe).
- The CLI and GUI share 100% of the core logic — presets, history, config, and the engine itself — so behavior is always consistent between the two.

## Adding a new format (plugin guide)

1. Create `fileconverter/converters/my_format_converter.py`.
2. Subclass `BaseConverter`:

```python
from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.registry import register

class MyFormatConverter(BaseConverter):
    name = "My Format Converter"
    input_formats = frozenset({"foo"})
    output_formats = frozenset({"bar"})

    def convert(self, job: ConversionJob, progress_cb: ProgressCallback = None) -> ConversionResult:
        def _do():
            # read job.source_path, write job.output_path, honor job.options
            if progress_cb:
                progress_cb(0.5, "Halfway there")
            ...
        return self._run_timed(job, _do)

register(MyFormatConverter())
```

3. That's it. Because `converters/__init__.py` auto-imports every `*_converter.py` file, your new format instantly appears in `fileconverter formats`, the GUI's target-format dropdown, and the engine — with zero changes anywhere else.
4. Add a test in `tests/test_my_format_converter.py` following the existing tests as a template.

## Running the test suite

```bash
pip install -e ".[dev,all]"
pytest
```

Tests that need an optional dependency (e.g. `pandas`, `PIL`) skip gracefully via `pytest.importorskip` if it isn't installed, so `pytest` works even with a partial install.

## Troubleshooting

**"No converter registered for 'x' -> 'y'"**
Run `fileconverter formats` to confirm that pairing is supported at all, and `fileconverter doctor` to check whether the relevant converter's dependencies are installed.

**Audio/video conversion fails immediately with a `MissingDependencyError`**
Install the `ffmpeg` binary and make sure it's on your `PATH` (`ffmpeg -version` should work in a terminal). This is a separate binary from any Python package.

**DOCX/PPTX/ODT conversions are text-only or fail**
Install [LibreOffice](https://www.libreoffice.org/) (recommended, richest fidelity) or [Pandoc](https://pandoc.org/); FileConverter auto-detects either and uses it as a fallback for anything without a lightweight native path.

**I want a single-folder executable that also includes ffmpeg**
Download a static ffmpeg build for your OS, drop `ffmpeg`/`ffmpeg.exe` next to the PyInstaller output folder, and either add that folder to `PATH` at runtime or set `os.environ["PATH"]` to include it before launching — PyInstaller's `--add-binary` flag can also embed it directly into the bundle.

**The GUI window doesn't open on Linux**
Make sure the Qt X11/Wayland runtime libraries are present (`libxkbcommon`, `libGL`, `fontconfig`, standard X11 libs) — these are normally already present on any desktop Linux install; headless servers need them installed explicitly.

**Where are my settings/history/presets stored?**
All in `~/.fileconverter/`: `config.json`, `history.sqlite3`, `presets.json`, `fileconverter.log`.

## License

MIT — see [`LICENSE`](LICENSE).