"""The conversion queue table: one row per file, with per-row target
format, progress bar, status, and row actions (remove/cancel).

Rows are identified by a stable ``row_id`` (not the table index, which
shifts whenever a row above is removed) so callers — and the engine's
async progress/done callbacks, which arrive keyed by job_id — can always
find "the right row" regardless of what's happened to the table in the
meantime, including the row having been removed entirely (in which case
lookups just return ``None`` and callers no-op)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)
from PySide6.QtCore import QUrl

from ...core.formats import detect_format
from ...core.registry import supported_targets

COLUMNS = ["File", "Source Format", "Target Format", "Progress", "Status", ""]
_ROW_ID_ROLE = Qt.ItemDataRole.UserRole

STATUS_READY = "Ready"
STATUS_DONE = "Done"


class QueueTable(QTableWidget):
    filesDropped = Signal(list)  # list[Path]

    cancelRequested = Signal(int)  # row_id

    removeRequested = Signal(int)  # row_id

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(COLUMNS)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setMinimumSectionSize(90)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu_requested)

        self._next_row_id = 0
        # All keyed by row_id, never by table index (indices shift on
        # removal; row_ids never do).
        self._paths: dict[int, Path] = {}
        self._output_paths: dict[int, Path] = {}
        self._statuses: dict[int, str] = {}
        self._job_id_by_row: dict[int, str] = {}
        self._row_by_job_id: dict[str, int] = {}
        # Rows with a job queued or running in the current batch. Tracked
        # explicitly: inferring it from the status text never worked, since
        # converters report free-form messages ("Encoding", "Rendered page
        # 2/5", ...), so right-click -> Cancel never appeared mid-conversion.
        self._active_rows: set[int] = set()

    # ------------------------------------------------------------------
    # Adding / removing rows
    # ------------------------------------------------------------------
    def has_path(self, path: Path) -> bool:
        """True if ``path`` (resolved) is already queued — used to skip
        duplicate drops/adds instead of silently queuing the same file
        twice."""

        path = Path(path)
        try:
            target = path.resolve()
        except OSError:
            target = path
        for existing in self._paths.values():
            try:
                if existing.resolve() == target:
                    return True
            except OSError:
                if existing == path:
                    return True
        return False

    def add_file(
        self, path: Path, default_target: Optional[str] = None
    ) -> Optional[int]:
        """Add a row for ``path``. Returns the new row's ``row_id``, or
        ``None`` if ``path`` is already queued (duplicate)."""

        if self.has_path(path):
            return None

        row_id = self._next_row_id
        self._next_row_id += 1
        row = self.rowCount()
        self.insertRow(row)
        self._paths[row_id] = path
        self._statuses[row_id] = STATUS_READY

        file_item = QTableWidgetItem(str(path))
        file_item.setData(_ROW_ID_ROLE, row_id)
        file_item.setToolTip(str(path))
        self.setItem(row, 0, file_item)

        src_format = detect_format(path) or "?"
        self.setItem(row, 1, QTableWidgetItem(src_format))

        target_combo = QComboBox()
        targets = supported_targets(src_format) or ["(no converter available)"]
        target_combo.addItems(targets)
        if default_target and default_target in targets:
            target_combo.setCurrentText(default_target)
        target_combo.currentTextChanged.connect(
            lambda _text, rid=row_id: self._on_target_changed(rid)
        )
        self.setCellWidget(row, 2, target_combo)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        self.setCellWidget(row, 3, progress)

        status_item = QTableWidgetItem(STATUS_READY)
        self.setItem(row, 4, status_item)

        remove_btn = QPushButton("\u2715")
        remove_btn.setObjectName("Secondary")
        remove_btn.setFixedWidth(28)
        remove_btn.setToolTip("Remove (cancels first if still running)")
        remove_btn.clicked.connect(
            lambda _checked=False, rid=row_id: self.removeRequested.emit(rid)
        )
        self.setCellWidget(row, 5, remove_btn)

        return row_id

    def remove_row(self, row_id: int) -> None:
        row = self._index_for_row_id(row_id)
        if row is not None:
            self.removeRow(row)
        self._paths.pop(row_id, None)
        self._output_paths.pop(row_id, None)
        self._statuses.pop(row_id, None)
        self._active_rows.discard(row_id)
        job_id = self._job_id_by_row.pop(row_id, None)
        if job_id is not None:
            self._row_by_job_id.pop(job_id, None)

    def remove_selected_rows(self) -> None:
        for row_id in self.selected_row_ids():
            self.removeRequested.emit(row_id)

    def clear_all(self) -> None:
        self.setRowCount(0)
        self._paths.clear()
        self._output_paths.clear()
        self._statuses.clear()
        self._job_id_by_row.clear()
        self._row_by_job_id.clear()
        self._active_rows.clear()

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def _index_for_row_id(self, row_id: int) -> Optional[int]:
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is not None and item.data(_ROW_ID_ROLE) == row_id:
                return row
        return None

    def row_id_for_job_id(self, job_id: str) -> Optional[int]:
        return self._row_by_job_id.get(job_id)

    def job_id_for_row(self, row_id: int) -> Optional[str]:
        return self._job_id_by_row.get(row_id)

    def path_for_row(self, row_id: int) -> Optional[Path]:
        return self._paths.get(row_id)

    def target_format_for_row(self, row_id: int) -> Optional[str]:
        row = self._index_for_row_id(row_id)
        if row is None:
            return None
        widget: Optional[QComboBox] = self.cellWidget(row, 2)  # type: ignore[assignment]
        return widget.currentText() if widget else None

    def all_row_ids(self) -> list[int]:
        row_ids = []
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is not None:
                row_ids.append(item.data(_ROW_ID_ROLE))
        return row_ids

    def selected_row_ids(self) -> list[int]:
        rows = {index.row() for index in self.selectedIndexes()}
        row_ids = []
        for row in rows:
            item = self.item(row, 0)
            if item is not None:
                row_ids.append(item.data(_ROW_ID_ROLE))
        return row_ids

    # ------------------------------------------------------------------
    # Job wiring (called by app.py when a batch is submitted/progresses)
    # ------------------------------------------------------------------
    def set_job_id(self, row_id: int, job_id: str) -> None:
        self._job_id_by_row[row_id] = job_id
        self._row_by_job_id[job_id] = row_id

    def set_output_path(self, row_id: int, path: Optional[Path]) -> None:
        if path is not None:
            self._output_paths[row_id] = path

    def output_path_for_row(self, row_id: int) -> Optional[Path]:
        return self._output_paths.get(row_id)

    def is_active(self, row_id: int) -> bool:
        return row_id in self._active_rows

    def set_active(self, row_id: int, active: bool) -> None:
        if active:
            self._active_rows.add(row_id)
        else:
            self._active_rows.discard(row_id)
        row = self._index_for_row_id(row_id)
        if row is not None:
            combo = self.cellWidget(row, 2)
            if combo is not None:
                # Changing the target mid-conversion would be misleading.
                combo.setEnabled(not active)

    def clear_active(self) -> None:
        for row_id in list(self._active_rows):
            self.set_active(row_id, False)

    def status_for_row(self, row_id: int) -> str:
        return self._statuses.get(row_id, "")

    def _on_target_changed(self, row_id: int) -> None:
        """A finished/failed row whose target format changes is ready to be
        converted again."""

        if row_id in self._active_rows:
            return
        if self._statuses.get(row_id) != STATUS_READY:
            self._output_paths.pop(row_id, None)
            self.set_progress(row_id, 0.0)
            self.set_status(row_id, STATUS_READY)

    def set_progress(self, row_id: int, fraction: float, message: str = "") -> None:
        row = self._index_for_row_id(row_id)
        if row is None:
            return
        progress: Optional[QProgressBar] = self.cellWidget(row, 3)  # type: ignore[assignment]
        if progress is not None:
            progress.setValue(int(fraction * 100))
        if message:
            self.set_status(row_id, message)

    def set_status(self, row_id: int, status: str) -> None:
        self._statuses[row_id] = status
        row = self._index_for_row_id(row_id)
        if row is None:
            return
        status_item = self.item(row, 4)
        if status_item is not None:
            status_item.setText(status)
            # Long converter error messages get cut off by the column
            # width; a tooltip lets you actually read the whole thing.
            status_item.setToolTip(status)

    # ------------------------------------------------------------------
    # Bulk actions
    # ------------------------------------------------------------------
    def set_target_format_for_selected(self, target_format: str) -> tuple[int, int]:
        """Apply ``target_format`` to every selected row whose source
        format can actually convert to it. Returns ``(applied, skipped)``
        counts so the caller can report what happened."""

        applied = 0
        skipped = 0
        for row_id in self.selected_row_ids():
            row = self._index_for_row_id(row_id)
            if row is None:
                continue
            combo: Optional[QComboBox] = self.cellWidget(row, 2)  # type: ignore[assignment]
            if combo is None:
                continue
            available = [combo.itemText(i) for i in range(combo.count())]
            if target_format in available:
                combo.setCurrentText(target_format)
                applied += 1
            else:
                skipped += 1
        return applied, skipped

    def filter_text(self, text: str) -> None:
        """Hide rows whose filename doesn't contain ``text`` (case
        insensitive). Empty text shows everything."""

        needle = text.strip().lower()
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            visible = not needle or (item is not None and needle in item.text().lower())
            self.setRowHidden(row, not visible)

    # ------------------------------------------------------------------
    # Context menu / keyboard / drag-drop
    # ------------------------------------------------------------------
    def _on_context_menu_requested(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        item = self.item(index.row(), 0)
        if item is None:
            return
        row_id = item.data(_ROW_ID_ROLE)
        # Right-clicking a row that isn't part of the current selection
        # replaces the selection with just that row, matching most apps.
        if row_id not in self.selected_row_ids():
            self.selectRow(index.row())

        selected = self.selected_row_ids()
        menu = QMenu(self)

        if any(self.is_active(rid) for rid in selected):
            cancel_action = menu.addAction("Cancel")
            cancel_action.triggered.connect(
                lambda: [
                    self.cancelRequested.emit(rid)
                    for rid in selected
                    if self.is_active(rid)
                ]
            )

        remove_action = menu.addAction(
            "Remove" if len(selected) == 1 else f"Remove {len(selected)} rows"
        )
        remove_action.triggered.connect(
            lambda: [self.removeRequested.emit(rid) for rid in selected]
        )

        if len(selected) == 1:
            rid = selected[0]
            output_path = self._output_paths.get(rid)
            if output_path is not None and output_path.exists():
                menu.addSeparator()
                open_action = menu.addAction("Open Output File")
                open_action.triggered.connect(lambda: self._open_path(output_path))
                folder_action = menu.addAction("Show in Folder")
                folder_action.triggered.connect(
                    lambda: self._open_path(output_path.parent)
                )

        menu.exec(self.viewport().mapToGlobal(pos))

    @staticmethod
    def _open_path(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def keyPressEvent(self, event) -> None:  # noqa: N802 — Qt naming convention
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_selected_rows()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            paths = [
                Path(url.toLocalFile())
                for url in event.mimeData().urls()
                if url.toLocalFile()
            ]
            if paths:
                self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
