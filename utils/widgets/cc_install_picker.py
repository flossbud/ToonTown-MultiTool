"""Themed picker dialog for choosing among multiple Corporate Clash installs."""

from __future__ import annotations

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QWidget,
)

from services.wine_runtimes import WineInstall


_LAUNCHER_CHIP_LABEL = {
    "bottles": "BOTTLES",
    "lutris": "LUTRIS",
    "steam-proton": "STEAM",
    "wine": "WINE",
    "native": "NATIVE",
}


class CCInstallPickerDialog(QDialog):
    """Modal dialog listing detected Corporate Clash installs.

    Visual style matches the surrounding settings tab (subtle border, themed
    surface). The active theme is applied via apply_theme() in the parent.
    """

    def __init__(self, installs: list[WineInstall], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose Corporate Clash install")
        self.setModal(True)
        self._installs = installs
        self._selected: WineInstall | None = None

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
        for inst in installs:
            chip = _LAUNCHER_CHIP_LABEL.get(inst.launcher, inst.launcher.upper())
            home = os.path.expanduser("~")
            short_path = inst.exe_path
            if short_path.startswith(home):
                short_path = "~" + short_path[len(home):]
            text = f"[{chip}]  {inst.display_name}\n         {short_path}"
            item = QListWidgetItem(text)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.confirm_btn = QPushButton("Use this install")
        self.confirm_btn.setDefault(True)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._confirm)
        btn_row.addWidget(self.confirm_btn)

        layout.addLayout(btn_row)
        self.resize(520, 320)

    def select_index(self, idx: int):
        """Programmatically pick a row (used in tests and the boot prompt).

        Sets both the visible selection and the resolved selection so callers
        can read selected_install() without driving the confirm button.
        """
        if 0 <= idx < self.list_widget.count():
            self.list_widget.setCurrentRow(idx)
            if 0 <= idx < len(self._installs):
                self._selected = self._installs[idx]

    def selected_install(self) -> WineInstall | None:
        return self._selected

    def _on_row_changed(self, row: int):
        self.confirm_btn.setEnabled(row >= 0)

    def _on_double_click(self, _item):
        self._confirm()

    def _confirm(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._installs):
            self._selected = self._installs[row]
            self.accept()
