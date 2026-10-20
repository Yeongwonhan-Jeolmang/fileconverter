# Changelog

## Unreleased — bug-fix & polish pass

### Fixed
- **Misnamed / extension-less files**: the engine detected the real format, but converters still looked at the file extension, so e.g. a PNG with no extension failed in most converters. Jobs now carry the detected format (`job.src_format`).
- **HEIC photos were routed to the video converter** (HEIC and MP4 share the `ftyp` signature). The ISO-BMFF brand is now checked, so iPhone HEICs — even ones saved as `.jpg` — are handled as images.
- **`.ods` files were detected as `.odt`** (both contain `content.xml`). ODF/EPUB archives are now identified by their `mimetype` entry.
- **Output collisions**: two inputs with the same name (`a/photo.png`, `b/photo.png`) converted into one `--output-dir` both wrote `photo.jpg`. Outputs are now reserved per batch (CLI and GUI).
- **LibreOffice could overwrite existing files** (it always writes `<stem>.<ext>` into the output folder, ignoring the rename policy) and parallel LibreOffice jobs failed with a shared profile. Each run now uses a private temp dir and profile.
- **Audio converter was broken on Python 3.13+** (`pydub` needs the removed `audioop` module) and AAC/WMA output always failed (wrong ffmpeg muxer names). Audio now drives ffmpeg directly, with progress and real cancellation; `pydub` is no longer a dependency.
- **`fileconverter retry` dropped the original options** (quality, preset settings, …). Results JSON now records options and retry reuses them.
- **`fileconverter --version` crashed** when run from a source checkout or PyInstaller build.
- **`python -m fileconverter retry …` opened the GUI** instead of the CLI (`retry` and `--verbose` were missing from the routing list).
- **Absolute glob patterns** (`/path/*.png`) crashed; glob characters in real filenames (`photo [1].png`) were misread as patterns.
- **Folder → archive was unreachable** (directories were never detected as `folder`), and "archive → folder" was advertised but didn't exist. Both now work: `convert ./project -t zip`, `convert backup.tar.gz -t folder`. `.tar.gz` outputs are named `name.tar.gz`, not `name.gz`.
- **Impossible conversions were offered**: VCF → ICS, DXF → PNG, CSV → XLS, DOCX → PPTX, PDF → PDF (which rasterized the PDF), etc. Converters now declare which pairs they really support; the contact converter no longer hijacks CSV → CSV.
- **JSON with a single list key → XML** produced a Python repr (`<users>[{'name': ...}]</users>`); TOML/YAML dates crashed JSON output; `None` crashed TOML output; keys like `"first name"` produced invalid XML. XML attributes are now preserved (`@attr` / `#text`).
- **ICS → CSV → ICS round trip** failed on timezone-aware times.
- **Transparent PNG → JPG** turned transparent areas black; `LA`/`P` images could fail outright. Alpha is now flattened onto white.
- **Animated GIF / multi-page TIFF → PDF** only kept the first frame.
- **PDF → image** wrote page 1 twice for multi-page PDFs.
- **DOCX → HTML** didn't escape text (`<` / `&` broke the page).
- **TXT → PDF** let long lines run off the page (wrapped by character count, not width).
- **Deleting a custom preset that overrides a built-in** was impossible; malformed `presets.json` entries crashed the preset list.
- **History DB connections were never closed** (one leaked handle per conversion); a history write failure could flip a successful job to failed.
- **Failed/cancelled jobs left truncated output files**; cancelled jobs were retried by `--retry`; a cancel arriving after a job finished marked it "Cancelled".
- **Ctrl+C in the CLI** left worker threads and ffmpeg/LibreOffice processes running.
- **GUI**: closing the window mid-batch could crash (running `QThread` destroyed); right-click → Cancel never appeared for running rows; the *Preserve metadata* and *Verify output* preferences had no effect; a non-object JSON in Advanced options crashed the batch.
- **PyInstaller build scripts** referenced a non-existent `gui/resources` folder and froze modules that use relative imports (the resulting app couldn't start); converters weren't collected because they're discovered at runtime.
- `normalize_ext(".PNG")` returned `""`.

### Improved
- "Convert All" skips rows that are already done (asks before redoing everything); changing a finished row's target makes it ready again; the status bar reports how many succeeded/failed.
- CLI lists the actual error for each failed file; `-h` works as `--help`; `watch` accepts `--preset` / `-O` and honours the overwrite policy; target formats like `.PNG` are normalized.
- Folder watcher ignores hidden files, partial downloads (`.part`, `.crdownload`, …) and file types that can't reach the target, and keeps running if a scan errors.
- Directory inputs skip hidden files/folders (`.git`, `.DS_Store`).
- PDF → image supports `page_range` and `dpi`; images accept `resize=1920x1080`.
- Documents: PDF → DOCX/ODT/RTF via LibreOffice's PDF import; Pandoc is tried if LibreOffice fails, with explicit reader/writer formats; PDFs with no text layer give a clear message instead of an empty file.
- Video: GIF export uses a generated palette (much better colours), resolutions keep aspect ratio and even dimensions, MP4/MOV get `+faststart`; more audio extraction targets (M4A, OGG).
- Output verification checks signatures for more formats (JPEG, WEBP, BMP, ODF, EPUB, gzip, 7z, FLAC, OGG, WAV).
- Windows: no console window flashes for each ffmpeg/LibreOffice run from the GUI build; cancel kills the whole process tree.
- History CSV export uses readable timestamps.
- Added a test suite (`pytest`) covering the engine, format detection, registry, presets, paths, watcher, CLI, and converters.
