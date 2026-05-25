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
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from utils.toon_pattern_assets import PATTERN_NAMES
from utils.widgets.card_preview_widget import CardPreviewWidget
from utils.widgets.race_icon_grid import RaceIconGridWidget


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


class _PortraitSection(QWidget):
    """Portrait color + gradient + pattern controls.

    Holds three sub-controls:
      - color row (default + 12 presets + custom)
      - gradient toggle + 2 color rows (only visible when toggle is on)
      - pattern picker (none + 8 patterns) + pattern color row
        (only visible when a pattern is selected)
    """

    color_changed = Signal(object)         # str or None
    gradient_changed = Signal(object)      # {"start", "end"} or None
    pattern_changed = Signal(object, object)  # (name or None, color or None)

    def __init__(self, current: dict, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        outer.addWidget(self._label("Color"))
        self._color_row = _SwatchRow(current.get("color"))
        self._color_row.color_picked.connect(self.color_changed.emit)
        outer.addWidget(self._color_row)

        outer.addWidget(self._label("Gradient"))
        grad_row = QHBoxLayout()
        self._grad_toggle = QPushButton("Off")
        self._grad_toggle.setCheckable(True)
        self._grad_toggle.setFixedHeight(22)
        self._grad_toggle.clicked.connect(self._on_gradient_toggle)
        grad_row.addWidget(self._grad_toggle)
        grad_row.addStretch(1)
        outer.addLayout(grad_row)

        self._grad_start = _SwatchRow(
            (current.get("gradient") or {}).get("start")
        )
        self._grad_end = _SwatchRow(
            (current.get("gradient") or {}).get("end")
        )
        self._grad_start.color_picked.connect(lambda _: self._emit_gradient())
        self._grad_end.color_picked.connect(lambda _: self._emit_gradient())
        outer.addWidget(self._grad_start)
        outer.addWidget(self._grad_end)

        outer.addWidget(self._label("Pattern"))
        pat_row = QHBoxLayout()
        self._pat_buttons: dict[Optional[str], QPushButton] = {}
        none_btn = QPushButton("None")
        none_btn.setCheckable(True)
        none_btn.setFixedHeight(22)
        none_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        none_btn.adjustSize()
        none_btn.clicked.connect(lambda: self._select_pattern(None))
        pat_row.addWidget(none_btn)
        self._pat_buttons[None] = none_btn
        for name in PATTERN_NAMES:
            b = QPushButton(name.replace("_", " "))
            b.setCheckable(True)
            b.setFixedHeight(22)
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.adjustSize()
            b.clicked.connect(lambda _=False, n=name: self._select_pattern(n))
            pat_row.addWidget(b)
            self._pat_buttons[name] = b
        pat_row.addStretch(1)
        outer.addLayout(pat_row)

        outer.addWidget(self._label("Pattern color"))
        self._pat_color_row = _SwatchRow(
            (current.get("pattern") or {}).get("color")
        )
        self._pat_color_row.color_picked.connect(lambda _: self._emit_pattern())
        outer.addWidget(self._pat_color_row)

        outer.addStretch(1)

        # Initialize visibility / checked state from `current`.
        grad = current.get("gradient")
        if isinstance(grad, dict):
            self._grad_toggle.setChecked(True)
            self._grad_toggle.setText("On")
        else:
            self._grad_start.setVisible(False)
            self._grad_end.setVisible(False)

        pat = current.get("pattern") or {}
        pat_name = pat.get("name") if isinstance(pat, dict) else None
        self._current_pat = pat_name
        self._refresh_pat_checked()
        self._pat_color_row.setVisible(pat_name is not None)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: #9a9aa8; font-size: 10px; "
            "text-transform: uppercase; letter-spacing: 0.5px;"
        )
        return lbl

    def _on_gradient_toggle(self) -> None:
        on = self._grad_toggle.isChecked()
        self._grad_toggle.setText("On" if on else "Off")
        self._grad_start.setVisible(on)
        self._grad_end.setVisible(on)
        self._emit_gradient()

    def _emit_gradient(self) -> None:
        if not self._grad_toggle.isChecked():
            self.gradient_changed.emit(None)
            return
        start = self._grad_start.current()
        end = self._grad_end.current()
        if start and end:
            self.gradient_changed.emit({"start": start, "end": end})
        else:
            self.gradient_changed.emit(None)

    def _select_pattern(self, name: Optional[str]) -> None:
        self._current_pat = name
        self._refresh_pat_checked()
        self._pat_color_row.setVisible(name is not None)
        self._emit_pattern()

    def _refresh_pat_checked(self) -> None:
        for n, btn in self._pat_buttons.items():
            btn.setChecked(n == self._current_pat)

    def _emit_pattern(self) -> None:
        if self._current_pat is None:
            self.pattern_changed.emit(None, None)
            return
        color = self._pat_color_row.current() or "#ffffff"
        self.pattern_changed.emit(self._current_pat, color)

    # -- programmatic setters (for tests) --------------------------------------

    def set_color(self, hex_: Optional[str]) -> None:
        self._color_row.set_current(hex_)

    def set_gradient(self, grad: Optional[dict]) -> None:
        on = isinstance(grad, dict)
        self._grad_toggle.setChecked(on)
        self._grad_toggle.setText("On" if on else "Off")
        self._grad_start.setVisible(on)
        self._grad_end.setVisible(on)
        if on:
            self._grad_start.set_current(grad.get("start"))
            self._grad_end.set_current(grad.get("end"))

    def set_pattern(self, name: Optional[str], color: Optional[str]) -> None:
        self._current_pat = name
        self._refresh_pat_checked()
        self._pat_color_row.setVisible(name is not None)
        if color is not None:
            self._pat_color_row.set_current(color)


class ToonCustomizationDialog(QDialog):
    customization_changed = Signal()

    def __init__(
        self,
        game: str,
        toon_name: str,
        manager,
        skin_color: Optional[QColor] = None,
        auto_stem: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._game = game
        self._toon_name = toon_name
        self._manager = manager
        self._skin = skin_color
        self._auto_stem = auto_stem
        self._draft: dict = dict(manager.get(game, toon_name))
        self._sections: dict[str, QWidget] = {}

        self.setWindowTitle(f"Customize {toon_name}")
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)
        self._build_ui()

    # -- Public test API -------------------------------------------------------

    def section_names(self) -> list[str]:
        return list(self._sections.keys())

    def section(self, name: str) -> QWidget:
        return self._sections[name]

    def draft(self) -> dict:
        return dict(self._draft)

    def set_icon_stem(self, stem: Optional[str]) -> None:
        if self._game != "cc":
            return
        if "Icon" not in self._sections:
            return
        grid: RaceIconGridWidget = self._sections["Icon"]
        if stem is None:
            # Best-effort: nothing to call to "unselect" the grid, so we just
            # update the draft. The dialog tracks the unset state and the
            # grid will visually fall back to the auto-marked tile.
            self._draft.pop("icon_stem", None)
            self._preview.set_draft(self._draft)
            return
        grid.select_stem(stem)
        self._on_icon_stem(stem)

    def set_accent(self, hex_: Optional[str]) -> None:
        accent_section: _SimpleColorSection = self._sections["Accent"]
        accent_section.set_current(hex_)
        self._on_accent_changed(hex_)

    def set_body(self, hex_: Optional[str]) -> None:
        body_section: _SimpleColorSection = self._sections["Body"]
        body_section.set_current(hex_)
        self._on_body_changed(hex_)

    # -- Portrait setters for tests --------------------------------------------

    def set_portrait_color(self, hex_: Optional[str]) -> None:
        sec: _PortraitSection = self._sections["Portrait"]
        sec.set_color(hex_)
        self._on_portrait_color(hex_)

    def set_portrait_gradient(self, grad: Optional[dict]) -> None:
        sec: _PortraitSection = self._sections["Portrait"]
        sec.set_gradient(grad)
        self._on_portrait_gradient(grad)

    def set_portrait_pattern(self, name: Optional[str], color: Optional[str]) -> None:
        sec: _PortraitSection = self._sections["Portrait"]
        sec.set_pattern(name, color)
        self._on_portrait_pattern(name, color)

    def reset_all(self) -> None:
        self._draft = {}
        for name, w in self._sections.items():
            if isinstance(w, _SimpleColorSection):
                w.set_current(None)
            elif isinstance(w, _PortraitSection):
                w.set_color(None)
                w.set_gradient(None)
                w.set_pattern(None, None)
            # RaceIconGridWidget keeps its visual selection; that's fine,
            # the draft no longer references it so save will skip it.
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

        # Icon (CC only)
        if self._game == "cc":
            skin = self._skin or QColor("#d9a04e")
            grid = RaceIconGridWidget(
                skin_color=skin,
                selected_stem=self._draft.get("icon_stem"),
                auto_stem=self._auto_stem,
            )
            grid.selection_changed.connect(self._on_icon_stem)
            self._add_section("Icon", grid)

        # Portrait
        portrait_section = _PortraitSection(self._draft.get("portrait") or {})
        portrait_section.color_changed.connect(self._on_portrait_color)
        portrait_section.gradient_changed.connect(self._on_portrait_gradient)
        portrait_section.pattern_changed.connect(self._on_portrait_pattern)
        self._add_section("Portrait", portrait_section)

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

    def _on_icon_stem(self, stem: str) -> None:
        if stem:
            self._draft["icon_stem"] = stem
        else:
            self._draft.pop("icon_stem", None)
        self._preview.set_draft(self._draft)

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

    # -- Portrait field handlers -----------------------------------------------

    def _portrait_subdict(self) -> dict:
        return self._draft.setdefault("portrait", {})

    def _prune_portrait(self) -> None:
        if not self._draft.get("portrait"):
            self._draft.pop("portrait", None)

    def _on_portrait_color(self, hex_: Optional[str]) -> None:
        sub = self._portrait_subdict()
        if hex_ is None:
            sub.pop("color", None)
        else:
            sub["color"] = hex_
        self._prune_portrait()
        self._preview.set_draft(self._draft)

    def _on_portrait_gradient(self, grad: Optional[dict]) -> None:
        sub = self._portrait_subdict()
        if grad is None:
            sub.pop("gradient", None)
        else:
            sub["gradient"] = dict(grad)
        self._prune_portrait()
        self._preview.set_draft(self._draft)

    def _on_portrait_pattern(self, name: Optional[str], color: Optional[str]) -> None:
        sub = self._portrait_subdict()
        if name is None:
            sub.pop("pattern", None)
        else:
            sub["pattern"] = {"name": name, "color": color or "#ffffff"}
        self._prune_portrait()
        self._preview.set_draft(self._draft)
