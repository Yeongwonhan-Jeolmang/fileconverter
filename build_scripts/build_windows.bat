@echo off
REM Build a standalone Windows executable (fileconverter.exe) with PyInstaller.

setlocal
cd /d "%~dp0\.."

echo Installing build dependencies...
python -m pip install --upgrade pip
python -m pip install -e .[all,dev]

echo Building GUI executable...
pyinstaller --noconfirm --clean --windowed --name FileConverter ^
  --add-data "gui/resources;gui/resources" ^
  gui/app.py

echo Building CLI executable...
pyinstaller --noconfirm --clean --console --name fileconverter-cli ^
  cli/main.py

echo.
echo Done. Executables are in dist\FileConverter\ and dist\fileconverter-cli\
echo Remember: audio/video conversion also requires ffmpeg on PATH.
endlocal
