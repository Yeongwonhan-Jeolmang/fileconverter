"""The conversion queue table: one row per file, with per-row target
format, progress bar, and status."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHeaderView,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
)

from ...core.formats import detect_format
from ...core.registry import supported_targets

COLUMNS = ["File", "Source Format", "Target Format", "Progress", "Status"]


class QueueTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(COLUMNS)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        self._paths: dict[int, Path] = {}

    def add_file(self, path: Path, default_target: Optional[str] = None) -> int:
        row = self.rowCount()
        self.insertRow(row)
        self._paths[row] = path

        self.setItem(row, 0, QTableWidgetItem(str(path)))

        src_format = detect_format(path) or "?"
        self.setItem(row, 1, QTableWidgetItem(src_format))

        target_combo = QComboBox()
        targets = supported_targets(src_format) or ["(no converter available)"]
        target_combo.addItems(targets)
        if default_target and default_target in targets:
            target_combo.setCurrentText(default_target)
        self.setCellWidget(row, 2, target_combo)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        self.setCellWidget(row, 3, progress)

        status_item = QTableWidgetItem("Queued")
        self.setItem(row, 4, status_item)

        return row

    def path_for_row(self, row: int) -> Path:
        return self._paths[row]

    def target_format_for_row(self, row: int) -> str:
        widget: QComboBox = self.cellWidget(row, 2)  # type: ignore[assignment]
        return widget.currentText()

    def set_progress(self, row: int, fraction: float, message: str = "") -> None:
        progress: QProgressBar = self.cellWidget(row, 3)  # type: ignore[assignment]
        progress.setValue(int(fraction * 100))
        if message:
            status_item = self.item(row, 4)
            if status_item is not None:
                status_item.setText(message)

    def set_status(self, row: int, status: str) -> None:
        status_item = self.item(row, 4)
        if status_item is not None:
            status_item.setText(status)

    def clear_all(self) -> None:
        self.setRowCount(0)
        self._paths.clear()

    def remove_row(self, row: int) -> None:
        self.removeRow(row)
        # Re-key the paths dict since row indices shift after removal.
        self._paths = {
            (r if r < row else r - 1): p for r, p in self._paths.items() if r != row
        }
