"""Menus must be wide enough for every label plus its shortcut, even when
the platform's native menu font differs from the stylesheet's (the cause
of clipped menu text on Windows). Runs headless; skips without PySide6."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setFont(QFont(instance.font().family(), 7))  # tiny "native" font
    return instance


def test_every_menu_fits_its_labels_and_shortcuts(app):
    from fileconverter.gui.app import MainWindow

    window = MainWindow()
    window.show()
    menus = [a.menu() for a in window.menuBar().actions()]
    menus += [a.menu() for m in list(menus) for a in m.actions() if a.menu()]
    assert len(menus) >= 6
    for menu in menus:
        menu.popup(window.mapToGlobal(window.rect().center()))
        app.processEvents()
        fm = menu.fontMetrics()
        for action in menu.actions():
            if action.isSeparator():
                continue
            label = fm.horizontalAdvance(action.text().replace("&", ""))
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            needed = label + (fm.horizontalAdvance(shortcut) + 24 if shortcut else 0)
            assert menu.width() >= needed, (menu.title(), action.text())
        menu.hide()
    window.close()
