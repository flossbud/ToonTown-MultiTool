"""Themed picker dialog for choosing among multiple Corporate Clash installs."""

from __future__ import annotations

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QWidget,
)

from services.wine_runtimes import WineInstall, install_signature
from utils.launcher_chip import LAUNCHER_CHIP_LABEL


_CONFIRM_KEEP = "Keep this install"
_CONFIRM_USE = "Use this install"


class CCInstallPickerDialog(QDialog):
    """Modal dialog listing detected Corporate Clash installs.

    When ``active_signature`` is provided and matches one of the installs,
    that row is marked with a ``(currently active)`` suffix and pre-
    selected; the confirm button reads "Keep this install" while the
    active row stays selected, "Use this install" otherwise.
    """

    def __init__(self, installs: list[WineInstall], parent=None,
                 active_signature: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Choose Corporate Clash install")
        self.setModal(True)
        self._installs = installs
        self._selected: WineInstall | None = None
        self._active_signature = active_signature or None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel(
            "Multiple Corporate Clash installs were detected. "
            "Choose which one to use."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("cc_install_picker_list")
        active_row: int | None = None
        for i, inst in enumerate(installs):
            chip = LAUNCHER_CHIP_LABEL.get(inst.launcher, inst.launcher.upper())
            home = os.path.expanduser("~")
            short_path = inst.exe_path
            if short_path.startswith(home):
                short_path = "~" + short_path[len(home):]
            suffix = ""
            if self._active_signature and install_signature(inst) == self._active_signature:
                suffix = "  (currently active)"
                active_row = i
            text = f"[{chip}]  {inst.display_name}{suffix}\n         {short_path}"
            self.list_widget.addItem(QListWidgetItem(text))
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.confirm_btn = QPushButton(_CONFIRM_USE)
        self.confirm_btn.setDefault(True)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._confirm)
        btn_row.addWidget(self.confirm_btn)

        layout.addLayout(btn_row)
        self.resize(520, 320)

        if active_row is not None:
            # Pre-select the active row AFTER signals are connected so the
            # row-changed hook flips the button label and resolves _selected.
            self.list_widget.setCurrentRow(active_row)
            self._selected = self._installs[active_row]

    def select_index(self, idx: int):
        """Programmatically pick a row (used in tests and the boot prompt)."""
        if 0 <= idx < self.list_widget.count():
            self.list_widget.setCurrentRow(idx)
            if 0 <= idx < len(self._installs):
                self._selected = self._installs[idx]

    def selected_install(self) -> WineInstall | None:
        return self._selected

    def _on_row_changed(self, row: int):
        self.confirm_btn.setEnabled(row >= 0)
        if (
            self._active_signature
            and 0 <= row < len(self._installs)
            and install_signature(self._installs[row]) == self._active_signature
        ):
            self.confirm_btn.setText(_CONFIRM_KEEP)
        else:
            self.confirm_btn.setText(_CONFIRM_USE)

    def _on_double_click(self, _item):
        self._confirm()

    def _confirm(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._installs):
            self._selected = self._installs[row]
            self.accept()
