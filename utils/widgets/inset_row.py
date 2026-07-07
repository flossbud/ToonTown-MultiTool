"""InsetRow - the v2 kit's translucent inset setting row (radius 13).

API mirrors tabs/settings_tab.py's SettingsField (set_control / add_control /
set_full_width_control / control_widget) so page builders are a mechanical
port. Disabled treatment: whole-row setEnabled(False) for input + native
control greying, plus a 220ms text-alpha fade (approximates the design's
opacity 0.5 + saturate(0.45); reduce-motion snaps).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from utils.theme_manager import get_v2_tokens

DIM_MS = 220
DIM_TEXT_FACTOR = 0.5     # label/helper alpha multiplier at full dim


class InsetRow(QFrame):
    def __init__(self, label: str, helper: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("inset_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._t = get_v2_tokens(True)
        self._dim = 0.0            # 0 = enabled look, 1 = fully dimmed
        self._dim_anim = None
        self.control_widget = None
        self._controls: list = []
        self._placement = "single"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(13, 10, 13, 10)
        outer.setSpacing(9)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(14)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.label_widget = QLabel(label)
        self.label_widget.setStyleSheet("background: transparent; border: none;")
        text_col.addWidget(self.label_widget)
        if helper:
            self.helper_widget = QLabel(helper)
            self.helper_widget.setWordWrap(True)
            self.helper_widget.setMaximumWidth(470)
            self.helper_widget.setStyleSheet("background: transparent; border: none;")
            text_col.addWidget(self.helper_widget)
        else:
            self.helper_widget = None
        top_row.addLayout(text_col, 1)
        self._top_control_slot = QHBoxLayout()
        self._top_control_slot.setContentsMargins(0, 0, 0, 0)
        self._top_control_slot.setSpacing(6)
        top_row.addLayout(self._top_control_slot)
        outer.addLayout(top_row)

        self._bottom_row = QWidget(self)
        self._bottom_row.setStyleSheet("background: transparent;")
        self._bottom_control_slot = QHBoxLayout(self._bottom_row)
        self._bottom_control_slot.setContentsMargins(0, 0, 0, 0)
        self._bottom_control_slot.setSpacing(6)
        self._bottom_control_slot.addStretch(1)
        self._bottom_row.hide()
        outer.addWidget(self._bottom_row)

    # ── control placement (SettingsField-compatible) ────────────────────
    def set_control(self, widget) -> None:
        self._clear_controls()
        self._bottom_control_slot.addStretch(1)
        widget.setParent(self)
        self.control_widget = widget
        self._controls.append(widget)
        self._top_control_slot.addWidget(widget)
        self._placement = "single"

    def add_control(self, widget) -> None:
        assert self._placement != "full_width"
        widget.setParent(self)
        self._controls.append(widget)
        if self.control_widget is None:
            self.control_widget = widget
        if len(self._controls) == 1:
            self._top_control_slot.addWidget(widget)
        elif len(self._controls) == 2:
            first = self._controls[0]
            self._top_control_slot.removeWidget(first)
            first.setParent(self._bottom_row)
            self._bottom_control_slot.insertWidget(
                self._bottom_control_slot.count() - 1, first)
            widget.setParent(self._bottom_row)
            self._bottom_control_slot.insertWidget(
                self._bottom_control_slot.count() - 1, widget)
            self._bottom_row.show()
        else:
            widget.setParent(self._bottom_row)
            self._bottom_control_slot.insertWidget(
                self._bottom_control_slot.count() - 1, widget)

    def set_full_width_control(self, widget) -> None:
        self._clear_controls()
        widget.setParent(self._bottom_row)
        self.control_widget = widget
        self._controls = [widget]
        self._bottom_control_slot.addWidget(widget, 1)
        self._bottom_row.show()
        self._placement = "full_width"

    def _clear_controls(self) -> None:
        for ctrl in self._controls:
            ctrl.setParent(None)
        self._controls = []
        while self._top_control_slot.count():
            self._top_control_slot.takeAt(0)
        while self._bottom_control_slot.count():
            self._bottom_control_slot.takeAt(0)
        self._bottom_row.hide()
        self.control_widget = None

    # ── disabled treatment ──────────────────────────────────────────────
    def set_row_disabled(self, disabled: bool) -> None:
        import utils.motion as motion
        self.setEnabled(not disabled)
        target = 1.0 if disabled else 0.0
        if motion.is_reduced():
            self._dim = target
            self._style_text()
            return
        if self._dim_anim is not None:
            self._dim_anim.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(DIM_MS)
        anim.setStartValue(self._dim)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _tick(v):
            self._dim = float(v)
            self._style_text()
        anim.valueChanged.connect(_tick)
        self._dim_anim = anim
        anim.start()

    # ── theming ─────────────────────────────────────────────────────────
    def apply_theme(self, is_dark: bool) -> None:
        self._t = get_v2_tokens(is_dark)
        self.setStyleSheet(
            "QFrame#inset_row {"
            f" background: {self._t['row_bg']};"
            f" border: 1px solid {self._t['row_border']};"
            f" border-radius: {self._t['radius_row']}px;"
            " }")
        self._style_text()

    def _style_text(self) -> None:
        t = self._t
        factor = 1.0 - (1.0 - DIM_TEXT_FACTOR) * self._dim
        label_col = _scale_alpha(t["label"], factor)
        self.label_widget.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {label_col}; "
            "background: transparent; border: none;")
        if self.helper_widget is not None:
            helper_col = _scale_alpha(t["helper"], factor)
            self.helper_widget.setStyleSheet(
                f"font-size: 11px; color: {helper_col}; "
                "background: transparent; border: none;")


def _scale_alpha(qss_color: str, factor: float) -> str:
    """Scale the alpha of a '#rrggbb' or 'rgba(r, g, b, a)' color string."""
    from PySide6.QtGui import QColor
    if qss_color.startswith("#"):
        c = QColor(qss_color)
        a = 255
    else:
        parts = qss_color[qss_color.index("(") + 1:qss_color.rindex(")")].split(",")
        r, g, b, a = (int(float(x.strip())) for x in parts)
        c = QColor(r, g, b)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {round(a * factor)})"
