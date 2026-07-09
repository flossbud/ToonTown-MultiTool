"""List model over LogLine records. Ring-capped at BUFFER_CAP (bundle: 500)."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from utils.widgets.logs_console.records import LogLine, format_line

BUFFER_CAP = 500
LINE_ROLE = Qt.UserRole + 1


class LogLineModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines: list[LogLine] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._lines)

    def data(self, index: QModelIndex,
             role: int = Qt.DisplayRole) -> LogLine | str | None:
        if not index.isValid() or not (0 <= index.row() < len(self._lines)):
            return None
        line = self._lines[index.row()]
        if role == LINE_ROLE:
            return line
        if role == Qt.DisplayRole:
            return format_line(line)
        return None

    def append(self, line: LogLine) -> None:
        # Remove-then-insert: the insert is always the terminal signal, so a
        # follow-mode scroll-to-bottom on rowsInserted lands on the new last
        # row by construction (no reliance on the view clamping a stale row).
        overflow = len(self._lines) + 1 - BUFFER_CAP
        if overflow > 0:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            del self._lines[:overflow]
            self.endRemoveRows()
        n = len(self._lines)
        self.beginInsertRows(QModelIndex(), n, n)
        self._lines.append(line)
        self.endInsertRows()

    def clear_scope(self, source: str | None) -> None:
        """None clears everything; a source ('raw'|'input'|'api') clears only
        that source's rows (spec Clear semantics)."""
        self.beginResetModel()
        if source is None:
            self._lines.clear()
        else:
            self._lines = [ln for ln in self._lines if ln.source != source]
        self.endResetModel()

    def lines(self) -> tuple[LogLine, ...]:
        return tuple(self._lines)
