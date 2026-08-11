"""FileConverter desktop GUI — main window.

Built with PySide6. Run via ``python -m fileconverter`` or the packaged
executable produced by ``build_scripts/``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional, cast

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import converters  # noqa: F401 — side effect: registers all converters
from ..core import config as config_module
from ..core.base import ConversionJob, ConversionOptions
from ..core.engine import ConversionEngine, build_output_path, output_conflict
from ..core.logging_setup import setup_logging
from ..core.registry import all_converters
from .theme import resolve_theme, stylesheet_for
from .widgets.dialogs import (
    DoctorDialog,
    HistoryDialog,
    PreferencesDialog,
    PresetsDialog,
)
from .widgets.drop_area import DropArea
from .widgets.queue_table import QueueTable


class EngineWorker(QObject):
    """Runs the ConversionEngine's batch on a background thread and relays
    progress/results back to the GUI thread via Qt signals (thread-safe)."""

    progress = Signal(str, float, str)  # job_id, fraction, message
    job_done = Signal(object)  # ConversionResult
    batch_done = Signal()

    def __init__(self, engine: ConversionEngine, jobs: list[ConversionJob]):
        super().__init__()
        self.engine = engine
        self.jobs = jobs

    def run(self) -> None:
        self.engine.run_batch(
            self.jobs,
            on_progress=lambda job_id, frac, msg: self.progress.emit(job_id, frac, msg),
            on_done=lambda result: self.job_done.emit(result),
        )
        self.batch_done.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileConverter")
        self.resize(1040, 680)

        self.config = config_module.load_config()
        self.engine = ConversionEngine(
            max_workers=self.config.max_workers, verify_output=self.config.verify_output
        )
        self._thread: Optional[QThread] = None
        self._worker: Optional[EngineWorker] = None
        # Job ids belonging to the batch currently running — used both by
        # the global Cancel button and by per-row cancel/remove so we know
        # whether a row still has something in flight worth cancelling.
        self._active_job_ids: set[str] = set()
        self._batch_total = 0
        self._batch_completed = 0
        self._output_dir: Optional[Path] = (
            Path(self.config.default_output_dir)
            if self.config.default_output_dir
            else None
        )

        self._build_ui()
        self.apply_theme(self.config.theme)
        self._restore_queue()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        header = QLabel("FileConverter")
        header.setObjectName("Header")
        subheader = QLabel(
            "Convert images, documents, spreadsheets, audio, video, and archives \u2014 all in one place."
        )
        subheader.setObjectName("SubHeader")
        root.addWidget(header)
        root.addWidget(subheader)

        self.drop_area = DropArea()
        self.drop_area.filesDropped.connect(self._on_files_dropped)
        root.addWidget(self.drop_area)

        button_row = QHBoxLayout()
        add_files_btn = QPushButton("Add Files")
        add_files_btn.clicked.connect(self._on_add_files)
        add_folder_btn = QPushButton("Add Folder")
        add_folder_btn.setObjectName("Secondary")
        add_folder_btn.clicked.connect(self._on_add_folder)
        button_row.addWidget(add_files_btn)
        button_row.addWidget(add_folder_btn)
        button_row.addStretch()
        button_row.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter queue by filename\u2026")
        self.filter_edit.setFixedWidth(220)
        self.filter_edit.textChanged.connect(
            lambda text: self.queue_table.filter_text(text)
        )
        button_row.addWidget(self.filter_edit)
        clear_btn = QPushButton("Clear Queue")
        clear_btn.setObjectName("Danger")
        clear_btn.clicked.connect(self._on_clear_queue)
        button_row.addWidget(clear_btn)
        root.addLayout(button_row)

        self.queue_table = QueueTable()
        self.queue_table.filesDropped.connect(self._on_files_dropped)
        self.queue_table.cancelRequested.connect(self._on_row_cancel_requested)
        self.queue_table.removeRequested.connect(self._on_row_remove_requested)
        root.addWidget(self.queue_table, stretch=1)

        bulk_row = QHBoxLayout()
        bulk_row.addWidget(QLabel("Set target format for selected rows:"))
        self.bulk_format_combo = QComboBox()
        self.bulk_format_combo.setEditable(True)
        self.bulk_format_combo.addItems(
            sorted({fmt for conv in all_converters() for fmt in conv.output_formats})
        )
        bulk_row.addWidget(self.bulk_format_combo)
        bulk_apply_btn = QPushButton("Apply")
        bulk_apply_btn.setObjectName("Secondary")
        bulk_apply_btn.clicked.connect(self._on_apply_bulk_format)
        bulk_row.addWidget(bulk_apply_btn)
        bulk_row.addStretch()
        root.addLayout(bulk_row)

        controls_row = QHBoxLayout()
        controls_row.addWidget(QLabel("Output directory:"))
        self.output_dir_label = QLabel(
            self.config.default_output_dir or "(same as source file)"
        )
        self.output_dir_label.setObjectName("SubHeader")
        controls_row.addWidget(self.output_dir_label, stretch=1)
        choose_output_btn = QPushButton("Choose\u2026")
        choose_output_btn.setObjectName("Secondary")
        choose_output_btn.clicked.connect(self._on_choose_output_dir)
        controls_row.addWidget(choose_output_btn)

        controls_row.addWidget(QLabel("Workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        self.workers_spin.setValue(self.config.max_workers)
        controls_row.addWidget(self.workers_spin)
        root.addLayout(controls_row)

        actions_row = QHBoxLayout()
        self.convert_btn = QPushButton("Convert All")
        self.convert_btn.setShortcut(QKeySequence("Ctrl+Return"))
        self.convert_btn.setToolTip("Convert All (Ctrl+Return)")
        self.convert_btn.clicked.connect(self._on_convert_all)
        actions_row.addWidget(self.convert_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.clicked.connect(self._on_cancel_all)
        self.cancel_btn.hide()
        actions_row.addWidget(self.cancel_btn)

        self.batch_progress = QProgressBar()
        self.batch_progress.setRange(0, 100)
        self.batch_progress.setFixedWidth(220)
        self.batch_progress.hide()
        actions_row.addWidget(self.batch_progress)

        actions_row.addStretch()
        actions_row.addWidget(QLabel("Advanced options (JSON, applied to every job):"))
        root.addLayout(actions_row)

        self.options_edit = QPlainTextEdit()
        self.options_edit.setPlaceholderText('{"quality": 85, "bitrate": "192k"}')
        self.options_edit.setFixedHeight(60)
        root.addWidget(self.options_edit)

        self._build_menu()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = QMenu("File", self)
        file_menu.addAction(
            self._make_action("Add Files\u2026", self._on_add_files, "Ctrl+O")
        )
        file_menu.addAction(
            self._make_action("Add Folder\u2026", self._on_add_folder, "Ctrl+Shift+O")
        )
        file_menu.addSeparator()
        file_menu.addAction(self._make_action("Exit", self.close, "Ctrl+Q"))
        menu_bar.addMenu(file_menu)

        edit_menu = QMenu("Edit", self)
        edit_menu.addAction(
            self._make_action(
                "Remove Selected", self.queue_table.remove_selected_rows, "Delete"
            )
        )
        edit_menu.addAction(self._make_action("Clear Queue", self._on_clear_queue))
        menu_bar.addMenu(edit_menu)

        tools_menu = QMenu("Tools", self)
        tools_menu.addAction(
            self._make_action("Check Dependencies (Doctor)", self._show_doctor)
        )
        tools_menu.addAction(
            self._make_action("Conversion History\u2026", self._show_history)
        )
        tools_menu.addAction(
            self._make_action("Manage Presets\u2026", self._show_presets)
        )
        tools_menu.addSeparator()
        tools_menu.addAction(
            self._make_action("Preferences\u2026", self._show_preferences, "Ctrl+,")
        )
        menu_bar.addMenu(tools_menu)

        view_menu = QMenu("View", self)
        theme_menu = QMenu("Theme", self)
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        for value, label in (
            ("dark", "Dark"),
            ("light", "Light"),
            ("system", "Follow System"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self.config.theme == value)
            action.triggered.connect(lambda _checked=False, v=value: self._set_theme(v))
            self._theme_group.addAction(action)
            theme_menu.addAction(action)
            self._theme_actions[value] = action
        view_menu.addMenu(theme_menu)
        menu_bar.addMenu(view_menu)

        help_menu = QMenu("Help", self)
        help_menu.addAction(self._make_action("About FileConverter", self._show_about))
        menu_bar.addMenu(help_menu)

    def _make_action(self, text: str, slot, shortcut: Optional[str] = None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        return action

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------
    def _add_path(self, path: Path) -> bool:
        """Returns True if a new row was actually added (False = duplicate)."""

        return (
            self.queue_table.add_file(path, self.config.last_target_format) is not None
        )

    def _report_added(self, added: int, skipped: int) -> None:
        if skipped and added:
            self.statusBar().showMessage(
                f"Added {added} file(s); skipped {skipped} already-queued duplicate(s)."
            )
        elif skipped:
            self.statusBar().showMessage(
                f"Skipped {skipped} file(s) \u2014 already in the queue."
            )
        elif added:
            self.statusBar().showMessage(f"Added {added} file(s).")

    def _on_files_dropped(self, paths: list[Path]) -> None:
        added = skipped = 0
        for path in paths:
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file():
                        if self._add_path(child):
                            added += 1
                        else:
                            skipped += 1
            else:
                if self._add_path(path):
                    added += 1
                else:
                    skipped += 1
        self._report_added(added, skipped)

    def _on_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select files to convert")
        added = skipped = 0
        for f in files:
            if self._add_path(Path(f)):
                added += 1
            else:
                skipped += 1
        self._report_added(added, skipped)

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select a folder")
        if not folder:
            return
        added = skipped = 0
        for child in sorted(Path(folder).rglob("*")):
            if child.is_file():
                if self._add_path(child):
                    added += 1
                else:
                    skipped += 1
        self._report_added(added, skipped)

    def _on_clear_queue(self) -> None:
        self.queue_table.clear_all()

    def _on_choose_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output directory")
        if folder:
            self._output_dir = Path(folder)
            self.output_dir_label.setText(folder)

    def _on_apply_bulk_format(self) -> None:
        fmt = self.bulk_format_combo.currentText().strip()
        if not fmt:
            return
        applied, skipped = self.queue_table.set_target_format_for_selected(fmt)
        if applied == 0 and skipped == 0:
            self.statusBar().showMessage("Select one or more queue rows first.")
            return
        message = f"Set target format to '{fmt}' for {applied} row(s)."
        if skipped:
            message += f" Skipped {skipped} row(s) that can't convert to '{fmt}'."
        self.statusBar().showMessage(message)

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
    def _on_convert_all(self) -> None:
        if self._thread is not None:
            QMessageBox.information(
                self,
                "Conversion in progress",
                "A batch is already converting \u2014 use Cancel first if you want to stop it.",
            )
            return

        row_ids = self.queue_table.all_row_ids()
        if not row_ids:
            QMessageBox.information(self, "Nothing to convert", "Add some files first.")
            return

        options_dict = self._parse_options_json()
        if options_dict is None:
            return

        effective_policy = self._resolve_overwrite_policy(row_ids)
        if effective_policy is None:
            return  # user cancelled at the conflict-resolution prompt

        jobs: list[ConversionJob] = []
        skipped_rows = 0
        for row_id in row_ids:
            source_path = self.queue_table.path_for_row(row_id)
            target_format = self.queue_table.target_format_for_row(row_id)
            if source_path is None:
                continue
            if not target_format or target_format.startswith("("):
                self.queue_table.set_status(row_id, "No converter available")
                continue
            output_path = build_output_path(
                source_path,
                target_format,
                self._output_dir,
                overwrite_policy=effective_policy,
            )
            if output_path is None:
                self.queue_table.set_status(row_id, "Skipped (output already exists)")
                skipped_rows += 1
                continue
            job = ConversionJob(
                source_path=source_path,
                output_path=output_path,
                target_format=target_format,
                options=ConversionOptions.from_dict(options_dict),
            )
            self.queue_table.set_job_id(row_id, job.job_id)
            jobs.append(job)
            self.queue_table.set_status(row_id, "Queued")

        if not jobs:
            if skipped_rows:
                self.statusBar().showMessage(
                    f"Nothing to convert \u2014 all {skipped_rows} file(s) were skipped "
                    "(output already exists)."
                )
            return

        self.config.max_workers = self.workers_spin.value()
        self.config.last_target_format = jobs[0].target_format
        config_module.save_config(self.config)

        self._active_job_ids = {job.job_id for job in jobs}
        self._batch_total = len(jobs)
        self._batch_completed = 0

        self.convert_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.show()
        self.batch_progress.setValue(0)
        self.batch_progress.setFormat(f"0/{self._batch_total}")
        self.batch_progress.show()
        self.statusBar().showMessage(f"Converting {len(jobs)} file(s)\u2026")

        self.engine.set_max_workers(self.workers_spin.value())
        self._thread = QThread()
        self._worker = EngineWorker(self.engine, jobs)
        self._worker.moveToThread(self._thread)
        self._worker.progress.connect(self._on_job_progress)
        self._worker.job_done.connect(self._on_job_done)
        self._worker.batch_done.connect(self._on_batch_done)
        self._thread.started.connect(self._worker.run)
        self._thread.start()

    def _resolve_overwrite_policy(self, row_ids: list[int]) -> Optional[str]:
        """Turn ``self.config.overwrite_policy`` into a concrete policy
        ``build_output_path`` can act on. For ``"ask"``, this shows one
        dialog covering every conflicting file in the batch — not a
        separate prompt per file, to keep a big batch from turning into a
        wall of pop-ups. Returns ``None`` if the user cancels the prompt,
        which should abort the whole conversion."""

        if self.config.overwrite_policy != "ask":
            return self.config.overwrite_policy

        conflicts = []
        for row_id in row_ids:
            source_path = self.queue_table.path_for_row(row_id)
            target_format = self.queue_table.target_format_for_row(row_id)
            if not source_path or not target_format or target_format.startswith("("):
                continue
            if (
                output_conflict(source_path, target_format, self._output_dir)
                is not None
            ):
                conflicts.append(row_id)

        if not conflicts:
            return "rename"  # no conflicts either way, so this choice doesn't matter

        box = QMessageBox(self)
        box.setWindowTitle("Output file(s) already exist")
        box.setText(
            f"{len(conflicts)} of {len(row_ids)} output file(s) already exist.\n"
            "What should happen to them?"
        )
        overwrite_btn = box.addButton("Overwrite", QMessageBox.ButtonRole.AcceptRole)
        rename_btn = box.addButton("Rename", QMessageBox.ButtonRole.AcceptRole)
        skip_btn = box.addButton("Skip", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(rename_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is overwrite_btn:
            return "overwrite"
        if clicked is rename_btn:
            return "rename"
        if clicked is skip_btn:
            return "skip"
        return None

    def _parse_options_json(self) -> Optional[dict]:
        text = self.options_edit.toPlainText().strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(
                self,
                "Invalid options",
                f"Advanced options must be valid JSON.\n\n{exc}",
            )
            return None

    def _on_job_progress(self, job_id: str, fraction: float, message: str) -> None:
        row_id = self.queue_table.row_id_for_job_id(job_id)
        if row_id is not None:
            self.queue_table.set_progress(row_id, fraction, message)

    def _on_job_done(self, result) -> None:
        self._active_job_ids.discard(result.job.job_id)
        self._batch_completed += 1
        if self._batch_total:
            self.batch_progress.setValue(
                int(100 * self._batch_completed / self._batch_total)
            )
        self.batch_progress.setFormat(f"{self._batch_completed}/{self._batch_total}")

        row_id = self.queue_table.row_id_for_job_id(result.job.job_id)
        if row_id is not None:
            self.queue_table.set_output_path(row_id, result.output_path)
            if result.success:
                status = "Done"
            elif result.message == "Cancelled":
                status = "Cancelled"
            else:
                status = f"Failed: {result.error}"
            self.queue_table.set_status(row_id, status)

    def _on_batch_done(self) -> None:
        self.convert_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.hide()
        self.batch_progress.hide()
        self.statusBar().showMessage("Conversion batch finished")
        self._active_job_ids.clear()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def _on_cancel_all(self) -> None:
        for job_id in list(self._active_job_ids):
            self.engine.cancel(job_id)
            row_id = self.queue_table.row_id_for_job_id(job_id)
            if row_id is not None:
                self.queue_table.set_status(row_id, "Cancelling\u2026")
        self.cancel_btn.setEnabled(False)
        self.statusBar().showMessage("Cancelling\u2026")

    def _on_row_cancel_requested(self, row_id: int) -> None:
        job_id = self.queue_table.job_id_for_row(row_id)
        if job_id and job_id in self._active_job_ids:
            self.engine.cancel(job_id)
            self.queue_table.set_status(row_id, "Cancelling\u2026")

    def _on_row_remove_requested(self, row_id: int) -> None:
        job_id = self.queue_table.job_id_for_row(row_id)
        if job_id and job_id in self._active_job_ids:
            self.engine.cancel(job_id)
            self._active_job_ids.discard(job_id)
        self.queue_table.remove_row(row_id)

    # ------------------------------------------------------------------
    # Tool dialogs
    # ------------------------------------------------------------------
    def _show_doctor(self) -> None:
        DoctorDialog(self).exec()

    def _show_history(self) -> None:
        HistoryDialog(self).exec()

    def _show_presets(self) -> None:
        dialog = PresetsDialog(self)
        dialog.presetApplied.connect(self._on_preset_applied)
        dialog.exec()

    def _on_preset_applied(self, target_format: str, options: dict) -> None:
        applied, skipped = self.queue_table.set_target_format_for_selected(
            target_format
        )
        self.options_edit.setPlainText(json.dumps(options, indent=2) if options else "")
        if applied or skipped:
            message = f"Applied preset (target='{target_format}') to {applied} selected row(s)."
            if skipped:
                message += f" Skipped {skipped} row(s) that can't convert to '{target_format}'."
        else:
            message = (
                f"Preset options loaded (target='{target_format}'). "
                "Select queue rows to also set their target format."
            )
        self.statusBar().showMessage(message)

    def _show_preferences(self) -> None:
        dialog = PreferencesDialog(self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.apply_to(self.config)
        config_module.save_config(self.config)

        self.workers_spin.setValue(self.config.max_workers)
        self.engine.set_max_workers(self.config.max_workers)
        self._output_dir = (
            Path(self.config.default_output_dir)
            if self.config.default_output_dir
            else None
        )
        self.output_dir_label.setText(
            self.config.default_output_dir or "(same as source file)"
        )
        self.apply_theme(self.config.theme)
        for value, action in self._theme_actions.items():
            action.setChecked(self.config.theme == value)

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "About FileConverter",
            "FileConverter — a modular, professional-grade file conversion toolkit.\n\n"
            "Supports images, documents, spreadsheets, audio, video, and archives, "
            "with a plugin architecture, batch processing (with retry and "
            "cancellation), presets, folder watching, and full conversion history.",
        )

    def _set_theme(self, theme: str) -> None:
        self.config.theme = theme
        config_module.save_config(self.config)
        self.apply_theme(theme)

    def apply_theme(self, theme: str) -> None:
        app = cast(QApplication, QApplication.instance())
        if app:
            app.setStyleSheet(stylesheet_for(resolve_theme(theme)))

    # ------------------------------------------------------------------
    # Queue persistence across restarts
    # ------------------------------------------------------------------
    def _queue_state_path(self) -> Path:
        return config_module.CONFIG_DIR / "queue_state.json"

    def _persist_queue(self) -> None:
        rows = []
        for row_id in self.queue_table.all_row_ids():
            path = self.queue_table.path_for_row(row_id)
            target = self.queue_table.target_format_for_row(row_id)
            if path is not None:
                rows.append({"path": str(path), "target_format": target})
        try:
            config_module.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self._queue_state_path().write_text(json.dumps(rows), encoding="utf-8")
        except OSError:
            pass  # best-effort only — losing the saved queue isn't fatal

    def _restore_queue(self) -> None:
        path = self._queue_state_path()
        if not path.exists():
            return
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(rows, list):
            return

        restored = 0
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            raw_path = entry.get("path")
            target = entry.get("target_format")
            if not raw_path:
                continue
            file_path = Path(raw_path)
            if not file_path.exists():
                continue  # moved/deleted since last session — silently drop it
            if self.queue_table.add_file(file_path, target) is not None:
                restored += 1
        if restored:
            self.statusBar().showMessage(
                f"Restored {restored} file(s) from your last session."
            )

    def closeEvent(self, event) -> None:  # noqa: N802
        self._persist_queue()
        self.engine.shutdown(wait=False)
        super().closeEvent(event)


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("FileConverter")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
