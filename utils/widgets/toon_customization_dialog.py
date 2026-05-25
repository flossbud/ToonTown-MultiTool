"""Toon customization picker dialog.

Replaces RacePickerDialog. Sidebar nav + section stack + live preview
+ Save/Cancel/Reset. Sections rendered based on game tag.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from utils.widgets.card_preview_widget import CardPreviewWidget


# Curated 12-color palette. Order matters - first row primaries, second
# row accents, third row neutrals.
PRESET_SWATCHES = (
    "#e74a4a", "#e7894a", "#d9a04e", "#e6d35a",
    "#56c856", "#4ae7d9", "#4a8fe7", "#4a5fe7",
    "#b04ae7", "#e74ab0", "#7a7a8a", "#1a1d29",
)


class _SwatchRow(QWidget):
    """Default swatch + 12 presets + Custom button. Emits color_picked(hex or None).
    None means 'Default' (remove the field from the draft)."""

    color_picked = Signal(object)  # str (hex) or None

    def __init__(self, current: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._current = current  # hex or None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        # Default swatch first
        self._default_btn = QPushButton("Default")
        self._default_btn.setFixedHeight(22)
        self._default_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #9a9aa8; "
            "border: 1px dashed #555a70; border-radius: 4px; padding: 0 8px; }"
            "QPushButton:checked { border: 2px solid #fff; color: #fff; }"
        )
        self._default_btn.setCheckable(True)
        self._default_btn.clicked.connect(lambda: self._select(None))
        outer.addWidget(self._default_btn)
        self._preset_btns: list[QPushButton] = []
        for hex_ in PRESET_SWATCHES:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setStyleSheet(
                f"QPushButton {{ background: {hex_}; "
                f"border: 1px solid #4a5070; border-radius: 4px; }}"
                f"QPushButton:checked {{ border: 2px solid #fff; }}"
            )
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, h=hex_: self._select(h))
            outer.addWidget(btn)
            self._preset_btns.append(btn)
        self._custom_btn = QPushButton("…")
        self._custom_btn.setFixedSize(22, 22)
        self._custom_btn.setStyleSheet(
            "QPushButton { background: #3a3f55; color: #d8d8e0; "
            "border: 1px dashed #6a6f85; border-radius: 4px; }"
        )
        self._custom_btn.clicked.connect(self._open_color_dialog)
        outer.addWidget(self._custom_btn)
        outer.addStretch(1)
        self._refresh_checked()

    def _select(self, hex_: Optional[str]) -> None:
        self._current = hex_
        self._refresh_checked()
        self.color_picked.emit(hex_)

    def _refresh_checked(self) -> None:
        self._default_btn.setChecked(self._current is None)
        for btn, hex_ in zip(self._preset_btns, PRESET_SWATCHES):
            btn.setChecked(hex_ == self._current)

    def _open_color_dialog(self) -> None:
        initial = QColor(self._current) if self._current else QColor("#ffffff")
        chosen = QColorDialog.getColor(initial, self, "Pick a color")
        if chosen.isValid():
            self._select(chosen.name())

    def current(self) -> Optional[str]:
        return self._current

    def set_current(self, hex_: Optional[str]) -> None:
        self._current = hex_
        self._refresh_checked()


class _SimpleColorSection(QWidget):
    """A section that contains a single label + one _SwatchRow."""

    color_changed = Signal(object)  # str or None

    def __init__(self, label: str, current: Optional[str], parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        title = QLabel(label)
        title.setStyleSheet("color: #c8c8d8; font-weight: bold;")
        outer.addWidget(title)
        self._row = _SwatchRow(current)
        self._row.color_picked.connect(self.color_changed.emit)
        outer.addWidget(self._row)
        outer.addStretch(1)

    def current(self) -> Optional[str]:
        return self._row.current()

    def set_current(self, hex_: Optional[str]) -> None:
        self._row.set_current(hex_)


class ToonCustomizationDialog(QDialog):
    customization_changed = Signal()

    def __init__(self, game: str, toon_name: str, manager, parent=None):
        super().__init__(parent)
        self._game = game
        self._toon_name = toon_name
        self._manager = manager
        self._draft: dict = dict(manager.get(game, toon_name))
        self._sections: dict[str, QWidget] = {}

        self.setWindowTitle(f"Customize {toon_name}")
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)
        self._build_ui()

    # -- Public test API -------------------------------------------------------

    def section_names(self) -> list[str]:
        return list(self._sections.keys())

    def draft(self) -> dict:
        return dict(self._draft)

    def set_accent(self, hex_: Optional[str]) -> None:
        accent_section: _SimpleColorSection = self._sections["Accent"]
        accent_section.set_current(hex_)
        self._on_accent_changed(hex_)

    def set_body(self, hex_: Optional[str]) -> None:
        body_section: _SimpleColorSection = self._sections["Body"]
        body_section.set_current(hex_)
        self._on_body_changed(hex_)

    def reset_all(self) -> None:
        self._draft = {}
        for name, w in self._sections.items():
            if isinstance(w, _SimpleColorSection):
                w.set_current(None)
        self._preview.set_draft(self._draft)

    def accept_save(self) -> None:
        self._manager.set(self._game, self._toon_name, self._draft)
        self.customization_changed.emit()
        self.accept()

    # -- UI build --------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # Live preview at the top
        self._preview = CardPreviewWidget(self._game, self._toon_name, self._draft)
        preview_box = QVBoxLayout()
        preview_box.setContentsMargins(0, 0, 0, 0)
        preview_box.addWidget(self._preview, alignment=Qt.AlignHCenter)
        outer.addLayout(preview_box)

        # Body row: sidebar + stack
        body_row = QHBoxLayout()
        body_row.setSpacing(8)

        self._nav = QListWidget()
        self._nav.setFixedWidth(110)
        self._nav.setStyleSheet(
            "QListWidget { background: #252939; border: 1px solid #3a3f55; }"
            "QListWidget::item { padding: 6px 10px; color: #9a9aa8; }"
            "QListWidget::item:selected { background: #2a2f44; color: #e8e8f0; "
            "border-left: 3px solid #4a7cff; }"
        )
        self._stack = QStackedWidget()

        # CC-only Icon section is added by Task 10. Stub for now: missing.

        # Portrait section is added by Task 9. Stub for now: a placeholder
        # widget so the section list isn't empty.
        portrait_placeholder = QLabel("Portrait controls land in a later task.")
        portrait_placeholder.setStyleSheet("color: #6a6f85; padding: 12px;")
        self._add_section("Portrait", portrait_placeholder)

        # Accent
        accent_section = _SimpleColorSection(
            "Accent (stripe + chip)", self._draft.get("accent")
        )
        accent_section.color_changed.connect(self._on_accent_changed)
        self._add_section("Accent", accent_section)

        # Body
        body_section = _SimpleColorSection(
            "Body tint", self._draft.get("body")
        )
        body_section.color_changed.connect(self._on_body_changed)
        self._add_section("Body", body_section)

        body_row.addWidget(self._nav)
        body_row.addWidget(self._stack, 1)
        outer.addLayout(body_row, 1)

        # Footer
        footer = QHBoxLayout()
        reset = QPushButton("Reset all")
        reset.clicked.connect(self.reset_all)
        footer.addWidget(reset)
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self.accept_save)
        footer.addWidget(save)
        outer.addLayout(footer)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

    def _add_section(self, name: str, widget: QWidget) -> None:
        self._sections[name] = widget
        QListWidgetItem(name, self._nav)
        self._stack.addWidget(widget)

    # -- Field handlers --------------------------------------------------------

    def _on_accent_changed(self, hex_: Optional[str]) -> None:
        if hex_ is None:
            self._draft.pop("accent", None)
        else:
            self._draft["accent"] = hex_
        self._preview.set_draft(self._draft)

    def _on_body_changed(self, hex_: Optional[str]) -> None:
        if hex_ is None:
            self._draft.pop("body", None)
        else:
            self._draft["body"] = hex_
        self._preview.set_draft(self._draft)
