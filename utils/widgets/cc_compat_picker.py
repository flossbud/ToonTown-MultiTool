"""Themed picker dialog for choosing the Proton runtime TTMT uses
when launching Corporate Clash through Steam.

Sibling to cc_install_picker.py: same card-based chrome, different content.
Settings UI invokes this when the user clicks [Change...] on the
compatibility-runtime row.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from services.steam_proton_tools import ProtonTool
from utils.widgets.picker_card import PickerCard


_SOURCE_TAG_LABEL = {
    "compatibilitytools.d": "USER",
    "official": "OFFICIAL",
}
_SOURCE_TAG_COLOR = {
    "USER": "#b39dff",
    "OFFICIAL": "#6bd66b",
}


def _format_sub(source: str) -> str:
    tag = _SOURCE_TAG_LABEL.get(source, source.upper())
    color = _SOURCE_TAG_COLOR.get(tag, "#888888")
    return (
        f'<span style="color:{color}; font-weight:700; '
        f'letter-spacing:0.5px; font-size:10px;">{tag}</span>'
    )


class CCCompatPickerDialog(QDialog):
    """Modal: pick "Use Steam's selection" (AUTO card) or a specific Proton."""

    def __init__(
        self,
        tools: list[ProtonTool],
        current_override: str,
        steam_default_display: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("picker_dialog")
        self.setWindowTitle("Compatibility runtime")
        self.setModal(True)
        self._tools = tools
        self._chosen_override: str | None = None
        # Card index 0 is AUTO; indices 1..N map to tools[0..N-1].
        self._cards: list[PickerCard] = []
        self._selected_index: int = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)

        intro = QLabel(
            "How should TTMT launch Corporate Clash through Steam?"
        )
        intro.setObjectName("picker_intro")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("picker_card_list")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        try:
            from utils.widgets.auto_hide_scrollbar import install_modern_scrollbar
            from utils.theme_manager import is_dark_palette
            install_modern_scrollbar(self._scroll, is_dark=is_dark_palette())
        except Exception:
            pass

        card_holder = QWidget()
        col = QVBoxLayout(card_holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)

        # AUTO card.
        auto_card = PickerCard(
            chip_slug="auto",
            name="Use Steam's selection",
            sub=f"Resolves to: {steam_default_display}",
        )
        auto_card.clicked.connect(lambda: self._on_card_clicked(0))
        auto_card.doubleClicked.connect(lambda: self._on_card_double_clicked(0))
        col.addWidget(auto_card)
        self._cards.append(auto_card)

        # Section label + per-Proton cards (only when there are tools).
        if tools:
            section = QLabel("OR PICK A SPECIFIC PROTON VERSION")
            section.setObjectName("picker_section_label")
            col.addWidget(section)

            for i, tool in enumerate(tools, start=1):
                card = PickerCard(
                    chip_slug="proton",
                    name=tool.nickname,
                    sub=_format_sub(tool.source),
                )
                card.clicked.connect(lambda i=i: self._on_card_clicked(i))
                card.doubleClicked.connect(lambda i=i: self._on_card_double_clicked(i))
                col.addWidget(card)
                self._cards.append(card)

        col.addStretch(1)
        self._scroll.setWidget(card_holder)
        outer.addWidget(self._scroll, 1)

        # Buttons.
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("picker_primary_btn")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        outer.addLayout(btn_row)

        self.resize(640, 480)
        self.setMinimumSize(560, 360)
        self.setMaximumWidth(820)

        # Initial selection: reflect current_override. If override does not
        # match any enumerated tool (e.g. it was uninstalled since saved),
        # fall back to AUTO. Mirrors services/cc_launcher.resolve_effective_proton.
        matched = 0
        if current_override:
            for i, tool in enumerate(tools, start=1):
                if tool.proton_dir == current_override:
                    matched = i
                    break
        self._select_card(matched)

    # -- Public API (preserved) --------------------------------------------
    def cards(self) -> list[PickerCard]:
        return list(self._cards)

    def chosen_override(self) -> str | None:
        """After accept(): "" for Steam's selection, or absolute proton_dir.

        Returns None if the dialog was rejected.
        """
        return self._chosen_override

    # -- Internal ----------------------------------------------------------
    def _on_card_clicked(self, idx: int) -> None:
        self._select_card(idx)

    def _on_card_double_clicked(self, idx: int) -> None:
        self._select_card(idx)
        self._on_save()

    def _select_card(self, idx: int) -> None:
        if not (0 <= idx < len(self._cards)):
            return
        if self._selected_index != idx:
            if 0 <= self._selected_index < len(self._cards):
                self._cards[self._selected_index].set_selected(False)
        self._selected_index = idx
        self._cards[idx].set_selected(True)

    def _on_save(self) -> None:
        idx = self._selected_index
        if idx == 0:
            self._chosen_override = ""
            self.accept()
            return
        # idx 1..N maps to tools[idx-1].
        tool_index = idx - 1
        if not (0 <= tool_index < len(self._tools)):
            self.reject()
            return
        self._chosen_override = self._tools[tool_index].proton_dir
        self.accept()
