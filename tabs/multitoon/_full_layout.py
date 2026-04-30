"""Full UI layout for the Multitoon tab — activated at >= 1280x800.

The Full UI is a 2x2 card grid with large portraits and a Discord-style status
indicator (background-colored ring overlapping the portrait + colored dot inside).
"""

import re

from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve, QRect, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
)


class _StatusIndicator(QWidget):
    """Status ring: outer ring in the card-bg color + inset filled dot.

    Z-order when overlaid on the portrait: portrait -> ring -> dot. The ring
    color must match the parent card background to create the cutout illusion.
    """

    def __init__(self, size: int = 32, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._active = False
        self._ring_color = QColor("#2a2a30")  # default = dark card-bg
        self._dot_color_active = QColor("#3aaa5e")
        self._dot_color_idle = QColor("#45454c")
        self._glow = 0.0  # 0.0..1.0, animated when active

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self.update()

    def apply_theme(self, ring_hex: str, active_hex: str, idle_hex: str) -> None:
        self._ring_color = QColor(ring_hex)
        self._dot_color_active = QColor(active_hex)
        self._dot_color_idle = QColor(idle_hex)
        self.update()

    # Animated glow property — driven by a QPropertyAnimation in a later task.
    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, v: float) -> None:
        self._glow = max(0.0, min(1.0, v))
        self.update()

    glow = Property(float, _get_glow, _set_glow)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        size = min(self.width(), self.height())
        inset = max(3, round(size * 0.125))
        dot = size - inset * 2

        # Ring fills the entire widget bounds — same color as parent card bg.
        p.setBrush(self._ring_color)
        p.drawEllipse(0, 0, size, size)

        # Dot centered inside the ring.
        dot_color = self._dot_color_active if self._active else self._dot_color_idle
        if self._active and self._glow > 0:
            # Glow halo: extra outer dot at low alpha
            halo = QColor(dot_color)
            halo.setAlphaF(0.35 * self._glow)
            p.setBrush(halo)
            p.drawEllipse(1, 1, size - 2, size - 2)
        p.setBrush(dot_color)
        p.drawEllipse(inset, inset, dot, dot)


def _style_ctrl(widget: QWidget, height: int = 32) -> None:
    """Force a control to the given height + 8px corner radius."""
    widget.setFixedHeight(height)
    sheet = widget.styleSheet()
    if "border-radius" not in sheet:
        widget.setStyleSheet(sheet + "border-radius: 8px;")


def _detach_from_layouts(widget: QWidget) -> None:
    """Remove a shared widget from any ancestor layouts before manual parenting."""
    parent = widget.parentWidget()
    while parent is not None:
        layout = parent.layout()
        if layout is not None:
            layout.removeWidget(widget)
        parent = parent.parentWidget()
    widget.setParent(None)


class _FullToonCard(QFrame):
    """One toon's card in the Full UI. Active and inactive states share the
    outer frame; the inner content swaps based on whether a window was found.

    Two-phase construction (active view): `_build_active_structure` creates the
    grid + ctrl_row shells; `populate_active` re-attaches shared widgets so we
    can rebuild after a layout-mode swap stole them.
    """

    _REF_CARD_W = 632
    _REF_CARD_H = 360
    _REF_PORTRAIT = QRect(26, 88, 168, 168)
    _REF_STATUS = QRect(132, 132, 42, 42)  # relative to portrait, may overflow it
    _REF_NAME = QRect(219, 104, 360, 54)
    _REF_LAFF = QRect(249, 158, 150, 30)
    _REF_BEANS = QRect(249, 200, 165, 30)
    _REF_ENABLE = QRect(24, 279, 118, 43)
    _REF_CHAT = QRect(151, 279, 43, 43)
    _REF_KEEPALIVE = QRect(203, 279, 43, 43)
    _REF_PROGRESS = QRect(255, 296, 150, 9)
    _REF_SELECTOR = QRect(436, 284, 174, 36)
    _REF_PILL = QRect(568, 14, 51, 23)
    _REF_NAME_FONT = 28
    _REF_STAT_FONT = 16
    _REF_BUTTON_FONT = 12
    _REF_PILL_FONT = 10

    def __init__(self, slot_index: int, tab, parent=None):
        super().__init__(parent)
        self._slot = slot_index
        self._tab = tab
        self._is_active = False
        self._pulse_anim = None
        self._scale = 1.0
        self._theme_colors = None

        self.setObjectName("full_toon_card")
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Cached refs for populate_active()
        self._portrait_wrap = None
        self._status_indicator = None
        self._game_pill = None  # set on first populate_active
        self._inactive_empty_area = None

        self._build_active_structure()
        self._build_inactive_view()
        self.populate_active()
        self.set_active(False)

    # ── Active view structure ──────────────────────────────────────────────
    def _build_active_structure(self):
        self._active_root = QWidget(self)
        self._active_root.setObjectName("full_active_root")
        self._active_root.setStyleSheet("background: transparent; border: none;")

        self._portrait_wrap = QWidget(self._active_root)
        self._portrait_wrap.setObjectName("full_portrait_wrap")
        self._portrait_wrap.setStyleSheet("background: transparent; border: none;")
        self._portrait_wrap.setGeometry(self._REF_PORTRAIT)
        self._status_indicator = _StatusIndicator(self._REF_STATUS.width(), self._active_root)
        self._status_indicator.setGeometry(self._status_rect())

    # ── Active view populate ───────────────────────────────────────────────
    def populate_active(self):
        """(Re-)attach the shared widgets into the active layout. Idempotent."""
        portrait = self._tab.slot_badges[self._slot]
        _detach_from_layouts(portrait)
        portrait.setParent(self._portrait_wrap)
        portrait.setFixedSize(self._REF_PORTRAIT.size())
        portrait.move(0, 0)
        self._status_indicator.setParent(self._active_root)
        self._status_indicator.setGeometry(self._status_rect())
        self._status_indicator.raise_()

        name_label, _status_dot_compact = self._tab.toon_labels[self._slot]
        for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
            f = lbl.font()
            try:
                f.setFeature("tnum", 1)
            except Exception:
                f.setStyleHint(QFont.TypeWriter, QFont.PreferDefault)
            lbl.setFont(f)

        for widget in (
            name_label,
            self._tab.laff_labels[self._slot],
            self._tab.bean_labels[self._slot],
        ):
            _detach_from_layouts(widget)
            widget.setParent(self._active_root)
            widget.show()

        # TTR/CC pill — parented to card frame, positioned in resizeEvent
        self._game_pill = self._tab.game_badges[self._slot]
        _detach_from_layouts(self._game_pill)
        self._game_pill.setParent(self)
        self._game_pill.move(0, 0)

        btn = self._tab.toon_buttons[self._slot]
        _style_ctrl(btn, 32)
        btn.setFixedWidth(88)
        _detach_from_layouts(btn)
        btn.setParent(self._active_root)

        chat = self._tab.chat_buttons[self._slot]
        _style_ctrl(chat, 32)
        chat.setFixedWidth(32)
        _detach_from_layouts(chat)
        chat.setParent(self._active_root)

        ka = self._tab.keep_alive_buttons[self._slot]
        _style_ctrl(ka, 32)
        ka.setFixedWidth(32)
        _detach_from_layouts(ka)
        ka.setParent(self._active_root)

        ka_bar = self._tab.ka_progress_bars[self._slot]
        ka_bar.setFixedHeight(7)
        ka_bar.setFixedWidth(self._REF_PROGRESS.width())
        ka_bar.setMinimumWidth(40)
        _detach_from_layouts(ka_bar)
        ka_bar.setParent(self._active_root)

        selector = self._tab.set_selectors[self._slot]
        _style_ctrl(selector, 28)
        selector.setFixedWidth(self._REF_SELECTOR.width())
        _detach_from_layouts(selector)
        selector.setParent(self._active_root)

        self._layout_active_content(force=True)

    # ── Inactive view ──────────────────────────────────────────────────────
    def _build_inactive_view(self):
        self._inactive_root = QWidget(self)
        self._inactive_root.setObjectName("full_inactive_root")
        self._inactive_root.setStyleSheet("background: transparent; border: none;")
        v = QVBoxLayout(self._inactive_root)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(0)

        slot_label = QLabel(f"Toon {self._slot + 1}")
        slot_label.setObjectName("full_slot_label")
        slot_font = slot_label.font()
        slot_font.setPointSize(11)
        slot_font.setWeight(QFont.DemiBold)
        slot_label.setFont(slot_font)
        v.addWidget(slot_label, alignment=Qt.AlignTop | Qt.AlignLeft)

        self._inactive_empty_area = QWidget()
        self._inactive_empty_area.setObjectName("full_empty_area")
        ev = QVBoxLayout(self._inactive_empty_area)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(6)
        ev.addStretch()
        icon = QLabel("·")
        icon.setObjectName("full_empty_icon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(32, 32)
        ev.addWidget(icon, alignment=Qt.AlignHCenter)
        msg = QLabel("No game detected")
        msg.setObjectName("full_empty_msg")
        msg.setAlignment(Qt.AlignCenter)
        ev.addWidget(msg, alignment=Qt.AlignHCenter)
        ev.addStretch()
        v.addWidget(self._inactive_empty_area, 1)

        self._inactive_root.setGeometry(self.rect())

    # ── State ──────────────────────────────────────────────────────────────
    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._active_root.setVisible(active)
        self._inactive_root.setVisible(not active)
        if self._game_pill is not None:
            self._game_pill.setVisible(active)
        if active:
            if getattr(self._tab, "_mode", "compact") == "full":
                self._scale_content()
            self._status_indicator.set_active(True)
            self._start_pulse()
        else:
            self._stop_pulse()

    def _start_pulse(self) -> None:
        if getattr(self, "_pulse_anim", None) is not None:
            return
        # Don't start pulse animations while Compact is the visible layout —
        # deactivate() will have stopped any running pulse on the mode swap, and
        # apply_all_visual_states (called from refresh_theme) must not restart it.
        if getattr(self._tab, "_mode", "full") != "full":
            return
        # Respect the user's reduced-motion / disable_animations setting
        sm = getattr(self._tab, "settings_manager", None)
        if sm and sm.get("disable_animations", False):
            return
        self._pulse_anim = QPropertyAnimation(self._status_indicator, b"glow")
        self._pulse_anim.setDuration(1500)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setKeyValueAt(0.5, 1.0)
        self._pulse_anim.setEndValue(0.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.start()

    def _stop_pulse(self) -> None:
        anim = getattr(self, "_pulse_anim", None)
        if anim is not None:
            anim.stop()
            self._pulse_anim = None
        self._status_indicator._set_glow(0.0)

    def apply_theme(self, c: dict) -> None:
        self._theme_colors = c
        self.setStyleSheet(
            f"#full_toon_card {{ background: {c['bg_card']}; "
            f"border: 1px solid {c['border_card']}; border-radius: 12px; }}"
        )
        self._status_indicator.apply_theme(
            c["bg_card"], c["status_dot_active"], c["status_dot_idle"]
        )
        self._inactive_root.setStyleSheet("background: transparent; border: none;")
        if self._inactive_empty_area is not None:
            self._inactive_empty_area.setStyleSheet(
                f"#full_empty_area {{ background: {c['bg_card']}; border: none; }}"
            )
        self._apply_game_pill_style()
        self._apply_scaled_styles()

    def _apply_game_pill_style(self) -> None:
        if self._theme_colors is None or self._game_pill is None:
            return
        c = self._theme_colors
        s = self._scale
        text = self._game_pill.text().strip().upper()
        bg = c["game_pill_cc"] if text == "CC" else c["game_pill_ttr"]
        pill_h = max(14, round(self._REF_PILL.height() * s))
        pill_w = max(30, round(self._REF_PILL.width() * s))
        radius = max(9, pill_h // 2)
        self._game_pill.setAlignment(Qt.AlignCenter)
        self._game_pill.setStyleSheet(
            f"background: {bg}; color: {c['text_on_accent']}; "
            f"border-radius: {radius}px; padding: 0px; "
            f"font-size: {max(9, round(self._REF_PILL_FONT * s))}px; "
            f"font-weight: 700; letter-spacing: 0.5px;"
        )
        self._game_pill.setFixedSize(pill_w, pill_h)
        if self._is_active:
            self._position_game_pill()

    def _position_game_pill(self) -> None:
        if self._game_pill is None:
            return
        self._game_pill.setGeometry(self._scaled_rect(self._REF_PILL))

    def resize(self, *args):
        """Override so _scale_content fires even on hidden widgets (e.g. tests)."""
        super().resize(*args)
        self._position_roots()
        if self._is_active:
            QTimer.singleShot(0, self._layout_active_content)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_roots()
        if self._is_active:
            self._layout_active_content()

    def _position_roots(self) -> None:
        rect = self.rect()
        self._active_root.setGeometry(rect)
        self._inactive_root.setGeometry(rect)

    def _scale_content(self):
        self._layout_active_content()

    def _scaled_rect(self, rect: QRect) -> QRect:
        s = self._scale
        return QRect(
            round(rect.x() * s),
            round(rect.y() * s),
            round(rect.width() * s),
            round(rect.height() * s),
        )

    def _status_rect(self) -> QRect:
        portrait_rect = self._scaled_rect(self._REF_PORTRAIT)
        status_rect = self._scaled_rect(self._REF_STATUS)
        status_rect.moveTo(
            portrait_rect.x() + status_rect.x(),
            portrait_rect.y() + status_rect.y(),
        )
        return status_rect

    def _place_fixed(self, widget: QWidget, rect: QRect) -> None:
        widget.setFixedSize(rect.size())
        widget.move(rect.topLeft())

    def _layout_active_content(self, force: bool = False):
        if getattr(self._tab, "_mode", "compact") != "full":
            if not force:
                return
        if self.width() <= 0 or self.height() <= 0:
            return
        if force and (self.width() < 200 or self.height() < 150):
            scale = 1.0
        else:
            scale = max(0.55, min(self.width() / self._REF_CARD_W, self.height() / self._REF_CARD_H))
        same_scale = abs(scale - self._scale) < 0.005
        self._scale = scale

        portrait_rect = self._scaled_rect(self._REF_PORTRAIT)
        self._place_fixed(self._portrait_wrap, portrait_rect)
        self._tab.slot_badges[self._slot].setFixedSize(portrait_rect.size())
        self._tab.slot_badges[self._slot].move(0, 0)

        status_rect = self._status_rect()
        self._place_fixed(self._status_indicator, status_rect)
        self._status_indicator.raise_()

        name_label, _ = self._tab.toon_labels[self._slot]
        name_label.setGeometry(self._scaled_rect(self._REF_NAME))
        self._tab.laff_labels[self._slot].setGeometry(self._scaled_rect(self._REF_LAFF))
        self._tab.bean_labels[self._slot].setGeometry(self._scaled_rect(self._REF_BEANS))

        self._place_fixed(self._tab.toon_buttons[self._slot], self._scaled_rect(self._REF_ENABLE))
        self._place_fixed(self._tab.chat_buttons[self._slot], self._scaled_rect(self._REF_CHAT))
        self._place_fixed(self._tab.keep_alive_buttons[self._slot], self._scaled_rect(self._REF_KEEPALIVE))
        self._place_fixed(self._tab.ka_progress_bars[self._slot], self._scaled_rect(self._REF_PROGRESS))
        self._place_fixed(self._tab.set_selectors[self._slot], self._scaled_rect(self._REF_SELECTOR))

        icon = QSize(max(10, round(14 * scale)), max(10, round(14 * scale)))
        self._tab.chat_buttons[self._slot].setIconSize(icon)
        self._tab.keep_alive_buttons[self._slot].setIconSize(icon)
        stat_icon = QSize(max(10, round(16 * scale)), max(10, round(16 * scale)))
        self._tab.laff_labels[self._slot].setIconSize(stat_icon)
        self._tab.bean_labels[self._slot].setIconSize(stat_icon)
        selector = self._tab.set_selectors[self._slot]
        if hasattr(selector, "set_paint_scale"):
            selector.set_paint_scale(scale)

        self._apply_scaled_styles()
        self._apply_game_pill_style()
        if same_scale:
            self._position_game_pill()

    def _apply_scaled_styles(self):
        if self._theme_colors is None:
            return
        c = self._theme_colors
        s = self._scale
        name_label, _ = self._tab.toon_labels[self._slot]
        name_label.setStyleSheet(
            f"font-size: {round(self._REF_NAME_FONT * s)}px; font-weight: 700; color: {c['text_primary']}; "
            f"background: transparent; border: none;"
        )
        f = name_label.font()
        f.setPixelSize(max(1, round(self._REF_NAME_FONT * s)))
        f.setWeight(QFont.Bold)
        name_label.setFont(f)
        for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
            lbl.setStyleSheet(
                f"border: none; background: transparent; font-weight: 600; "
                f"font-size: {round(self._REF_STAT_FONT * s)}px; color: {c['text_primary']}; "
                f"text-align: left;"
            )
        self._scale_button_styles()

    def _scale_button_styles(self) -> None:
        font_px = max(10, round(self._REF_BUTTON_FONT * self._scale))
        for widget in (
            self._tab.toon_buttons[self._slot],
            self._tab.chat_buttons[self._slot],
            self._tab.keep_alive_buttons[self._slot],
        ):
            sheet = widget.styleSheet()
            if not sheet:
                continue
            if "font-size" in sheet:
                sheet = re.sub(r"font-size:\s*\d+px", f"font-size: {font_px}px", sheet)
            else:
                sheet += f"\nfont-size: {font_px}px;"
            widget.setStyleSheet(sheet)


class _FullLayout(QWidget):
    """Top-level Full UI: centered controls above a 2x2 toon card grid.

    Two-phase construction:
    - `_build_structure` builds the centered controls widget with empty slot
      layouts and four `_FullToonCard` shells inside a grid container.
    - `populate` clears the control slots + each card's active view, then
      re-adds the shared widgets in correct order.
    """

    _H_SPACING = 12
    _V_SPACING = 12
    _ASPECT = 1.75  # 7:4
    _MAX_CARD_W = 1050
    _MAX_CARD_H = 600

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._cards = []
        self._ctrl_layout = None
        self._pills_row = None
        self._build_structure()
        self.populate()

    def _build_structure(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(0)

        # Centered controls block — no frame, just a widget with max-width
        controls = QWidget()
        controls.setMaximumWidth(960)
        controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._ctrl_layout = QVBoxLayout(controls)
        self._ctrl_layout.setContentsMargins(0, 0, 0, 0)
        self._ctrl_layout.setSpacing(0)

        self._pills_row = QHBoxLayout()
        self._pills_row.setSpacing(6)

        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.addStretch(1)
        center_row.addWidget(controls, 100)
        center_row.addStretch(1)
        outer.addLayout(center_row)
        outer.addSpacing(16)

        # Grid container with manually positioned config label + cards
        layout_ref = self

        class _GridContainer(QWidget):
            def resizeEvent(self, ev):
                super().resizeEvent(ev)
                layout_ref._position_cards()

        self._grid_container = _GridContainer()
        for i in range(4):
            card = _FullToonCard(i, self._tab, parent=self._grid_container)
            self._cards.append(card)
        outer.addWidget(self._grid_container, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_cards()

    def resize(self, *args):
        """Override resize() to position cards after an explicit resize() call.

        QWidget.resizeEvent is only dispatched for shown widgets; tests and other
        callers that resize a hidden _FullLayout via resize() would otherwise never
        trigger _position_cards.  A zero-delay timer fires during the next
        processEvents() call, which is exactly what the test suite does.
        """
        super().resize(*args)
        QTimer.singleShot(0, self._position_cards)

    def _position_cards(self):
        self.layout().setGeometry(QRect(0, 0, self.width(), self.height()))
        w = self._grid_container.width()
        h = self._grid_container.height()
        if w <= 0 or h <= 0:
            return

        label_h = self._tab.config_label.sizeHint().height() if self._tab.config_label.text() else 0
        label_gap = 8 if label_h > 0 else 0
        avail_h = h - label_h - label_gap
        if avail_h < self._V_SPACING + 2:
            return

        card_w = (w - self._H_SPACING) / 2
        card_h = card_w / self._ASPECT

        if card_h * 2 + self._V_SPACING > avail_h:
            card_h = (avail_h - self._V_SPACING) / 2
            card_w = card_h * self._ASPECT

        card_w = int(min(card_w, self._MAX_CARD_W))
        card_h = int(min(card_h, self._MAX_CARD_H))

        grid_w = card_w * 2 + self._H_SPACING
        grid_h = card_h * 2 + self._V_SPACING
        total_h = label_h + label_gap + grid_h
        ox = (w - grid_w) // 2
        oy = (h - total_h) // 2

        if label_h > 0:
            self._tab.config_label.setGeometry(ox, oy, grid_w, label_h)

        cards_oy = oy + label_h + label_gap
        positions = [
            (ox, cards_oy),
            (ox + card_w + self._H_SPACING, cards_oy),
            (ox, cards_oy + card_h + self._V_SPACING),
            (ox + card_w + self._H_SPACING, cards_oy + card_h + self._V_SPACING),
        ]
        for card, (x, y) in zip(self._cards, positions):
            card.setGeometry(x, y, card_w, card_h)

    def populate(self):
        """(Re-)attach shared widgets into the controls block and each card."""
        from tabs.multitoon._layout_utils import clear_layout

        # Controls block: toggle button → status bar → pills row
        clear_layout(self._ctrl_layout)
        clear_layout(self._pills_row)

        self._tab.toggle_service_button.setMinimumWidth(0)
        self._ctrl_layout.addWidget(self._tab.toggle_service_button)
        self._ctrl_layout.addSpacing(8)
        self._ctrl_layout.addWidget(self._tab.status_bar)
        self._ctrl_layout.addSpacing(12)

        self._pills_row.addStretch()
        for pill in self._tab.profile_pills:
            self._pills_row.addWidget(pill)
        self._pills_row.addSpacing(4)
        self._pills_row.addWidget(self._tab.refresh_button)
        self._pills_row.addStretch()
        self._ctrl_layout.addLayout(self._pills_row)

        # Config label — reparent into grid container, positioned manually
        self._tab.config_label.setParent(self._grid_container)
        self._tab.config_label.show()

        # Cards
        for card in self._cards:
            card.populate_active()
            card.set_active(card._is_active)

    def deactivate(self):
        """Called when the Multitoon tab is leaving Full mode. Stops all
        per-card pulse animations so they don't keep running on hidden widgets."""
        for card in self._cards:
            card._stop_pulse()

    def apply_theme(self, c: dict) -> None:
        for card in self._cards:
            card.apply_theme(c)
