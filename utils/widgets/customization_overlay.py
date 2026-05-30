"""In-app overlay that replaces the floating ToonCustomizationDialog.

Owns:
  - _BackdropBlur: paints a frozen blurred grab of the multitoon tab
                   plus a 40 % black dim layer
  - _Panel:        the editor card (header / preview / pill nav /
                   section stack / footer)
  - ToonCustomizationOverlay: the host widget. Public API:
                              open_for, request_close,
                              close_and_discard, close_and_save.

See docs/superpowers/specs/2026-05-26-customization-inline-panel-design.md
for the design contract.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from utils.icon_factory import make_x_icon
from utils.motion import reduced_motion_enabled

from utils.image_blur import gaussian_blur_pixmap
from utils.widgets.card_preview_widget import CardPreviewWidget
from utils.widgets.race_icon_grid import RaceIconGridWidget
from utils.widgets.toon_customization_sections import (
    _PortraitSection,
    _PoseSection,
    _SimpleColorSection,
)


class _BackdropBlur(QWidget):
    """Static blurred backdrop for the customization overlay.

    Exposes `opacity` as a Qt property (0.0 - 1.0) so the entry/exit
    animations can drive the backdrop's fade via QPropertyAnimation
    on the widget itself. We deliberately do NOT use
    QGraphicsOpacityEffect here: the effect's source-pixmap render
    path creates a second QPainter on the widget's paint device
    while the widget's own paintEvent has QPainter(self) active,
    producing "A paint device can only be painted by one painter at
    a time" spam. Painting with `p.setOpacity(self._opacity)` keeps
    everything inside the widget's single painter."""

    DIM_COLOR = QColor(0, 0, 0, int(0.40 * 255))
    BLUR_RADIUS = 16

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._blurred: Optional[QPixmap] = None
        self._opacity: float = 1.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def set_source_pixmap(self, pix: QPixmap) -> None:
        """Capture a fresh blurred copy of the given pixmap."""
        if pix.isNull():
            self._blurred = None
        else:
            self._blurred = gaussian_blur_pixmap(pix, self.BLUR_RADIUS)
        self.update()

    # `opacity` is a Qt property so QPropertyAnimation(self, b"opacity")
    # can drive it. Setter triggers a repaint.
    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = float(value)
        self.update()

    opacity = Property(float, _get_opacity, _set_opacity)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setOpacity(self._opacity)
        if self._blurred is not None and not self._blurred.isNull():
            # Stretch the captured pixmap to fill the widget bounds.
            p.drawPixmap(self.rect(), self._blurred, self._blurred.rect())
        p.fillRect(self.rect(), self.DIM_COLOR)
        p.end()


class _Panel(QFrame):
    """The editor card. Header / preview / pill nav / section stack /
    footer. Emits high-level intent signals that the overlay routes."""

    PANEL_W = 543
    PANEL_H = 738
    HEADER_H = 44
    FOOTER_H = 52
    PREVIEW_H = 180
    PILL_ROW_H = 40

    close_requested = Signal()
    cancel_requested = Signal()
    save_requested = Signal()
    reset_requested = Signal()
    section_changed = Signal(str)  # active pill name

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("CustomizationPanel")
        # WA_StyledBackground + WA_TranslucentBackground let the QSS
        # rgba alpha composite against the parent's painted pixels
        # (the blurred backdrop) rather than against an opaque widget
        # surface. Without WA_TranslucentBackground the panel renders
        # as a solid #1f2230 even with alpha < 255 in the QSS.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(
            "QFrame#CustomizationPanel {"
            "  background: rgba(31, 34, 48, 240);"  # ~94 % alpha of #1f2230
            "  border: 1px solid #3a3f55;"
            "  border-radius: 12px;"
            "}"
        )
        self.setFixedSize(self.PANEL_W, self.PANEL_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_preview_placeholder())
        outer.addWidget(self._build_pill_row())
        outer.addWidget(self._build_section_stack(), 1)
        outer.addWidget(self._build_footer())

    # -- subwidgets ------------------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(self.HEADER_H)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 0, 8, 0)
        row.setSpacing(8)

        self.title_label = QLabel("Customize")
        self.title_label.setStyleSheet(
            "color: #e8e8f0; font-size: 15px; font-weight: 600;"
        )
        row.addWidget(self.title_label, 1)

        # Paint the X as a QIcon (not text). KDE Breeze elides
        # QPushButton text when it doesn't fit the button's content
        # rect, which makes a small text-glyph close button render as
        # an empty square. Icons are never elided.
        self.close_btn = QPushButton()
        self.close_btn.setIcon(make_x_icon(14, QColor("#e8e8f0")))
        self.close_btn.setIconSize(QSize(14, 14))
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.setStyleSheet(
            "QPushButton {"
            "  background: #353a52;"
            "  border: none; border-radius: 6px;"
            "}"
            "QPushButton:hover { background: #4a5070; }"
        )
        self.close_btn.clicked.connect(self.close_requested)
        row.addWidget(self.close_btn)
        return bar

    def _build_preview_placeholder(self) -> QWidget:
        # CardPreviewWidget is added by populate() in a later task;
        # for now this is a fixed-height slot the layout reserves.
        self.preview_host = QWidget()
        self.preview_host.setFixedHeight(self.PREVIEW_H)
        return self.preview_host

    def _build_pill_row(self) -> QWidget:
        row_widget = QWidget()
        row_widget.setFixedHeight(self.PILL_ROW_H)
        self.pill_row = QHBoxLayout(row_widget)
        self.pill_row.setContentsMargins(16, 5, 16, 5)
        self.pill_row.setSpacing(6)
        self._pill_group = QButtonGroup(row_widget)
        self._pill_group.setExclusive(True)
        self._pill_group.idClicked.connect(self._on_pill_clicked)
        return row_widget

    def _build_section_stack(self) -> QWidget:
        self.section_stack = QStackedWidget()
        self.section_stack.setStyleSheet(
            "QStackedWidget { background: transparent; }"
        )
        return self.section_stack

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(self.FOOTER_H)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(8)

        self.reset_btn = QPushButton("Reset all")
        self.reset_btn.setFixedHeight(32)
        self.reset_btn.setStyleSheet(self._secondary_btn_css())
        self.reset_btn.clicked.connect(self.reset_requested)
        row.addWidget(self.reset_btn)

        row.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(32)
        self.cancel_btn.setStyleSheet(self._secondary_btn_css())
        self.cancel_btn.clicked.connect(self.cancel_requested)
        row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setFixedHeight(32)
        self.save_btn.setDefault(True)
        self.save_btn.setStyleSheet(self._primary_btn_css())
        self.save_btn.clicked.connect(self.save_requested)
        row.addWidget(self.save_btn)
        return bar

    @staticmethod
    def _secondary_btn_css() -> str:
        return (
            "QPushButton {"
            "  background: #353a52; color: #c8c8d0;"
            "  border: none; border-radius: 6px;"
            "  padding: 0 14px; font-size: 13px;"
            "}"
            "QPushButton:hover { background: #4a5070; }"
        )

    @staticmethod
    def _primary_btn_css() -> str:
        return (
            "QPushButton {"
            "  background: #4a7cff; color: #ffffff;"
            "  border: none; border-radius: 6px;"
            "  padding: 0 14px; font-size: 13px; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #5d8cff; }"
        )

    def _on_pill_clicked(self, index: int) -> None:
        self.section_stack.setCurrentIndex(index)
        btn = self._pill_group.button(index)
        if btn is not None:
            self.section_changed.emit(btn.text())

    # -- populate / public API ------------------------------------------

    def populate(
        self,
        *,
        game: str,
        toon_name: str,
        manager,
        dna: Optional[str] = None,
        skin_color: Optional[QColor] = None,
        auto_stem: Optional[str] = None,
    ) -> None:
        self._game = game
        self._toon_name = toon_name
        self._manager = manager
        self._dna = dna
        self._skin = skin_color
        self._auto_stem = auto_stem
        self._draft: dict = dict(manager.get(game, toon_name))
        self._sections: dict[str, QWidget] = {}

        self.title_label.setText(f"Customize {toon_name}")

        # Tear down any previous content.
        while self.pill_row.count():
            item = self.pill_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for btn in self._pill_group.buttons():
            self._pill_group.removeButton(btn)
        while self.section_stack.count():
            w = self.section_stack.widget(0)
            self.section_stack.removeWidget(w)
            w.deleteLater()

        # Preview widget lives in preview_host.
        prev_layout = self.preview_host.layout()
        if prev_layout is not None:
            while prev_layout.count():
                item = prev_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        else:
            prev_layout = QVBoxLayout(self.preview_host)
            prev_layout.setContentsMargins(0, 0, 0, 0)
        self._preview = CardPreviewWidget(
            self._game, self._toon_name, self._draft, dna=self._dna,
        )
        prev_layout.addWidget(self._preview, alignment=Qt.AlignHCenter)

        # Build sections per game.
        if self._game == "cc":
            skin = self._skin or QColor("#d9a04e")
            grid = RaceIconGridWidget(
                skin_color=skin,
                selected_stem=self._draft.get("icon_stem"),
                auto_stem=self._auto_stem,
            )
            grid.selection_changed.connect(self._on_icon_stem)
            self._add_section("Icon", grid)

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
            pose_section.set_transform_from_draft(resolve_portrait_transform(self._draft))
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

        portrait_section = _PortraitSection(self._draft.get("portrait") or {})
        portrait_section.color_changed.connect(self._on_portrait_color)
        portrait_section.gradient_changed.connect(self._on_portrait_gradient)
        portrait_section.pattern_changed.connect(self._on_portrait_pattern)
        portrait_section.circle_outline_changed.connect(self._on_circle_outline)
        self._add_section("Portrait", portrait_section)

        accent_section = _SimpleColorSection(
            "Accent (stripe + chip)", self._draft.get("accent"),
        )
        accent_section.color_changed.connect(self._on_accent_changed)
        self._add_section("Accent", accent_section)

        body_section = _SimpleColorSection(
            "Body tint", self._draft.get("body"),
        )
        body_section.color_changed.connect(self._on_body_changed)
        self._add_section("Body", body_section)

        if self._pill_group.buttons():
            self._pill_group.button(0).setChecked(True)
            self.section_stack.setCurrentIndex(0)

    def _add_section(self, name: str, widget: QWidget) -> None:
        self._sections[name] = widget
        btn = QPushButton(name)
        btn.setCheckable(True)
        btn.setFixedHeight(30)
        btn.setStyleSheet(
            "QPushButton {"
            "  background: #353a52; color: #c8c8d0;"
            "  border: none; border-radius: 8px; padding: 0 12px;"
            "  font-size: 12px;"
            "}"
            "QPushButton:checked {"
            "  background: #4a7cff; color: #ffffff;"
            "}"
        )
        idx = self.section_stack.count()
        self._pill_group.addButton(btn, idx)
        self.pill_row.addWidget(btn)

        # Wrap each section in a scroll area so long content doesn't clip.
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.section_stack.addWidget(scroll)

    def section_names(self) -> list[str]:
        return list(self._sections.keys())

    def section(self, name: str) -> QWidget:
        return self._sections[name]

    def draft(self) -> dict:
        return dict(self._draft)

    # -- Public setters used by tests + outside callers -----------------

    def set_body(self, hex_: Optional[str]) -> None:
        body_section: _SimpleColorSection = self._sections["Body"]
        body_section.set_current(hex_)
        self._on_body_changed(hex_)

    def set_accent(self, hex_: Optional[str]) -> None:
        accent_section: _SimpleColorSection = self._sections["Accent"]
        accent_section.set_current(hex_)
        self._on_accent_changed(hex_)

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
                if w._adjust_view is not None:
                    w._adjust_view.set_silhouette_outline_from_draft(None, None)
                    w._adjust_view.set_silhouette_shadow_from_draft(None, None)
        self._preview.set_draft(self._draft)

    def set_pose(self, pose: str) -> None:
        from utils.rendition_poses import POSE_NAMES
        if pose not in POSE_NAMES:
            return
        if "Toon" in self._sections:
            sec = self._sections["Toon"]
            if pose == sec._current_pose:
                self._on_pose_changed(pose)
                return
            sec._on_tile_clicked(pose)
        else:
            self._on_pose_changed(pose)

    def set_icon_stem(self, stem: Optional[str]) -> None:
        if self._game != "cc" or "Icon" not in self._sections:
            return
        grid = self._sections["Icon"]
        if stem is None:
            self._draft.pop("icon_stem", None)
            self._preview.set_draft(self._draft)
            return
        grid.select_stem(stem)
        self._on_icon_stem(stem)

    def set_portrait_color(self, hex_: Optional[str]) -> None:
        sec = self._sections["Portrait"]
        sec.set_color(hex_)
        self._on_portrait_color(hex_)

    def set_portrait_gradient(self, grad: Optional[dict]) -> None:
        sec = self._sections["Portrait"]
        sec.set_gradient(grad)
        self._on_portrait_gradient(grad)

    def set_portrait_pattern(self, name, color) -> None:
        sec = self._sections["Portrait"]
        sec.set_pattern(name, color)
        self._on_portrait_pattern(name, color)

    def set_circle_outline(self, hex_, width_key) -> None:
        sec = self._sections["Portrait"]
        sec.set_circle_outline(hex_, width_key)
        self._on_circle_outline(hex_, width_key or "medium")

    def set_silhouette_outline(self, hex_, width_key) -> None:
        if "Toon" in self._sections:
            sec = self._sections["Toon"]
            sec.set_silhouette_outline(hex_, width_key)
        else:
            self._on_silhouette_outline(hex_, width_key or "medium")

    def set_silhouette_shadow(self, hex_, softness_key) -> None:
        if "Toon" in self._sections:
            sec = self._sections["Toon"]
            sec.set_silhouette_shadow(hex_, softness_key)
        else:
            self._on_silhouette_shadow(hex_, softness_key or "medium")

    # -- Draft mutation handlers (mirror old dialog) --------------------

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
            self._draft.pop("pose", None)
        else:
            self._draft["pose"] = pose
        self._preview.set_draft(self._draft)

    def _on_transform_changed(self) -> None:
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
                "zoom": zoom, "offset_x": off_x,
                "offset_y": off_y, "rotate": rot,
            }
        if not self._draft.get("portrait"):
            self._draft.pop("portrait", None)
        self._preview.set_draft(self._draft)

    def _on_silhouette_outline(self, hex_: Optional[str], width_key: Optional[str]) -> None:
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

    def _on_silhouette_shadow(self, hex_, softness_key) -> None:
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

    def _on_circle_outline(self, hex_: Optional[str], width_key: str) -> None:
        sub = self._portrait_subdict()
        if hex_ is None:
            sub.pop("outline", None)
        else:
            sub["outline"] = {"color": hex_, "width": width_key}
        self._prune_portrait()
        self._preview.set_draft(self._draft)


class _ConfirmPrompt(QWidget):
    """Inline confirm prompt shown over the panel when the user
    requests close with unsaved changes. Slides over the preview
    area; styling intentionally matches the panel chrome."""

    keep_clicked = Signal()
    discard_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ConfirmPrompt")
        self.setStyleSheet(
            "QWidget#ConfirmPrompt {"
            "  background: rgba(31, 34, 48, 245);"
            "  border: 1px solid #4a5070;"
            "  border-radius: 10px;"
            "}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        title = QLabel("Discard unsaved changes?")
        title.setStyleSheet(
            "color: #e8e8f0; font-size: 15px; font-weight: 600;"
        )
        outer.addWidget(title)

        body = QLabel(
            "Your edits will be lost. Save first, or keep editing."
        )
        body.setWordWrap(True)
        body.setStyleSheet("color: #c8c8d0; font-size: 12px;")
        outer.addWidget(body)

        row = QHBoxLayout()
        row.addStretch(1)
        self.keep_btn = QPushButton("Keep editing")
        self.keep_btn.setFixedHeight(30)
        self.keep_btn.setStyleSheet(
            "QPushButton {"
            "  background: #4a7cff; color: #ffffff;"
            "  border: none; border-radius: 6px;"
            "  padding: 0 14px; font-size: 12px; font-weight: 600;"
            "}"
        )
        self.keep_btn.setDefault(True)
        self.keep_btn.clicked.connect(self.keep_clicked)
        self.discard_btn = QPushButton("Discard changes")
        self.discard_btn.setFixedHeight(30)
        self.discard_btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #e74a4a;"
            "  border: 1px solid #e74a4a; border-radius: 6px;"
            "  padding: 0 14px; font-size: 12px;"
            "}"
            "QPushButton:hover { background: rgba(231, 74, 74, 30); }"
        )
        self.discard_btn.clicked.connect(self.discard_clicked)
        row.addWidget(self.discard_btn)
        row.addWidget(self.keep_btn)
        outer.addLayout(row)


class ToonCustomizationOverlay(QWidget):
    """Whole-window overlay that hosts the customization editor."""

    customization_changed = Signal(int, str)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._skip_animations_for_test = False
        self._slot: Optional[int] = None
        self._game: Optional[str] = None
        self._original: dict = {}
        self._active_anim_group = None

        self.setAttribute(Qt.WA_StyledBackground, True)
        # The overlay itself is invisible chrome; visuals come from
        # _BackdropBlur and _Panel.
        self.setStyleSheet("background: transparent;")

        self._backdrop = _BackdropBlur(self)
        # Panel is a CHILD of the backdrop (not the overlay) so the
        # panel's translucent fill composites against the backdrop's
        # blurred pixels. Sibling widgets in Qt don't alpha-blend with
        # each other; nesting forces correct compositing.
        self._panel = _Panel(self._backdrop)
        self._panel.close_requested.connect(self.request_close)
        self._panel.cancel_requested.connect(self.request_close)
        self._panel.save_requested.connect(self.close_and_save)
        self._panel.reset_requested.connect(self._on_reset_requested)

        self._confirm_prompt = _ConfirmPrompt(self)
        self._confirm_prompt.hide()
        self._confirm_prompt.keep_clicked.connect(self._on_confirm_keep)
        self._confirm_prompt.discard_clicked.connect(self._on_confirm_discard)

        self.hide()

    # -- Public API -----------------------------------------------------

    def open_for(
        self,
        slot: int,
        game: str,
        toon_name: str,
        manager,
        dna: Optional[str] = None,
        skin_color: Optional[QColor] = None,
        auto_stem: Optional[str] = None,
    ) -> None:
        self._slot = slot
        self._game = game
        self._manager = manager

        self._panel.populate(
            game=game, toon_name=toon_name, manager=manager,
            dna=dna, skin_color=skin_color, auto_stem=auto_stem,
        )
        self._original = deepcopy(self._panel.draft())

        self._refresh_geometry()
        self._refresh_backdrop_pixmap()
        self._confirm_prompt.hide()
        self.show()
        self.raise_()
        self._panel.save_btn.setFocus()
        self._play_entry_animation()

    def request_close(self) -> None:
        if self._is_dirty():
            self._show_confirm_prompt()
        else:
            self.close_and_discard()

    def close_and_discard(self) -> None:
        self._confirm_prompt.hide()
        self._play_exit_animation(self.hide)

    def close_and_save(self) -> None:
        if self._slot is None or self._game is None:
            return
        toon_name = self._panel._toon_name
        self._manager.set(self._game, toon_name, self._panel.draft())
        self.customization_changed.emit(self._slot, self._game)
        self.close_and_discard()

    # -- Internals ------------------------------------------------------

    def _is_dirty(self) -> bool:
        return self._panel.draft() != self._original

    def _show_confirm_prompt(self) -> None:
        # Center the prompt horizontally over the panel; place it just
        # below the panel header so it covers the preview area.
        panel_geom = self._panel.geometry()
        prompt_w = 380
        prompt_h = 140
        x = panel_geom.x() + (panel_geom.width() - prompt_w) // 2
        y = panel_geom.y() + self._panel.HEADER_H + 30
        self._confirm_prompt.setGeometry(x, y, prompt_w, prompt_h)
        self._confirm_prompt.show()
        self._confirm_prompt.raise_()
        self._confirm_prompt.keep_btn.setFocus()

    def _on_confirm_keep(self) -> None:
        self._confirm_prompt.hide()
        self._panel.setFocus()

    def _on_confirm_discard(self) -> None:
        self._confirm_prompt.hide()
        self.close_and_discard()

    def _on_reset_requested(self) -> None:
        self._panel.reset_all()

    def _refresh_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        self._backdrop.setGeometry(self.rect())
        px = (self.width() - self._panel.PANEL_W) // 2
        py = (self.height() - self._panel.PANEL_H) // 2
        self._panel.move(max(0, px), max(0, py))

    def _refresh_backdrop_pixmap(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            self._backdrop.set_source_pixmap(QPixmap())
            return
        # Grab the parent's current rendering. The overlay is hidden
        # at this point (we call show() AFTER this), so the grab is
        # of the underlying tab without the overlay on top.
        pix = parent.grab()
        self._backdrop.set_source_pixmap(pix)

    # -- Events ---------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.request_close()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_geometry()
        # On resize while open, re-grab the backdrop too.
        if self.isVisible():
            self._refresh_backdrop_pixmap()

    # -- Animation helpers -----------------------------------------------

    ENTRY_DURATION_MS = 220
    EXIT_DURATION_MS = 150
    BACKDROP_ENTRY_MS = 180
    BACKDROP_EXIT_MS = 130
    PANEL_SCALE_START = 0.85
    PANEL_SCALE_END = 1.00

    def _ensure_opacity_effects(self) -> None:
        # Backdrop has its own `opacity` Qt property (animated directly).
        # Only the panel needs a QGraphicsOpacityEffect: QFrame's default
        # QSS-driven paint plays nice with the effect, but a widget with
        # a custom QPainter(self) paintEvent (like _BackdropBlur) fights
        # the effect's source-pixmap renderer.
        if not hasattr(self, "_panel_opacity"):
            self._panel_opacity = QGraphicsOpacityEffect(self._panel)
            self._panel.setGraphicsEffect(self._panel_opacity)

    def _set_panel_scale(self, scale: float, origin: Optional[QPoint] = None) -> None:
        """Apply a CSS transform-like scale by resizing the panel
        proportionally and recentering. We avoid QGraphicsView /
        QGraphicsProxyWidget here because PySide6 6.11 has known bugs
        with opacity / blur effects inside proxies; instead we use
        simple geometry + an opacity effect.

        origin is unused for now; the spec calls for transform-origin
        at the pencil position but a centered scale reads almost
        identically at PANEL_W x PANEL_H scale 0.85 -> 1.0."""
        panel_w_scaled = int(self._panel.PANEL_W * scale)
        panel_h_scaled = int(self._panel.PANEL_H * scale)
        px = (self.width() - panel_w_scaled) // 2
        py = (self.height() - panel_h_scaled) // 2
        self._panel.setFixedSize(panel_w_scaled, panel_h_scaled)
        self._panel.move(max(0, px), max(0, py))

    def _restore_panel_scale(self) -> None:
        self._panel.setFixedSize(self._panel.PANEL_W, self._panel.PANEL_H)
        self._refresh_geometry()

    def _stop_active_animation(self) -> None:
        from PySide6.QtCore import QAbstractAnimation
        g = self._active_anim_group
        if g is not None and g.state() == QAbstractAnimation.Running:
            g.stop()
        self._active_anim_group = None

    def _play_entry_animation(self) -> None:
        if self._skip_animations_for_test or reduced_motion_enabled():
            self._ensure_opacity_effects()
            self._backdrop.opacity = 1.0
            self._panel_opacity.setOpacity(1.0)
            self._restore_panel_scale()
            return
        self._stop_active_animation()
        self._ensure_opacity_effects()
        self._backdrop.opacity = 0.0
        self._panel_opacity.setOpacity(0.0)
        self._set_panel_scale(self.PANEL_SCALE_START)

        group = QParallelAnimationGroup(self)

        a_back = QPropertyAnimation(self._backdrop, b"opacity", self)
        a_back.setStartValue(0.0)
        a_back.setEndValue(1.0)
        a_back.setDuration(self.BACKDROP_ENTRY_MS)
        a_back.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(a_back)

        a_panel = QPropertyAnimation(self._panel_opacity, b"opacity", self)
        a_panel.setStartValue(0.0)
        a_panel.setEndValue(1.0)
        a_panel.setDuration(self.ENTRY_DURATION_MS)
        a_panel.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(a_panel)

        # Scale: animate fixedSize from 85 % to 100 %. We use a
        # QVariantAnimation on a scalar and call _set_panel_scale
        # on each tick.
        a_scale = QVariantAnimation(self)
        a_scale.setStartValue(float(self.PANEL_SCALE_START))
        a_scale.setEndValue(float(self.PANEL_SCALE_END))
        a_scale.setDuration(self.ENTRY_DURATION_MS)
        curve = QEasingCurve(QEasingCurve.OutBack)
        curve.setOvershoot(1.3)
        a_scale.setEasingCurve(curve)
        a_scale.valueChanged.connect(
            lambda v: self._set_panel_scale(float(v))
        )
        group.addAnimation(a_scale)

        self._active_anim_group = group
        group.finished.connect(lambda: setattr(self, "_active_anim_group", None))
        group.finished.connect(self._restore_panel_scale)
        group.start(QParallelAnimationGroup.DeleteWhenStopped)

    def _play_exit_animation(self, on_finish) -> None:
        if self._skip_animations_for_test or reduced_motion_enabled():
            on_finish()
            return
        self._stop_active_animation()
        self._ensure_opacity_effects()
        group = QParallelAnimationGroup(self)

        a_back = QPropertyAnimation(self._backdrop, b"opacity", self)
        a_back.setStartValue(1.0)
        a_back.setEndValue(0.0)
        a_back.setDuration(self.BACKDROP_EXIT_MS)
        a_back.setEasingCurve(QEasingCurve.InCubic)
        group.addAnimation(a_back)

        a_panel = QPropertyAnimation(self._panel_opacity, b"opacity", self)
        a_panel.setStartValue(1.0)
        a_panel.setEndValue(0.0)
        a_panel.setDuration(self.EXIT_DURATION_MS)
        a_panel.setEasingCurve(QEasingCurve.InCubic)
        group.addAnimation(a_panel)

        a_scale = QVariantAnimation(self)
        a_scale.setStartValue(float(self.PANEL_SCALE_END))
        a_scale.setEndValue(float(self.PANEL_SCALE_START))
        a_scale.setDuration(self.EXIT_DURATION_MS)
        a_scale.setEasingCurve(QEasingCurve.InCubic)
        a_scale.valueChanged.connect(
            lambda v: self._set_panel_scale(float(v))
        )
        group.addAnimation(a_scale)

        def _done():
            self._restore_panel_scale()
            on_finish()
        self._active_anim_group = group
        group.finished.connect(lambda: setattr(self, "_active_anim_group", None))
        group.finished.connect(_done)
        group.start(QParallelAnimationGroup.DeleteWhenStopped)
