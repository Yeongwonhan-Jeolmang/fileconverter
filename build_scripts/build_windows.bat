@echo off
REM Build a standalone Windows executable (fileconverter.exe) with PyInstaller.

setlocal
cd /d "%~dp0\.."

echo Installing build dependencies...
python -m pip install --upgrade pip
REM A regular (non-editable) install: PyInstaller can't reliably follow the
REM import hooks that editable installs use.
python -m pip install .[all,dev]

echo Building GUI executable...
REM Converters are discovered at runtime via pkgutil, which PyInstaller's
REM static analysis can't see, so collect every fileconverter submodule.
pyinstaller --noconfirm --clean --windowed --name FileConverter ^
  --collect-submodules fileconverter ^
  build_scripts\launch_gui.py

echo Building CLI executable...
pyinstaller --noconfirm --clean --console --name fileconverter-cli ^
  --collect-submodules fileconverter ^
  build_scripts\launch_cli.py

echo.
echo Done. Executables are in dist\FileConverter\ and dist\fileconverter-cli\
echo Remember: audio/video conversion also requires ffmpeg on PATH.
endlocal
