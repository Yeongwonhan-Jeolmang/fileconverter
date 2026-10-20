#!/usr/bin/env bash
# Build standalone Linux binaries with PyInstaller.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Installing build dependencies..."
python3 -m pip install --upgrade pip
# A regular (non-editable) install: PyInstaller can't reliably follow the
# import hooks that editable installs use.
python3 -m pip install ".[all,dev]"

echo "Building GUI binary..."
# Converters are discovered at runtime via pkgutil, which PyInstaller's
# static analysis can't see — so collect every fileconverter submodule.
pyinstaller --noconfirm --clean --windowed --name FileConverter \
  --collect-submodules fileconverter \
  build_scripts/launch_gui.py

echo "Building CLI binary..."
pyinstaller --noconfirm --clean --console --name fileconverter-cli \
  --collect-submodules fileconverter \
  build_scripts/launch_cli.py

echo
echo "Done. Find the FileConverter and fileconverter-cli binaries under dist/"
echo "Note: audio/video conversion also requires ffmpeg on PATH (apt/dnf/pacman install ffmpeg)."
