"""Visible-set filter: scope ∩ active tag chips ∩ case-insensitive query
over `tag + " " + message` (spec §6)."""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QSortFilterProxyModel

from utils.widgets.logs_console.model import LINE_ROLE


class LogFilterProxy(QSortFilterProxyModel):
    VALID_SCOPES = frozenset({"all", "raw", "input", "api"})

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scope = "all"          # all | raw | input | api
        self._tags: set[str] = set()
        self._query = ""

    def set_scope(self, scope: str) -> None:
        assert scope in self.VALID_SCOPES, f"unknown scope {scope!r}"
        self._scope = scope
        self.invalidateFilter()

    def set_active_tags(self, tags: Iterable[str]) -> None:
        tags = set(tags)
        if tags == self._tags:
            return
        self._tags = tags
        self.invalidateFilter()

    def set_query(self, query: str) -> None:
        self._query = query.strip().lower()
        self.invalidateFilter()

    def scope(self) -> str:
        return self._scope

    def filterAcceptsRow(self, row, parent) -> bool:
        line = self.sourceModel().index(row, 0, parent).data(LINE_ROLE)
        if line is None:
            return False
        if self._scope != "all" and line.source != self._scope:
            return False
        if self._tags and line.tag not in self._tags:
            return False
        if self._query:
            hay = f"{line.tag} {line.message}".lower()
            if self._query not in hay:
                return False
        return True
