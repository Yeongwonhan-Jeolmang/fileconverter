"""Dark/light stylesheets for the Qt GUI.

Kept as plain QSS strings (no external theme package) so the GUI has zero
extra dependencies beyond PySide6 itself. (ALL CREDITS FOR THIS FILE GO TO FLORIAN VAN DEN BERSSELAAR THE UI LORD)
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication

# -- Menus ---------------------------------------------------------------
# Shared by the stylesheet below and gui/widgets/menus.AutoSizeMenu, which
# uses the same numbers to compute how wide each menu must be.
MENU_FONT_PX = 13
MENU_ITEM_PADDING_V = 6
MENU_ITEM_PADDING_LEFT = 14
MENU_ITEM_PADDING_RIGHT = 18
MENU_SHORTCUT_GAP = 36  # minimum space between a label and its shortcut


def _menu_qss(bg: str, border: str, text: str, muted: str, hover: str, hover_text: str) -> str:
    """Complete menu rules. Giving QMenu::item a full box model (font,
    padding, border) makes Qt's stylesheet engine measure *and* draw items
    with the same font; with only a ``:selected`` rule it falls back to the
    platform style for sizing, which on Windows measures with the system
    menu font and clips the text."""

    return f"""
QMenu {{
    background-color: {bg};
    border: 1px solid {border};
    padding: 4px 0px;
    font-size: {MENU_FONT_PX}px;
}}
QMenu::item {{
    background-color: transparent;
    color: {text};
    font-size: {MENU_FONT_PX}px;
    padding: {MENU_ITEM_PADDING_V}px {MENU_ITEM_PADDING_RIGHT}px {MENU_ITEM_PADDING_V}px {MENU_ITEM_PADDING_LEFT}px;
    border: none;
    margin: 0px 4px;
    border-radius: 4px;
}}
QMenu::item:selected {{ background-color: {hover}; color: {hover_text}; }}
QMenu::item:disabled {{ color: {muted}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 6px; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
"""

DARK_QSS = """
QWidget {
    background-color: #1e1f26;
    color: #e8e8ec;
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog { background-color: #1e1f26; }
QLabel#Header { font-size: 20px; font-weight: 600; color: #ffffff; }
QLabel#SubHeader { color: #9a9cae; font-size: 12px; }
QFrame#DropArea {
    border: 2px dashed #3a3c4d;
    border-radius: 12px;
    background-color: #262835;
}
QFrame#DropArea[dragActive="true"] {
    border-color: #6c8bff;
    background-color: #262b45;
}
QPushButton {
    background-color: #6c8bff;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover { background-color: #7f9aff; }
QPushButton:pressed { background-color: #5a76e0; }
QPushButton:disabled { background-color: #3a3c4d; color: #7c7e91; }
QPushButton#Secondary {
    background-color: #2c2e3d;
    color: #e8e8ec;
}
QPushButton#Secondary:hover { background-color: #383a4c; }
QPushButton#Danger { background-color: #e05a5a; }
QPushButton#Danger:hover { background-color: #ef6f6f; }
QTableWidget {
    background-color: #23242f;
    gridline-color: #33344a;
    border: 1px solid #33344a;
    border-radius: 8px;
    selection-background-color: #3a4270;
}
QHeaderView::section {
    background-color: #262835;
    color: #9a9cae;
    padding: 6px;
    border: none;
    font-weight: 600;
}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #262835;
    border: 1px solid #33344a;
    border-radius: 6px;
    padding: 4px 8px;
}
QProgressBar {
    background-color: #262835;
    border-radius: 6px;
    text-align: center;
    height: 16px;
}
QProgressBar::chunk { background-color: #6c8bff; border-radius: 6px; }
QStatusBar { background-color: #17181f; color: #9a9cae; }
QMenuBar { background-color: #17181f; }
QMenuBar::item:selected { background-color: #2c2e3d; }
QTabWidget::pane { border: 1px solid #33344a; border-radius: 8px; }
QTabBar::tab {
    background-color: #23242f;
    padding: 8px 16px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: #9a9cae;
}
QTabBar::tab:selected { background-color: #2c2e3d; color: #ffffff; }
"""

LIGHT_QSS = """
QWidget {
    background-color: #f6f7fb;
    color: #1c1d24;
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog { background-color: #f6f7fb; }
QLabel#Header { font-size: 20px; font-weight: 600; color: #101116; }
QLabel#SubHeader { color: #6a6c7d; font-size: 12px; }
QFrame#DropArea {
    border: 2px dashed #c7c9db;
    border-radius: 12px;
    background-color: #ffffff;
}
QFrame#DropArea[dragActive="true"] {
    border-color: #4863d6;
    background-color: #eef1ff;
}
QPushButton {
    background-color: #4863d6;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover { background-color: #5a74e6; }
QPushButton:pressed { background-color: #3c53bd; }
QPushButton:disabled { background-color: #d8dae6; color: #9799a8; }
QPushButton#Secondary {
    background-color: #e9ebf3;
    color: #1c1d24;
}
QPushButton#Secondary:hover { background-color: #dcdfef; }
QPushButton#Danger { background-color: #d94a4a; }
QPushButton#Danger:hover { background-color: #e56060; }
QTableWidget {
    background-color: #ffffff;
    gridline-color: #e3e5ef;
    border: 1px solid #e3e5ef;
    border-radius: 8px;
    selection-background-color: #dbe1ff;
}
QHeaderView::section {
    background-color: #eef0f7;
    color: #5c5e70;
    padding: 6px;
    border: none;
    font-weight: 600;
}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #ffffff;
    border: 1px solid #d5d7e3;
    border-radius: 6px;
    padding: 4px 8px;
}
QProgressBar {
    background-color: #e9ebf3;
    border-radius: 6px;
    text-align: center;
    height: 16px;
}
QProgressBar::chunk { background-color: #4863d6; border-radius: 6px; }
QStatusBar { background-color: #eef0f7; color: #5c5e70; }
"""


DARK_QSS += _menu_qss(
    bg="#23242f",
    border="#33344a",
    text="#e8e8ec",
    muted="#6c6e80",
    hover="#3a4270",
    hover_text="#ffffff",
)
LIGHT_QSS += _menu_qss(
    bg="#ffffff",
    border="#dcdfea",
    text="#1c1d24",
    muted="#a3a5b5",
    hover="#dfe5ff",
    hover_text="#1c1d24",
)


def stylesheet_for(theme: str) -> str:
    return LIGHT_QSS if theme == "light" else DARK_QSS


def resolve_theme(theme: str) -> str:
    """Resolve a config theme value to a concrete ``"dark"``/``"light"``.
    """

    if theme == "light":
        return "light"
    if theme != "system":
        return "dark"

    app = QGuiApplication.instance()
    if app is None:
        return "dark"
    style_hints = QGuiApplication.styleHints()
    color_scheme = getattr(style_hints, "colorScheme", None)
    if color_scheme is None:
        return "dark"
    try:
        from PySide6.QtCore import Qt

        scheme = color_scheme()
        if scheme == Qt.ColorScheme.Light:
            return "light"
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
    except Exception:
        pass
    return "dark"
