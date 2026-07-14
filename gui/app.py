"""FileConverter desktop GUI — main window.

Built with PySide6. Run via ``python -m fileconverter`` or the packaged
executable produced by ``build_scripts/``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, cast

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import converters  # noqa: F401 — side effect: registers all converters
from ..core import config as config_module
from ..core import history as history_module
from ..core import presets as presets_module
from ..core.base import ConversionJob, ConversionOptions
from ..core.engine import ConversionEngine, build_output_path
from ..core.logging_setup import setup_logging
from .theme import stylesheet_for
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
        self.resize(980, 640)

        self.config = config_module.load_config()
        self.engine = ConversionEngine(
            max_workers=self.config.max_workers, verify_output=self.config.verify_output
        )
        self._job_row_map: dict[str, int] = {}
        self._thread: Optional[QThread] = None
        self._worker: Optional[EngineWorker] = None

        self._build_ui()
        self.apply_theme(self.config.theme)

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
        clear_btn = QPushButton("Clear Queue")
        clear_btn.setObjectName("Danger")
        clear_btn.clicked.connect(self._on_clear_queue)
        button_row.addWidget(add_files_btn)
        button_row.addWidget(add_folder_btn)
        button_row.addStretch()
        button_row.addWidget(clear_btn)
        root.addLayout(button_row)

        self.queue_table = QueueTable()
        root.addWidget(self.queue_table, stretch=1)

        controls_row = QHBoxLayout()
        controls_row.addWidget(QLabel("Output directory:"))
        self.output_dir_label = QLabel("(same as source file)")
        self.output_dir_label.setObjectName("SubHeader")
        controls_row.addWidget(self.output_dir_label, stretch=1)
        choose_output_btn = QPushButton("Choose\u2026")
        choose_output_btn.setObjectName("Secondary")
        choose_output_btn.clicked.connect(self._on_choose_output_dir)
        controls_row.addWidget(choose_output_btn)

        controls_row.addWidget(QLabel("Workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 32)
        self.workers_spin.setValue(self.config.max_workers)
        controls_row.addWidget(self.workers_spin)
        root.addLayout(controls_row)

        actions_row = QHBoxLayout()
        self.convert_btn = QPushButton("Convert All")
        self.convert_btn.clicked.connect(self._on_convert_all)
        actions_row.addWidget(self.convert_btn)
        actions_row.addStretch()
        actions_row.addWidget(QLabel("Advanced options (JSON, applied to every job):"))
        root.addLayout(actions_row)

        self.options_edit = QPlainTextEdit()
        self.options_edit.setPlaceholderText('{"quality": 85, "bitrate": "192k"}')
        self.options_edit.setFixedHeight(60)
        root.addWidget(self.options_edit)

        self._output_dir: Optional[Path] = None

        self._build_menu()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = QMenu("File", self)
        file_menu.addAction(self._make_action("Add Files\u2026", self._on_add_files))
        file_menu.addAction(self._make_action("Add Folder\u2026", self._on_add_folder))
        file_menu.addSeparator()
        file_menu.addAction(self._make_action("Exit", self.close))
        menu_bar.addMenu(file_menu)

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
        menu_bar.addMenu(tools_menu)

        view_menu = QMenu("View", self)
        view_menu.addAction(
            self._make_action("Toggle Dark / Light Theme", self._toggle_theme)
        )
        menu_bar.addMenu(view_menu)

        help_menu = QMenu("Help", self)
        help_menu.addAction(self._make_action("About FileConverter", self._show_about))
        menu_bar.addMenu(help_menu)

    def _make_action(self, text: str, slot) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        return action

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------
    def _on_files_dropped(self, paths: list[Path]) -> None:
        for path in paths:
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file():
                        self.queue_table.add_file(child, self.config.last_target_format)
            else:
                self.queue_table.add_file(path, self.config.last_target_format)

    def _on_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select files to convert")
        for f in files:
            self.queue_table.add_file(Path(f), self.config.last_target_format)

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select a folder")
        if folder:
            for child in sorted(Path(folder).rglob("*")):
                if child.is_file():
                    self.queue_table.add_file(child, self.config.last_target_format)

    def _on_clear_queue(self) -> None:
        self.queue_table.clear_all()

    def _on_choose_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output directory")
        if folder:
            self._output_dir = Path(folder)
            self.output_dir_label.setText(folder)

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
    def _on_convert_all(self) -> None:
        row_count = self.queue_table.rowCount()
        if row_count == 0:
            QMessageBox.information(self, "Nothing to convert", "Add some files first.")
            return

        options_dict = self._parse_options_json()
        if options_dict is None:
            return

        jobs: list[ConversionJob] = []
        self._job_row_map.clear()
        for row in range(row_count):
            source_path = self.queue_table.path_for_row(row)
            target_format = self.queue_table.target_format_for_row(row)
            if not target_format or target_format.startswith("("):
                self.queue_table.set_status(row, "No converter available")
                continue
            output_path = build_output_path(
                source_path, target_format, self._output_dir
            )
            job = ConversionJob(
                source_path=source_path,
                output_path=output_path,
                target_format=target_format,
                options=ConversionOptions.from_dict(options_dict),
            )
            self._job_row_map[job.job_id] = row
            jobs.append(job)
            self.queue_table.set_status(row, "Queued")

        if not jobs:
            return

        self.config.max_workers = self.workers_spin.value()
        self.config.last_target_format = jobs[0].target_format
        config_module.save_config(self.config)

        self.convert_btn.setEnabled(False)
        self.statusBar().showMessage(f"Converting {len(jobs)} file(s)\u2026")

        self.engine.max_workers = self.workers_spin.value()
        self._thread = QThread()
        self._worker = EngineWorker(self.engine, jobs)
        self._worker.moveToThread(self._thread)
        self._worker.progress.connect(self._on_job_progress)
        self._worker.job_done.connect(self._on_job_done)
        self._worker.batch_done.connect(self._on_batch_done)
        self._thread.started.connect(self._worker.run)
        self._thread.start()

    def _parse_options_json(self) -> Optional[dict]:
        import json

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
        row = self._job_row_map.get(job_id)
        if row is not None:
            self.queue_table.set_progress(row, fraction, message)

    def _on_job_done(self, result) -> None:
        row = self._job_row_map.get(result.job.job_id)
        if row is not None:
            self.queue_table.set_status(
                row, "Done" if result.success else f"Failed: {result.error}"
            )

    def _on_batch_done(self) -> None:
        self.convert_btn.setEnabled(True)
        self.statusBar().showMessage("Conversion batch finished")
        if self._thread:
            self._thread.quit()
            self._thread.wait()

    # ------------------------------------------------------------------
    # Tool dialogs
    # ------------------------------------------------------------------
    def _show_doctor(self) -> None:
        from ..core.registry import all_converters

        lines = []
        for conv in all_converters():
            available, reason = conv.check_available()
            lines.append(f"{'✓' if available else '✗'} {conv.name}: {reason}")
        QMessageBox.information(self, "Dependency Check", "\n".join(lines))

    def _show_history(self) -> None:
        entries = history_module.recent(limit=50)
        if not entries:
            QMessageBox.information(self, "History", "No conversions recorded yet.")
            return
        lines = [
            f"{'OK' if e.success else 'FAILED'} — {Path(e.source_path).name} -> {e.target_format}"
            for e in entries
        ]
        QMessageBox.information(self, "Recent Conversions", "\n".join(lines))

    def _show_presets(self) -> None:
        presets_list = presets_module.list_presets()
        lines = [f"{p.name}: -> {p.target_format} ({p.options})" for p in presets_list]
        QMessageBox.information(
            self, "Presets", "\n".join(lines) or "No presets available."
        )

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "About FileConverter",
            "FileConverter — a modular, professional-grade file conversion toolkit.\n\n"
            "Supports images, documents, spreadsheets, audio, video, and archives, "
            "with a plugin architecture, batch processing, presets, folder watching, "
            "and full conversion history.",
        )

    def _toggle_theme(self) -> None:
        self.config.theme = "light" if self.config.theme == "dark" else "dark"
        config_module.save_config(self.config)
        self.apply_theme(self.config.theme)

    def apply_theme(self, theme: str) -> None:
        app = cast(QApplication, QApplication.instance())
        if app:
            app.setStyleSheet(stylesheet_for(theme))

    def closeEvent(self, event) -> None:  # noqa: N802
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
