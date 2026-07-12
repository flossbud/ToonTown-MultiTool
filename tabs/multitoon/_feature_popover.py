"""Feature-discovery popover: 'Extra features' panel with Click Sync and
Keep-Alive switches writing the app-wide flags (the SAME keys Settings ->
Features uses), an inline ToS confirm gating Keep-Alive, and a 'Manage
features in Settings' footer link.

A Qt.Popup top-level: click-away/Esc dismissal comes from Qt, and on X11 a
popup is override-redirect, so it stacks above the Float UI cluster without
touching the window-type matrix. Chat is deliberately NOT here: the per-card
chat toggle follows chat_handling_mode == per_toon (a 4-option Settings
control, not an on/off flag).

Colors resolve from get_theme_colors at every open so theme flips are
honored. Deviation from the bundle noted: the pop-in is a 140ms windowOpacity
fade (a top-level widget cannot cheaply scale-transform; the KA help popover
set this precedent)."""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from utils.icon_factory import make_click_sync_icon, make_lightning_icon
from utils.settings_keys import CLICK_SYNC_ENABLED
from utils.shared_widgets import Switch
from utils.theme_manager import (
    KEEP_ALIVE_ACCENT, KEEP_ALIVE_ACCENT_BORDER, V2_ACCENTS,
    get_theme_colors, get_v2_tokens, is_dark_palette, resolve_theme,
)
from utils.widgets.portrait_badge import _qcolor_from_rgba

_WIDTH = 300
_PAD = 14
_RADIUS = 12
_FADE_MS = 140
_ANCHOR_GAP = 8


def prefer_above(anchor_center_y: int, screen_center_y: int) -> bool:
    """True when the popover should open ABOVE the anchor (bottom-row cards).
    Screen-relative so it behaves identically in the framed tab and Float UI."""
    return anchor_center_y > screen_center_y


class _FeatureSwitch(Switch):
    """Controlled-mode canonical Switch: renders the checked state it is
    GIVEN and reports presses via `clicked` WITHOUT self-flipping; the
    popover owns the flip decision (needed for the ToS confirm gate).
    Reuses the canonical paint, theming, and reduced-motion handling so
    these toggles read identically to Settings -> Features, which writes
    the same flags."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()
            event.accept()
            return
        QWidget.mousePressEvent(self, event)

    def set_checked(self, checked: bool, colors: tuple, animate: bool = True) -> None:
        """Apply (track_on, border_on) colors and the visual checked state
        without emitting toggled (base setChecked emits; controlled mode
        must not)."""
        track_on, border_on = colors
        self.set_accent(str(track_on), str(border_on))
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        if animate:
            self._animate_to_state()
        else:
            target = (self.TRACK_W - self.THUMB_D - self.PADDING
                      if checked else self.PADDING)
            self._anim.stop()
            self._thumb_x = float(target)
            self.update()


class FeatureDiscoveryPopover(QWidget):
    settings_requested = Signal()

    _FEATURES = ("sync", "ka")

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._sm = settings_manager
        self._switches: dict[str, _FeatureSwitch] = {}
        self._chips: dict[str, QLabel] = {}
        self._anchor_rect: QRect | None = None
        self._above = False
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(_FADE_MS)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._build()
        self.setFixedWidth(_WIDTH)

    # -- structure -------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._panel = QFrame(self)
        self._panel.setObjectName("feature_popover_panel")
        outer.addWidget(self._panel)
        lay = QVBoxLayout(self._panel)
        lay.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        lay.setSpacing(0)

        self._title = QLabel("Extra features")
        self._title.setObjectName("fp_title")
        lay.addWidget(self._title)
        self._subtitle = QLabel("Apply to all toons. Off by default.")
        self._subtitle.setObjectName("fp_subtitle")
        lay.addWidget(self._subtitle)
        lay.addSpacing(4)

        self._row_meta = {
            "sync": dict(
                name="Click Sync",
                desc="Mirror your clicks across all toon windows. "
                     "Adds a sync toggle to each card.",
                key=CLICK_SYNC_ENABLED,
            ),
            "ka": dict(
                name="Keep-Alive",
                desc="Taps a key on idle toons so they don't disconnect. "
                     "Adds a timer bar to each card.",
                key="keep_alive_enabled",
            ),
        }
        for fkey in self._FEATURES:
            lay.addWidget(self._build_row(fkey))
            if fkey == "ka":
                self._tos_panel = self._build_tos_panel()
                lay.addWidget(self._tos_panel)
                self._tos_panel.hide()

        lay.addSpacing(10)
        self._footer_rule = QFrame()
        self._footer_rule.setObjectName("fp_footer_rule")
        self._footer_rule.setFixedHeight(1)
        lay.addWidget(self._footer_rule)
        lay.addSpacing(10)
        self._footer_btn = QPushButton("Manage features in Settings ›")
        self._footer_btn.setObjectName("fp_footer_btn")
        self._footer_btn.setCursor(Qt.PointingHandCursor)
        self._footer_btn.setFlat(True)
        self._footer_btn.clicked.connect(self._on_footer)
        lay.addWidget(self._footer_btn, 0, Qt.AlignLeft)

    def _build_row(self, fkey: str) -> QWidget:
        meta = self._row_meta[fkey]
        row = QWidget(self._panel)
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 8, 0, 8)
        h.setSpacing(10)

        chip = QLabel()
        chip.setObjectName(f"fp_chip_{fkey}")
        chip.setFixedSize(28, 28)
        chip.setAlignment(Qt.AlignCenter)
        self._chips[fkey] = chip
        h.addWidget(chip)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        name = QLabel(meta["name"])
        name.setObjectName(f"fp_name_{fkey}")
        desc = QLabel(meta["desc"])
        desc.setObjectName(f"fp_desc_{fkey}")
        desc.setWordWrap(True)
        # QLabel wordwrap + hfw layouts clip unless the wrap width is FIXED
        # (house law). 300 panel - 2*14 pad - 28 chip - 50 switch - 2*10 gaps.
        desc.setFixedWidth(_WIDTH - 2 * _PAD - 28 - 50 - 2 * 10)
        col.addWidget(name)
        col.addWidget(desc)
        h.addLayout(col, 1)

        sw = _FeatureSwitch(parent=row)
        sw.clicked.connect(lambda k=fkey: self._on_switch_clicked(k))
        self._switches[fkey] = sw
        h.addWidget(sw, 0, Qt.AlignVCenter)
        return row

    def _build_tos_panel(self) -> QFrame:
        panel = QFrame(self._panel)
        panel.setObjectName("fp_tos_panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(9)
        self._tos_label = QLabel(
            "Keep-Alive automates key presses, which is <b>against game "
            "ToS</b>. Use at your own risk.")
        self._tos_label.setObjectName("fp_tos_label")
        self._tos_label.setWordWrap(True)
        self._tos_label.setFixedWidth(_WIDTH - 2 * _PAD - 2 * 10)
        lay.addWidget(self._tos_label)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self._tos_cancel = QPushButton("Cancel")
        self._tos_cancel.setObjectName("fp_tos_cancel")
        self._tos_cancel.setCursor(Qt.PointingHandCursor)
        self._tos_cancel.clicked.connect(self._on_tos_cancel)
        self._tos_confirm = QPushButton("I understand, enable")
        self._tos_confirm.setObjectName("fp_tos_confirm")
        self._tos_confirm.setCursor(Qt.PointingHandCursor)
        self._tos_confirm.clicked.connect(self._on_tos_confirm)
        btns.addWidget(self._tos_cancel, 10)
        btns.addWidget(self._tos_confirm, 14)   # 1 : 1.4 flex per the bundle
        lay.addLayout(btns)
        return panel

    # -- behavior ---------------------------------------------------------------
    def _feature_colors(self, fkey: str) -> tuple[str, str]:
        if fkey == "ka":
            return (KEEP_ALIVE_ACCENT, KEEP_ALIVE_ACCENT_BORDER)
        return (V2_ACCENTS["pink"]["c"], V2_ACCENTS["pink"]["b"])

    def _flag(self, fkey: str) -> bool:
        meta = self._row_meta[fkey]
        return bool(self._sm and self._sm.get(meta["key"], False))

    def _on_switch_clicked(self, fkey: str) -> None:
        if self._sm is None:
            return
        meta = self._row_meta[fkey]
        if self._flag(fkey):
            # Turning OFF is always immediate.
            self._sm.set(meta["key"], False)
        elif fkey == "ka" and not self._sm.get(
                "keep_alive_consent_acknowledged", False):
            self._tos_panel.show()
            self._reposition()
            return
        else:
            self._sm.set(meta["key"], True)
        if fkey == "ka":
            self._tos_panel.hide()
            self._reposition()
        self.sync_from_settings()

    def _on_tos_confirm(self) -> None:
        # Consent BEFORE the flag: a consumer reacting to keep_alive_enabled
        # must already see consent recorded.
        self._sm.set("keep_alive_consent_acknowledged", True)
        self._sm.set("keep_alive_enabled", True)
        self._tos_panel.hide()
        self._reposition()
        self.sync_from_settings()

    def _on_tos_cancel(self) -> None:
        self._tos_panel.hide()
        self._reposition()
        self.sync_from_settings()

    def _on_footer(self) -> None:
        self.hide()
        self.settings_requested.emit()

    def sync_from_settings(self) -> None:
        for fkey in self._FEATURES:
            self._switches[fkey].set_checked(
                self._flag(fkey), self._feature_colors(fkey))

    # -- open / placement --------------------------------------------------------
    def open_at(self, anchor_global: QRect, above: bool) -> None:
        self._anchor_rect = QRect(anchor_global)
        self._above = bool(above)
        self._tos_panel.hide()
        self._apply_theme()
        for fkey in self._FEATURES:
            # Snap to state on open; animation is for in-popover flips.
            self._switches[fkey].set_checked(
                self._flag(fkey), self._feature_colors(fkey), animate=False)
        self._reposition()
        self._fade.stop()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.start()

    def showEvent(self, event):
        # A bare show() (no open_at) must still render styled and in sync.
        super().showEvent(event)
        if self._anchor_rect is None:
            self._apply_theme()
            self.sync_from_settings()

    def _reposition(self) -> None:
        if self._anchor_rect is None:
            return
        self.adjustSize()
        anchor = self._anchor_rect
        screen = QGuiApplication.screenAt(anchor.center())
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        x = anchor.center().x() - self.width() // 2
        x = max(geo.left() + 4, min(x, geo.right() - self.width() - 4))
        if self._above:
            y = anchor.top() - _ANCHOR_GAP - self.height()
        else:
            y = anchor.bottom() + _ANCHOR_GAP
        y = max(geo.top() + 4, min(y, geo.bottom() - self.height() - 4))
        self.move(x, y)

    # -- theming ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        is_dark = (resolve_theme(self._sm) == "dark") if self._sm else is_dark_palette()
        c = get_theme_colors(is_dark)
        t2 = get_v2_tokens(is_dark)

        # Off-track theming so the switch reads on light bg_card too (the
        # hand-rolled dark-native track was invisible there). set_accent for
        # the on-color happens in set_checked (open_at / sync_from_settings).
        for fkey in self._FEATURES:
            track_on, _border_on = self._feature_colors(fkey)
            self._switches[fkey].set_theme_colors(
                track_on=track_on,
                track_off=_qcolor_from_rgba(t2["sw_off"]),
                thumb="#ffffff")

        # Chips carry dark-native fills/tints; on light they must invert so
        # the fill stays subtle and the icon+border read against bg_card.
        if is_dark:
            chip_fill = "rgba(0,0,0,0.3)"
            sync_ink = V2_ACCENTS["pink"]["b"]
            ka_ink = KEEP_ALIVE_ACCENT_BORDER
        else:
            chip_fill = "rgba(0,0,0,0.06)"
            sync_ink = V2_ACCENTS["pink"]["c"]
            ka_ink = QColor(KEEP_ALIVE_ACCENT).darker(135).name()
        self._chips["sync"].setPixmap(
            make_click_sync_icon(15, QColor(sync_ink)).pixmap(15, 15))
        self._chips["ka"].setPixmap(
            make_lightning_icon(13, QColor(ka_ink)).pixmap(13, 13))
        self.setStyleSheet(f"""
            QFrame#feature_popover_panel {{
                background: {c['bg_card']};
                border: 1px solid {c['border_input']};
                border-radius: {_RADIUS}px;
            }}
            QLabel#fp_title {{
                color: {c['text_primary']}; font-size: 13px; font-weight: 800;
                background: transparent; border: none;
            }}
            QLabel#fp_subtitle {{
                color: {c['text_secondary']}; font-size: 11px;
                background: transparent; border: none;
            }}
            QLabel#fp_name_sync, QLabel#fp_name_ka {{
                color: {c['text_primary']}; font-size: 13px; font-weight: 700;
                background: transparent; border: none;
            }}
            QLabel#fp_desc_sync, QLabel#fp_desc_ka {{
                color: {c['text_secondary']}; font-size: 11px;
                background: transparent; border: none;
            }}
            QLabel#fp_chip_sync {{
                background: {chip_fill}; border: 1px solid {sync_ink};
                border-radius: 8px;
            }}
            QLabel#fp_chip_ka {{
                background: {chip_fill};
                border: 1px solid {ka_ink};
                border-radius: 8px;
            }}
            QFrame#fp_footer_rule {{
                background: {c['border_input']}; border: none;
            }}
            QPushButton#fp_footer_btn {{
                color: {c['accent_blue_btn']}; font-size: 12px; font-weight: 600;
                background: transparent; border: none; text-align: left;
                padding: 0;
            }}
            QFrame#fp_tos_panel {{
                background: {c['status_warning_bg']};
                border: 1px solid {c['status_warning_border']};
                border-radius: 9px;
            }}
            QLabel#fp_tos_label {{
                color: {c['status_warning_text']}; font-size: 12px;
                background: transparent; border: none;
            }}
            QPushButton#fp_tos_cancel {{
                background: {c['btn_bg']}; color: {c['text_secondary']};
                border: 1px solid {c['border_input']}; border-radius: 7px;
                font-size: 12px; font-weight: 600; min-height: 26px;
            }}
            QPushButton#fp_tos_confirm {{
                background: {KEEP_ALIVE_ACCENT}; color: #ffffff;
                border: 1px solid {KEEP_ALIVE_ACCENT_BORDER}; border-radius: 7px;
                font-size: 12px; font-weight: 700; min-height: 26px;
            }}
        """)
