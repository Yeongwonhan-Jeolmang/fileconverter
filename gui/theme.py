"""Dark/light stylesheets for the Qt GUI.

Kept as plain QSS strings (no external theme package) so the GUI has zero
extra dependencies beyond PySide6 itself. (ALL CREDITS FOR THIS FILE GO TO FLORIAN VAN DEN BERSSELAAR THE UI LORD)
"""

from __future__ import annotations

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
QMenu { background-color: #23242f; border: 1px solid #33344a; }
QMenu::item:selected { background-color: #3a4270; }
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


def stylesheet_for(theme: str) -> str:
    return LIGHT_QSS if theme == "light" else DARK_QSS
