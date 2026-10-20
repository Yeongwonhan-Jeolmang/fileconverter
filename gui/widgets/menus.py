"""Menus that size themselves to their content.

Why this exists: Qt sizes menu items with the *style's* idea of the menu
font, but our stylesheet draws them with its own font (13px). On Windows
the native style measures with the system menu font (~9pt), so items were
laid out too narrow and their text/shortcuts clipped — by a different
amount in each menu, depending on its longest label.

:class:`AutoSizeMenu` fixes that independently of the platform style: every
time it opens it measures its labels and shortcuts with the font it will
actually draw with, and sets a minimum width that fits

    [check/icon] [label] <gap> [shortcut] [submenu arrow]

QMenu stretches every item to that width, and the stylesheet (see
``theme.MENU_*``) right-aligns shortcuts inside it, so shortcuts always
line up in their own column and nothing is cut off.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QWidget

from ..theme import (
    MENU_ITEM_PADDING_LEFT,
    MENU_ITEM_PADDING_RIGHT,
    MENU_SHORTCUT_GAP,
)


def _display_text(action: QAction) -> str:
    """The label as drawn: "&&" is a literal ampersand, "&x" a mnemonic,
    and anything after a tab is an inline shortcut (measured separately)."""

    text = action.text().split("\t", 1)[0]
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def _shortcut_text(action: QAction) -> str:
    inline = action.text().split("\t", 1)
    if len(inline) == 2:
        return inline[1]
    shortcut = action.shortcut()
    if shortcut.isEmpty():
        return ""
    return shortcut.toString(QKeySequence.SequenceFormat.NativeText)


class AutoSizeMenu(QMenu):
    """A QMenu that is always wide enough for its labels and shortcuts.

    Drop-in replacement for ``QMenu``. Use :meth:`addAutoSizeMenu` (or pass
    an ``AutoSizeMenu`` to ``addMenu``) for submenus so they fit too.
    """

    def __init__(self, title: str = "", parent: Optional[QWidget] = None):
        super().__init__(title, parent)
        # Recompute on every open: labels, shortcuts, visibility and the
        # theme font can all change while the app is running.
        self.aboutToShow.connect(self.fit_to_contents)

    def addAutoSizeMenu(self, title: str) -> "AutoSizeMenu":  # noqa: N802 — Qt naming
        submenu = AutoSizeMenu(title, self)
        self.addMenu(submenu)
        return submenu

    def required_width(self) -> int:
        """Width needed to show every visible item without clipping."""

        self.ensurePolished()  # make sure the stylesheet font is applied
        fm = self.fontMetrics()

        label_width = 0
        shortcut_width = 0
        has_indicator = False
        has_submenu = False
        for action in self.actions():
            if action.isSeparator() or not action.isVisible():
                continue
            label_width = max(label_width, fm.horizontalAdvance(_display_text(action)))
            shortcut = _shortcut_text(action)
            if shortcut:
                shortcut_width = max(shortcut_width, fm.horizontalAdvance(shortcut))
            if action.isCheckable() or not action.icon().isNull():
                has_indicator = True
            if action.menu() is not None:
                has_submenu = True

        line = fm.height()
        indicator = line + 6 if has_indicator else 0  # check mark / icon column
        arrow = line if has_submenu else 0  # submenu "›" column
        gap = MENU_SHORTCUT_GAP if shortcut_width else 0
        frame = 2 * self.style().pixelMetric(
            self.style().PixelMetric.PM_MenuPanelWidth, None, self
        ) + 2 * self.style().pixelMetric(
            self.style().PixelMetric.PM_MenuHMargin, None, self
        )
        return (
            MENU_ITEM_PADDING_LEFT
            + indicator
            + label_width
            + gap
            + shortcut_width
            + arrow
            + MENU_ITEM_PADDING_RIGHT
            + frame
            + 2  # 1px border on each side from the stylesheet
        )

    def fit_to_contents(self) -> None:
        width = self.required_width()
        screen = self.screen()
        if screen is not None:
            width = min(width, screen.availableGeometry().width())
        self.setMinimumWidth(width)
