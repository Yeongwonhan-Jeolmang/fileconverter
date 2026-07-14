#!/usr/bin/env bash
# Build a standalone macOS app bundle (FileConverter.app) with PyInstaller.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Installing build dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[all,dev]"

echo "Building GUI binary..."
pyinstaller --noconfirm --clean --windowed --name FileConverter \
  --add-data "gui/resources:gui/resources" \
  gui/app.py

echo "Building CLI binary..."
pyinstaller --noconfirm --clean --console --name fileconverter-cli \
  cli/main.py

echo
echo "Done. Find the FileConverter and fileconverter-cli binaries under dist/"
echo "Note: audio/video conversion also requires ffmpeg on PATH (apt/yum/pacman install ffmpeg)."
