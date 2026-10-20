"""Standalone dialogs for the GUI's Tools/Preferences menus.

These replace the original ``QMessageBox.information(...)`` walls of text
for Doctor/History/Presets with real, sortable tables, and add a
Preferences dialog that's the first place in the GUI where every
``AppConfig`` field (not just theme and worker count) is actually
editable.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...core import history as history_module
from ...core import presets as presets_module
from ...core.config import AppConfig
from ...core.exceptions import FileConverterError
from ...core.registry import all_converters


def _make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setSortingEnabled(True)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    return table


class DoctorDialog(QDialog):
    """Sortable table of every converter and whether its dependencies are
    installed — the GUI equivalent of ``fileconverter doctor``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dependency Check")
        self.resize(640, 420)

        layout = QVBoxLayout(self)
        self.table = _make_table(["Converter", "Formats", "Status"])
        layout.addWidget(self.table)

        # Sorting must be off while filling: with it on, Qt re-sorts after
        # every setItem() and later cells land in the wrong (or no) row.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for conv in sorted(all_converters(), key=lambda c: c.name):
            available, reason = conv.safe_check_available()
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(conv.name))
            formats = ", ".join(sorted(conv.input_formats | conv.output_formats))
            self.table.setItem(row, 1, QTableWidgetItem(formats))
            status_item = QTableWidgetItem(
                ("Available" if available else "Missing")
                + (f" \u2014 {reason}" if not available else "")
            )
            status_item.setForeground(
                Qt.GlobalColor.green if available else Qt.GlobalColor.red
            )
            self.table.setItem(row, 2, status_item)
        self.table.setSortingEnabled(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
            self.accept
        )
        layout.addWidget(buttons)


class HistoryDialog(QDialog):
    """Sortable, exportable conversion history — replaces the old
    newline-joined ``QMessageBox``."""

    def __init__(self, parent=None, limit: int = 200):
        super().__init__(parent)
        self.setWindowTitle("Conversion History")
        self.resize(760, 480)
        self._limit = limit

        layout = QVBoxLayout(self)
        self.table = _make_table(["When", "Source", "Target", "Status"])
        layout.addWidget(self.table)

        button_row = QHBoxLayout()
        export_btn = QPushButton("Export CSV\u2026")
        export_btn.setObjectName("Secondary")
        export_btn.clicked.connect(self._on_export)
        clear_btn = QPushButton("Clear History")
        clear_btn.setObjectName("Danger")
        clear_btn.clicked.connect(self._on_clear)
        button_row.addWidget(export_btn)
        button_row.addWidget(clear_btn)
        button_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self._reload()

    def _reload(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for entry in history_module.recent(limit=self._limit):
            row = self.table.rowCount()
            self.table.insertRow(row)
            when = datetime.datetime.fromtimestamp(entry.timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            self.table.setItem(row, 0, QTableWidgetItem(when))
            self.table.setItem(row, 1, QTableWidgetItem(Path(entry.source_path).name))
            self.table.setItem(row, 2, QTableWidgetItem(entry.target_format or "-"))
            status_text = (
                "OK" if entry.success else f"Failed \u2014 {entry.error or ''}"
            )
            status_item = QTableWidgetItem(status_text)
            status_item.setToolTip(entry.error or "")
            status_item.setForeground(
                Qt.GlobalColor.green if entry.success else Qt.GlobalColor.red
            )
            self.table.setItem(row, 3, status_item)
        self.table.setSortingEnabled(True)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export history to CSV", "history.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            history_module.export_csv(path, limit=10_000)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Exported", f"History exported to:\n{path}")

    def _on_clear(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Clear history",
            "Permanently delete all conversion history? This can't be undone.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            history_module.clear()
            self._reload()


class PresetsDialog(QDialog):
    """Browsable, actually-actionable preset list: apply a preset to the
    currently selected queue rows, or delete a custom one."""

    # Emitted with (target_format, options) when "Apply to Selected Rows"
    # is clicked — MainWindow applies it to the queue's current selection.
    presetApplied = Signal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Presets")
        self.resize(560, 400)

        layout = QVBoxLayout(self)
        self.table = _make_table(["Name", "Target", "Options"])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.table)

        hint = QLabel(
            "Select a preset, then apply it to the rows currently selected in the queue."
        )
        hint.setObjectName("SubHeader")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        button_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply to Selected Rows")
        self.apply_btn.clicked.connect(self._on_apply)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("Danger")
        self.delete_btn.clicked.connect(self._on_delete)
        button_row.addWidget(self.apply_btn)
        button_row.addWidget(self.delete_btn)
        button_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self._reload()

    def _reload(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for preset in presets_module.list_presets():
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(preset.name)
            is_builtin = preset.name in presets_module.BUILTIN_PRESETS
            name_item.setToolTip("Built-in preset" if is_builtin else "Custom preset")
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(preset.target_format))
            self.table.setItem(row, 2, QTableWidgetItem(str(preset.options)))
        self.table.setSortingEnabled(True)

    def _selected_preset_name(self) -> Optional[str]:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            return None
        row = next(iter(rows))
        item = self.table.item(row, 0)
        return item.text() if item else None

    def _on_apply(self) -> None:
        name = self._selected_preset_name()
        if not name:
            QMessageBox.information(
                self, "No preset selected", "Select a preset first."
            )
            return
        try:
            preset = presets_module.get_preset(name)
        except FileConverterError as exc:
            QMessageBox.warning(self, "Couldn't load preset", str(exc))
            return
        self.presetApplied.emit(preset.target_format, dict(preset.options))

    def _on_delete(self) -> None:
        name = self._selected_preset_name()
        if not name:
            QMessageBox.information(
                self, "No preset selected", "Select a preset first."
            )
            return
        try:
            presets_module.delete_preset(name)
        except FileConverterError as exc:
            QMessageBox.warning(self, "Couldn't delete preset", str(exc))
            return
        self._reload()


class PreferencesDialog(QDialog):
    """Exposes every persisted setting (not just theme/workers) — this is
    the first GUI surface for ``overwrite_policy``, ``preserve_metadata``,
    ``verify_output``, and ``default_output_dir``, which previously had no
    GUI control at all."""

    _THEME_LABELS = {"dark": "Dark", "light": "Light", "system": "Follow System"}
    _OVERWRITE_LABELS = {
        "ask": "Ask (prompt on conflict)",
        "overwrite": "Overwrite existing file",
        "skip": "Skip the file",
        "rename": "Rename (e.g. \u2018name (1).ext\u2019)",
    }

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(420)
        self._config = config

        form = QFormLayout()

        self.theme_combo = QComboBox()
        for value, label in self._THEME_LABELS.items():
            self.theme_combo.addItem(label, userData=value)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(config.theme))
        form.addRow("Theme:", self.theme_combo)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        self.workers_spin.setValue(config.max_workers)
        form.addRow("Parallel workers:", self.workers_spin)

        output_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit(config.default_output_dir or "")
        self.output_dir_edit.setPlaceholderText("(same as source file)")
        browse_btn = QPushButton("Browse\u2026")
        browse_btn.setObjectName("Secondary")
        browse_btn.clicked.connect(self._on_browse_output_dir)
        output_row.addWidget(self.output_dir_edit, stretch=1)
        output_row.addWidget(browse_btn)
        form.addRow("Default output directory:", output_row)

        self.overwrite_combo = QComboBox()
        for value, label in self._OVERWRITE_LABELS.items():
            self.overwrite_combo.addItem(label, userData=value)
        self.overwrite_combo.setCurrentIndex(
            self.overwrite_combo.findData(config.overwrite_policy)
        )
        form.addRow("If the output file already exists:", self.overwrite_combo)

        self.preserve_metadata_check = QCheckBox(
            "Preserve metadata (EXIF/ID3/document info) when possible"
        )
        self.preserve_metadata_check.setChecked(config.preserve_metadata)
        form.addRow("", self.preserve_metadata_check)

        self.verify_output_check = QCheckBox("Verify output files after conversion")
        self.verify_output_check.setChecked(config.verify_output)
        form.addRow("", self.verify_output_check)

        layout = QVBoxLayout(self)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_browse_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose default output directory"
        )
        if folder:
            self.output_dir_edit.setText(folder)

    def apply_to(self, config: AppConfig) -> AppConfig:
        """Write the dialog's current values back onto ``config`` and
        return it. Call after ``exec()`` returns ``Accepted``."""

        config.theme = self.theme_combo.currentData()
        config.max_workers = self.workers_spin.value()
        text = self.output_dir_edit.text().strip()
        config.default_output_dir = text or None
        config.overwrite_policy = self.overwrite_combo.currentData()
        config.preserve_metadata = self.preserve_metadata_check.isChecked()
        config.verify_output = self.verify_output_check.isChecked()
        return config
