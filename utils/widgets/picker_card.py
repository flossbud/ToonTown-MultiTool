"""Picker chrome: PickerChip helper, ElidedLabel, and PickerCard row widget.

PickerChip
    Namespace for chip rendering: QSS background gradient (used by
    PickerCard's chip QLabel) and inline HTML snippet (used by
    tabs/settings_tab.py's SettingsPanel._refresh_game_path_display when the
    active CC install matches).

ElidedLabel
    QLabel subclass that paints middle-elided text and exposes the full
    string as a tooltip. Used by PickerCard for the path line so long
    Bottles/Flatpak paths don't blow out the dialog width.

PickerCard
    (added in Task 3) Single-row widget composing chip + name + path + state
    (active, selected, stale). Consumed by cc_install_picker.py and
    cc_compat_picker.py.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from utils.launcher_chip import (
    LAUNCHER_CHIP_LABEL,
    chip_style_for,
)


class PickerChip:
    """Stateless namespace for chip rendering primitives."""

    @staticmethod
    def label_for(slug: str) -> str:
        """The uppercase label shown inside the chip."""
        return LAUNCHER_CHIP_LABEL.get(slug, slug.upper())

    @staticmethod
    def qss_background(slug: str) -> str:
        """QSS background-image gradient for the chip widget itself."""
        return chip_style_for(slug)

    @staticmethod
    def inline_html(slug: str, *, height_px: int = 18) -> str:
        """Render a chip as an inline HTML snippet for QLabel rich-text.

        Used by tabs/settings_tab.py's SettingsPanel._refresh_game_path_display
        when the active CC install matches a discovered one. The QLabel hosting
        the snippet must have setTextFormat(Qt.RichText).

        QLabel's rich-text subset does not support `qlineargradient(...)`
        or `linear-gradient(...)`, so the inline chip uses the gradient's
        start color as a solid background. At this small size (~18px tall)
        the gradient depth is barely perceptible anyway.
        """
        from utils.launcher_chip import LAUNCHER_CHIP_COLOR, _FALLBACK_PAIR
        start, _end = LAUNCHER_CHIP_COLOR.get(slug, _FALLBACK_PAIR)
        label = PickerChip.label_for(slug)
        return (
            f'<span style="'
            f'background-color:{start}; '
            f'color:#fff; font-weight:800; letter-spacing:0.5px; '
            f'padding:2px 6px; border-radius:5px; '
            f'font-size:10px; line-height:{height_px}px;'
            f'">{label}</span>'
        )


class ElidedLabel(QLabel):
    """QLabel that paints text elided from the middle and tooltips the full text.

    The visible elided text is recomputed on every paintEvent against the
    current widget width and font metrics, so resizing the parent dialog
    re-elides automatically.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setToolTip(text)

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self._full_text, Qt.ElideMiddle, self.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, elided)


_STRIPE_GRADIENT_DARK = ("#0077ff", "#3399ff")
_STRIPE_WIDTH_PX = 3


class PickerCard(QFrame):
    """One row in the picker dialog list.

    Layout: [chip] [name + (path|sub)] [optional pill (ACTIVE | MISSING)].
    The active-row left stripe is painted manually in paintEvent because
    Qt QSS does not support left-edge gradient borders.

    Click is consumed and re-emitted via the `clicked` signal so the parent
    dialog can update selection state. Stale cards swallow clicks entirely.
    """

    clicked = Signal()
    doubleClicked = Signal()

    def __init__(
        self,
        *,
        chip_slug: str,
        name: str,
        path: str | None = None,
        sub: str | None = None,
        active: bool = False,
        stale: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pressed: bool = False
        self._stale = stale
        self.setObjectName("picker_card")
        # Dynamic properties drive the QSS rules added in Task 4.
        self.setProperty("selected", "false")
        self.setProperty("active", "true" if active else "false")
        self.setProperty("stale", "true" if stale else "false")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(15, 13, 15, 13)
        outer.setSpacing(14)

        chip = QLabel(PickerChip.label_for(chip_slug))
        chip.setObjectName("picker_chip")
        chip.setAlignment(Qt.AlignCenter)
        chip.setMinimumWidth(64)
        chip.setFixedHeight(28)
        chip_qss = (
            f"{PickerChip.qss_background(chip_slug)} "
            f"color: #fff; font-weight: 800; letter-spacing: 0.9px; "
            f"font-size: 11px; padding: 0 10px; border-radius: 8px;"
        )
        if stale:
            # Stale chip: keep the gradient but dim the text so the row reads
            # as unavailable without removing colour cues entirely.
            chip_qss += " color: rgba(255,255,255,140);"
        chip.setStyleSheet(chip_qss)
        outer.addWidget(chip, 0)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        self._name_label = QLabel(name)
        self._name_label.setObjectName("picker_card_name")
        text_col.addWidget(self._name_label)

        self._path_label: ElidedLabel | None = None
        self._sub_label: QLabel | None = None
        if path is not None:
            self._path_label = ElidedLabel(path)
            self._path_label.setObjectName("picker_card_path")
            text_col.addWidget(self._path_label)
        elif sub is not None:
            self._sub_label = QLabel(sub)
            self._sub_label.setObjectName("picker_card_sub")
            self._sub_label.setTextFormat(Qt.RichText)
            text_col.addWidget(self._sub_label)
        outer.addLayout(text_col, 1)

        if active and not stale:
            pill = QLabel("ACTIVE")
            pill.setObjectName("picker_active_pill")
            outer.addWidget(pill, 0, Qt.AlignVCenter)
        if stale:
            pill = QLabel("MISSING")
            pill.setObjectName("picker_missing_pill")
            outer.addWidget(pill, 0, Qt.AlignVCenter)

    def set_selected(self, selected: bool) -> None:
        """Flip the dynamic property and force a QSS re-polish."""
        new = "true" if selected else "false"
        if self.property("selected") == new:
            return
        self.setProperty("selected", new)
        # Qt requires unpolish + polish to re-evaluate property-based QSS rules.
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.property("active") != "true":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(_STRIPE_GRADIENT_DARK[0]))
        grad.setColorAt(1.0, QColor(_STRIPE_GRADIENT_DARK[1]))
        painter.fillRect(0, 0, _STRIPE_WIDTH_PX, self.height(), grad)

    def mousePressEvent(self, event) -> None:
        if self._stale or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        # Defer to mouseReleaseEvent so a press-drag-off cancels activation
        # (standard button behaviour).
        self._pressed = True
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        was_pressed = getattr(self, "_pressed", False)
        self._pressed = False
        if self._stale or event.button() != Qt.LeftButton or not was_pressed:
            super().mouseReleaseEvent(event)
            return
        if self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._stale or event.button() != Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        # Qt's double-click sequence ends with a trailing Release; clear the
        # press flag so that release doesn't re-emit `clicked`.
        self._pressed = False
        self.doubleClicked.emit()
        event.accept()

    def keyPressEvent(self, event) -> None:
        if self._stale:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)
