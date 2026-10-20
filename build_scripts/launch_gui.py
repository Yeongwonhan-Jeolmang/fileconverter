"""PyInstaller entry point for the GUI.

``gui/app.py`` uses package-relative imports, so it can't be handed to
PyInstaller directly (the frozen app would die with "attempted relative
import with no known parent package"). This shim imports it through the
installed ``fileconverter`` package instead.
"""

import sys

from gui.app import main

if __name__ == "__main__":
    sys.exit(main())
