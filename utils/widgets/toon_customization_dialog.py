"""Toon customization picker dialog.

Sidebar nav + section stack + live preview + Save/Cancel/Reset.
Sections rendered based on game tag.

NOTE: This file is being phased out in favor of
utils.widgets.customization_overlay.ToonCustomizationOverlay. Section
widgets live in utils.widgets.toon_customization_sections.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from utils.widgets.card_preview_widget import CardPreviewWidget
from utils.widgets.race_icon_grid import RaceIconGridWidget
from utils.widgets.toon_customization_sections import (
    PRESET_SWATCHES,
    _ChipRow,
    _PortraitSection,
    _PoseAdjustPreview,
    _PoseAdjustView,
    _PoseSection,
    _PoseTile,
    _SimpleColorSection,
    _SwatchRow,
)


class ToonCustomizationDialog(QDialog):
    customization_changed = Signal()

    def __init__(
        self,
        game: str,
        toon_name: str,
        manager,
        skin_color: Optional[QColor] = None,
        auto_stem: Optional[str] = None,
        dna: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._game = game
        self._toon_name = toon_name
        self._manager = manager
        self._skin = skin_color
        self._auto_stem = auto_stem
        self._dna = dna
        self._draft: dict = dict(manager.get(game, toon_name))
        self._sections: dict[str, QWidget] = {}

        self.setWindowTitle(f"Customize {toon_name}")
        self.setMinimumWidth(720)
        self.setMinimumHeight(520)
        self._build_ui()
        self.resize(760, 560)

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

    def set_pose(self, pose: str) -> None:
        """Public test API: programmatically pick a pose."""
        from utils.rendition_poses import POSE_NAMES
        if pose not in POSE_NAMES:
            return
        if "Toon" in self._sections:
            sec = self._sections["Toon"]
            # Force the section to think the click is fresh by bypassing its
            # short-circuit when pose == current_pose.
            if pose == sec._current_pose:
                # Default behaviour: if already selected, just rewrite draft
                # explicitly (the spec test exercises a back-to-default flow).
                self._on_pose_changed(pose)
                return
            sec._on_tile_clicked(pose)
        else:
            self._on_pose_changed(pose)

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

    def set_circle_outline(
        self, hex_: Optional[str], width_key: Optional[str],
    ) -> None:
        sec: _PortraitSection = self._sections["Portrait"]
        sec.set_circle_outline(hex_, width_key)

    def set_silhouette_outline(
        self, hex_: Optional[str], width_key: Optional[str],
    ) -> None:
        if "Toon" in self._sections:
            sec = self._sections["Toon"]
            sec.set_silhouette_outline(hex_, width_key)
        else:
            self._on_silhouette_outline(hex_, width_key or "medium")

    def set_silhouette_shadow(
        self, hex_: Optional[str], softness_key: Optional[str],
    ) -> None:
        if "Toon" in self._sections:
            sec = self._sections["Toon"]
            sec.set_silhouette_shadow(hex_, softness_key)
        else:
            self._on_silhouette_shadow(hex_, softness_key or "medium")

    def reset_all(self) -> None:
        self._draft = {}
        for name, w in self._sections.items():
            if isinstance(w, _SimpleColorSection):
                w.set_current(None)
            elif isinstance(w, _PortraitSection):
                w.set_color(None)
                w.set_gradient(None)
                w.set_pattern(None, None)
                w.set_circle_outline(None, None)
            elif isinstance(w, _PoseSection):
                for t in w.tiles():
                    t.set_selected(t.pose == "portrait")
                w._current_pose = "portrait"
                # Clear the Adjust view's silhouette picker state if it
                # was lazy-constructed - otherwise the swatch color
                # persists and any subsequent interaction re-writes the
                # silhouette back into the draft.
                if w._adjust_view is not None:
                    w._adjust_view.set_silhouette_outline_from_draft(None, None)
                    w._adjust_view.set_silhouette_shadow_from_draft(None, None)
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
        self._preview = CardPreviewWidget(
            self._game, self._toon_name, self._draft, dna=self._dna,
        )
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

        # Toon section (TTR only, first in sidebar for TTR)
        if self._game == "ttr":
            from utils.toon_customization_resolve import (
                resolve_pose, resolve_portrait_transform,
            )
            current_pose = resolve_pose(self._draft, "portrait")
            pose_section = _PoseSection(self._dna, current_pose)
            pose_section.pose_changed.connect(self._on_pose_changed)
            pose_section.transform_changed.connect(self._on_transform_changed)
            pose_section.silhouette_outline_changed.connect(self._on_silhouette_outline)
            pose_section.silhouette_shadow_changed.connect(self._on_silhouette_shadow)
            initial_transform = resolve_portrait_transform(self._draft)
            pose_section.set_transform_from_draft(initial_transform)
            sil = (self._draft.get("portrait") or {}).get("silhouette") or {}
            outline = sil.get("outline") or {}
            pose_section.set_silhouette_outline(
                outline.get("color"), outline.get("width"),
            )
            shadow = sil.get("shadow") or {}
            pose_section.set_silhouette_shadow(
                shadow.get("color"), shadow.get("softness"),
            )
            self._add_section("Toon", pose_section)

        # Portrait
        portrait_section = _PortraitSection(self._draft.get("portrait") or {})
        portrait_section.color_changed.connect(self._on_portrait_color)
        portrait_section.gradient_changed.connect(self._on_portrait_gradient)
        portrait_section.pattern_changed.connect(self._on_portrait_pattern)
        portrait_section.circle_outline_changed.connect(self._on_circle_outline)
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

    def _on_pose_changed(self, pose: str) -> None:
        if pose == "portrait":
            # Default - don't pollute the saved entry with the default.
            self._draft.pop("pose", None)
        else:
            self._draft["pose"] = pose
        self._preview.set_draft(self._draft)

    def _on_transform_changed(self) -> None:
        """The Toon section's adjust view changed the transform. Write
        into _draft["portrait"]["transform"]; omit the sub-object when
        at defaults so the saved entry stays minimal."""
        sec = self._sections["Toon"]
        zoom, off_x, off_y, rot = sec.transform()
        portrait = self._draft.setdefault("portrait", {})
        if (
            abs(zoom - 1.0) < 1e-6
            and abs(off_x) < 1e-6
            and abs(off_y) < 1e-6
            and abs(rot) < 1e-6
        ):
            portrait.pop("transform", None)
        else:
            portrait["transform"] = {
                "zoom": zoom,
                "offset_x": off_x,
                "offset_y": off_y,
                "rotate": rot,
            }
        if not self._draft.get("portrait"):
            self._draft.pop("portrait", None)
        self._preview.set_draft(self._draft)

    def _on_silhouette_outline(
        self, hex_: Optional[str], width_key: Optional[str],
    ) -> None:
        portrait = self._draft.setdefault("portrait", {})
        sil = portrait.setdefault("silhouette", {})
        if hex_ is None:
            sil.pop("outline", None)
        else:
            sil["outline"] = {"color": hex_, "width": width_key}
        if not sil:
            portrait.pop("silhouette", None)
        if not portrait:
            self._draft.pop("portrait", None)
        self._preview.set_draft(self._draft)

    def _on_silhouette_shadow(
        self, hex_, softness_key,
    ) -> None:
        portrait = self._draft.setdefault("portrait", {})
        sil = portrait.setdefault("silhouette", {})
        if hex_ is None:
            sil.pop("shadow", None)
        else:
            sil["shadow"] = {"color": hex_, "softness": softness_key}
        if not sil:
            portrait.pop("silhouette", None)
        if not portrait:
            self._draft.pop("portrait", None)
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

    def _on_circle_outline(
        self, hex_: Optional[str], width_key: str,
    ) -> None:
        sub = self._portrait_subdict()
        if hex_ is None:
            sub.pop("outline", None)
        else:
            sub["outline"] = {"color": hex_, "width": width_key}
        self._prune_portrait()
        self._preview.set_draft(self._draft)
