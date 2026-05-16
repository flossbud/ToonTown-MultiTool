"""Modal dialog with release notes + action buttons.

Emits one of three signals when the user picks an action:
- update_now   -> caller invokes UpdateRunner.run_update
- skip_version -> caller persists settings["update_skipped_version"]
- remind_later -> caller does nothing (dialog just closes)

view_notes opens the release URL in the browser; doesn't dismiss.
"""
from __future__ import annotations

import re
import webbrowser

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)


_BUILD_LINE_RE = re.compile(r"^Build:\s*\d+\s*$\n?", re.MULTILINE)


def _strip_build_line(body: str) -> str:
    return _BUILD_LINE_RE.sub("", body or "").strip()


class UpdateDialog(QDialog):
    update_now = Signal()
    remind_later = Signal()
    skip_version = Signal()

    def __init__(self, release_info: dict, *, local_version_string: str, parent=None):
        super().__init__(parent)
        self._release = release_info
        self.setWindowTitle("Update available")
        self.setModal(True)
        self.setMinimumSize(480, 360)
        self.setMaximumSize(720, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        tag = release_info.get("tag_name", "")
        heading = QLabel(f"<b>ToonTown MultiTool {tag} is available</b>")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        sub = QLabel(f"You're on v{local_version_string}")
        sub.setObjectName("update_dialog_sub")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        notes_label = QLabel("Release notes:")
        layout.addWidget(notes_label)

        self._body = QTextBrowser()
        self._body.setOpenExternalLinks(True)
        self._body.setPlainText(_strip_build_line(release_info.get("body", "")))
        layout.addWidget(self._body, 1)

        self._view_notes_btn = QPushButton("View release notes")
        self._view_notes_btn.clicked.connect(self._open_release_url)
        layout.addWidget(self._view_notes_btn)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._skip_btn = QPushButton("Skip this version")
        self._later_btn = QPushButton("Remind me later")
        self._update_btn = QPushButton("Update now")
        self._update_btn.setDefault(True)
        self._skip_btn.clicked.connect(self._on_skip)
        self._later_btn.clicked.connect(self._on_later)
        self._update_btn.clicked.connect(self._on_update)
        btn_row.addWidget(self._skip_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._later_btn)
        btn_row.addWidget(self._update_btn)
        layout.addLayout(btn_row)

    def _open_release_url(self) -> None:
        url = self._release.get("html_url")
        if url:
            webbrowser.open(url)

    def _on_update(self) -> None:
        self.update_now.emit()
        self.accept()

    def _on_skip(self) -> None:
        self.skip_version.emit()
        self.reject()

    def _on_later(self) -> None:
        self.remind_later.emit()
        self.reject()
