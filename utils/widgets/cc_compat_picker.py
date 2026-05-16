"""Themed picker dialog for choosing the Proton runtime TTMT uses
when launching Corporate Clash through Steam.

Sibling to cc_install_picker.py — same dialog chrome, different
content. Settings UI invokes this when the user clicks [Change…] on
the compatibility-runtime row.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QButtonGroup, QListWidget, QListWidgetItem, QWidget,
)

from services.steam_proton_tools import ProtonTool


_SOURCE_TAG = {
    "compatibilitytools.d": "user",
    "official": "official",
}


class CCCompatPickerDialog(QDialog):
    """Modal: pick Steam's selection (cascade) or a specific Proton."""

    def __init__(
        self,
        tools: list[ProtonTool],
        current_override: str,
        steam_default_display: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Compatibility runtime")
        self.setModal(True)
        self._tools = tools
        self._chosen_override: str | None = None  # None = use Steam's selection

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel(
            "How should TTMT launch Corporate Clash through Steam?"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Radio: use Steam's selection.
        self.use_steam_radio = QRadioButton("Use Steam's selection")
        layout.addWidget(self.use_steam_radio)
        steam_help = QLabel(
            f"Currently resolves to: {steam_default_display}\n"
            "(matches what Steam itself would use)"
        )
        steam_help.setObjectName("compat_picker_steam_help")
        steam_help.setIndent(24)
        steam_help.setWordWrap(True)
        layout.addWidget(steam_help)

        # Radio: pick a specific Proton.
        self.use_specific_radio = QRadioButton("Use a specific Proton:")
        layout.addWidget(self.use_specific_radio)

        # Group both radios so they're mutually exclusive.
        self._radio_group = QButtonGroup(self)
        self._radio_group.setExclusive(True)
        self._radio_group.addButton(self.use_steam_radio)
        self._radio_group.addButton(self.use_specific_radio)

        # List of tools (only enabled when "specific" is selected).
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("cc_compat_picker_list")
        for tool in tools:
            tag = _SOURCE_TAG.get(tool.source, tool.source)
            label = f"{tool.display_name}    [{tag}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, tool.proton_dir)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        # Wire radio → list-enabled state.
        self.use_steam_radio.toggled.connect(self._on_radio_changed)
        self.use_specific_radio.toggled.connect(self._on_radio_changed)

        # Initial selection: reflect current_override. If the override path
        # is non-empty but no longer matches any enumerated tool (e.g. the
        # Proton was uninstalled since the override was saved), fall back
        # to "Use Steam's selection" rather than leaving the user in a
        # confusing "specific Proton checked but no row selected" state.
        # This mirrors the self-healing posture the launch-time resolver
        # already applies (see services/cc_launcher._resolve_effective_proton).
        matched_row = -1
        if current_override:
            for i in range(self.list_widget.count()):
                if self.list_widget.item(i).data(Qt.UserRole) == current_override:
                    matched_row = i
                    break
        if matched_row >= 0:
            self.use_specific_radio.setChecked(True)
            self.list_widget.setCurrentRow(matched_row)
        else:
            self.use_steam_radio.setChecked(True)
        self._on_radio_changed()

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

        self.resize(540, 360)

    def _on_radio_changed(self, *_):
        self.list_widget.setEnabled(self.use_specific_radio.isChecked())

    def _on_save(self):
        if self.use_steam_radio.isChecked():
            self._chosen_override = ""
            self.accept()
            return
        row = self.list_widget.currentRow()
        if row < 0 or row >= self.list_widget.count():
            # No specific Proton selected; treat as Cancel-equivalent.
            self.reject()
            return
        self._chosen_override = self.list_widget.item(row).data(Qt.UserRole)
        self.accept()

    def chosen_override(self) -> str | None:
        """After accept(): "" for Steam's selection, or absolute proton_dir.

        Returns None if the dialog was rejected.
        """
        return self._chosen_override
