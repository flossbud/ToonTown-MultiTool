"""Full UI layout for the Multitoon tab — activated at >= 1280x800.

The Full UI is a 2x2 card grid with large portraits and a Discord-style status
indicator (background-colored ring overlapping the portrait + colored dot inside).
"""

from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve, QRect, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
)


class _StatusIndicator(QWidget):
    """32x32 widget: a 32px ring in the card-bg color + a 24px filled dot.

    Z-order when overlaid on the portrait: portrait -> ring -> dot. The ring
    color must match the parent card background to create the cutout illusion.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
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

        # Ring fills the entire widget bounds — same color as parent card bg.
        p.setBrush(self._ring_color)
        p.drawEllipse(0, 0, 32, 32)

        # Dot — 24x24 centered, leaves a 4px ring on every side.
        dot_color = self._dot_color_active if self._active else self._dot_color_idle
        if self._active and self._glow > 0:
            # Glow halo: extra outer dot at low alpha
            halo = QColor(dot_color)
            halo.setAlphaF(0.35 * self._glow)
            p.setBrush(halo)
            p.drawEllipse(1, 1, 30, 30)
        p.setBrush(dot_color)
        p.drawEllipse(4, 4, 24, 24)


def _style_ctrl(widget: QWidget, height: int = 32) -> None:
    """Force a control to the given height + 6px corner radius."""
    widget.setFixedHeight(height)
    sheet = widget.styleSheet()
    if "border-radius" not in sheet:
        widget.setStyleSheet(sheet + "border-radius: 6px;")


class _FullToonCard(QFrame):
    """One toon's card in the Full UI. Active and inactive states share the
    outer frame; the inner content swaps based on whether a window was found.

    Two-phase construction (active view): `_build_active_structure` creates the
    grid + ctrl_row shells; `populate_active` re-attaches shared widgets so we
    can rebuild after a layout-mode swap stole them.
    """

    _REF_H = 400  # card height at which scale == 1.0

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

        self._stack_layout = QVBoxLayout(self)
        self._stack_layout.setContentsMargins(18, 18, 18, 18)
        self._stack_layout.setSpacing(0)

        # Cached refs for populate_active()
        self._info_col = None
        self._ctrl_row = None
        self._portrait_wrap = None
        self._status_indicator = None
        self._game_pill = None  # set on first populate_active

        self._build_active_structure()
        self._build_inactive_view()
        self.populate_active()
        self.set_active(False)

    # ── Active view structure ──────────────────────────────────────────────
    def _build_active_structure(self):
        self._active_root = QWidget(self)
        root_vbox = QVBoxLayout(self._active_root)
        root_vbox.setContentsMargins(0, 0, 0, 0)
        root_vbox.setSpacing(10)

        self._content_row = QHBoxLayout()
        self._content_row.setSpacing(16)

        self._portrait_wrap = QWidget()
        self._portrait_wrap.setFixedSize(130, 130)
        self._status_indicator = _StatusIndicator(self._portrait_wrap)
        self._status_indicator.move(100, 100)

        self._info_col = QVBoxLayout()
        self._info_col.setSpacing(4)

        self._content_row.addWidget(self._portrait_wrap)
        self._content_row.addLayout(self._info_col, 1)

        self._ctrl_row = QHBoxLayout()
        self._ctrl_row.setSpacing(8)

        root_vbox.addLayout(self._content_row, 1)
        root_vbox.addLayout(self._ctrl_row, 0)

        self._stack_layout.addWidget(self._active_root)

    # ── Active view populate ───────────────────────────────────────────────
    def populate_active(self):
        """(Re-)attach the shared widgets into the active layout. Idempotent."""
        from tabs.multitoon._layout_utils import clear_layout

        clear_layout(self._info_col)
        clear_layout(self._ctrl_row)

        # Portrait — fixed 130x130
        portrait = self._tab.slot_badges[self._slot]
        portrait.setParent(self._portrait_wrap)
        portrait.setFixedSize(130, 130)
        portrait.move(0, 0)
        self._status_indicator.setParent(self._portrait_wrap)
        self._status_indicator.move(100, 100)

        # Info column: vertically centered name + stats
        name_label, _status_dot_compact = self._tab.toon_labels[self._slot]
        for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
            f = lbl.font()
            try:
                f.setFeature("tnum", 1)
            except Exception:
                f.setStyleHint(QFont.TypeWriter, QFont.PreferDefault)
            lbl.setFont(f)

        self._info_col.addStretch(1)
        self._info_col.addWidget(name_label)
        self._info_col.addWidget(self._tab.laff_labels[self._slot])
        self._info_col.addWidget(self._tab.bean_labels[self._slot])
        self._info_col.addStretch(1)

        # TTR/CC pill — parented to card frame, positioned in resizeEvent
        self._game_pill = self._tab.game_badges[self._slot]
        self._game_pill.setParent(self)
        self._game_pill.move(0, 0)

        # Controls row — 40px height, proportional widths
        btn = self._tab.toon_buttons[self._slot]
        _style_ctrl(btn, 40)
        btn.setFixedWidth(100)
        self._ctrl_row.addWidget(btn)

        chat = self._tab.chat_buttons[self._slot]
        _style_ctrl(chat, 40)
        chat.setFixedWidth(40)
        self._ctrl_row.addWidget(chat)

        ka = self._tab.keep_alive_buttons[self._slot]
        _style_ctrl(ka, 40)
        ka.setFixedWidth(40)
        self._ctrl_row.addWidget(ka)

        ka_bar = self._tab.ka_progress_bars[self._slot]
        ka_bar.setFixedSize(120, 10)
        self._ctrl_row.addWidget(ka_bar)
        self._ctrl_row.addStretch(1)

        selector = self._tab.set_selectors[self._slot]
        _style_ctrl(selector, 40)
        self._ctrl_row.addWidget(selector)

    # ── Inactive view ──────────────────────────────────────────────────────
    def _build_inactive_view(self):
        self._inactive_root = QWidget(self)
        v = QVBoxLayout(self._inactive_root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        slot_label = QLabel(f"Toon {self._slot + 1}")
        slot_label.setObjectName("full_slot_label")
        slot_font = slot_label.font()
        slot_font.setPointSize(11)
        slot_font.setWeight(QFont.DemiBold)
        slot_label.setFont(slot_font)
        v.addWidget(slot_label, alignment=Qt.AlignTop | Qt.AlignLeft)

        empty_area = QWidget()
        ev = QVBoxLayout(empty_area)
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
        v.addWidget(empty_area, 1)

        self._stack_layout.addWidget(self._inactive_root)

    # ── State ──────────────────────────────────────────────────────────────
    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._active_root.setVisible(active)
        self._inactive_root.setVisible(not active)
        if self._game_pill is not None:
            self._game_pill.setVisible(active)
        if active:
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
        if self._game_pill is not None:
            self._game_pill.setStyleSheet(
                f"background: {c['game_pill_ttr']}; color: {c['text_on_accent']}; "
                f"border-radius: 10px; padding: 3px 10px; "
                f"font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
            )
        self._apply_scaled_styles()

    def resize(self, *args):
        """Override so _scale_content fires even on hidden widgets (e.g. tests)."""
        super().resize(*args)
        if self._is_active:
            QTimer.singleShot(0, self._scale_content)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._is_active:
            self._scale_content()
        if self._is_active and self._game_pill is not None:
            pw = self._game_pill.sizeHint().width()
            self._game_pill.move(self.width() - pw - 14, 14)

    def _scale_content(self):
        m = self._stack_layout.contentsMargins()
        content_h = self.height() - m.top() - m.bottom()
        if content_h <= 0:
            return
        ref_h = self._REF_H - m.top() - m.bottom()
        scale = max(0.6, min(1.5, content_h / ref_h))
        if abs(scale - self._scale) < 0.01:
            return
        self._scale = scale

        ps = int(130 * scale)
        self._portrait_wrap.setFixedSize(ps, ps)
        self._tab.slot_badges[self._slot].setFixedSize(ps, ps)
        ind_offset = ps - 30
        self._status_indicator.move(ind_offset, ind_offset)

        bh = int(40 * scale)
        self._tab.toon_buttons[self._slot].setFixedHeight(bh)
        self._tab.toon_buttons[self._slot].setFixedWidth(int(100 * scale))
        self._tab.chat_buttons[self._slot].setFixedHeight(bh)
        self._tab.chat_buttons[self._slot].setFixedWidth(bh)
        self._tab.keep_alive_buttons[self._slot].setFixedHeight(bh)
        self._tab.keep_alive_buttons[self._slot].setFixedWidth(bh)

        self._tab.ka_progress_bars[self._slot].setFixedSize(
            int(120 * scale), max(4, int(10 * scale))
        )
        self._tab.set_selectors[self._slot].setFixedHeight(bh)

        self._active_root.layout().setSpacing(int(10 * scale))
        self._content_row.setSpacing(int(16 * scale))
        self._ctrl_row.setSpacing(int(8 * scale))

        self._apply_scaled_styles()

    def _apply_scaled_styles(self):
        if self._theme_colors is None:
            return
        c = self._theme_colors
        s = self._scale
        name_label, _ = self._tab.toon_labels[self._slot]
        name_label.setStyleSheet(
            f"font-size: {int(22 * s)}px; font-weight: 600; color: {c['text_primary']}; "
            f"background: transparent; border: none; padding-right: 60px;"
        )
        f = name_label.font()
        f.setPointSize(int(22 * s))
        f.setWeight(QFont.DemiBold)
        name_label.setFont(f)
        for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
            lbl.setStyleSheet(
                f"border: none; background: transparent; font-weight: 600; "
                f"font-size: {int(15 * s)}px; color: {c['text_primary']};"
            )


class _FullLayout(QWidget):
    """Top-level Full UI: service bar above a 2x2 toon card grid.

    Two-phase construction:
    - `_build_structure` builds the service-bar QFrame with empty row/sb layouts
      and four `_FullToonCard` shells.
    - `populate` clears the service-bar slots + each card's active view, then
      re-adds the shared widgets in correct order.
    """

    _H_SPACING = 12
    _V_SPACING = 12
    _ASPECT = 1.6  # 16:10
    _MAX_CARD_W = 960
    _MAX_CARD_H = 600

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._cards = []
        self._service_row = None  # the QHBoxLayout inside service_bar
        self._service_sb_layout = None  # the QVBoxLayout that holds service_row + status_bar
        self._build_structure()
        self.populate()

    def _build_structure(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)

        # Service bar shell — empty layouts cached for populate()
        service_bar = QFrame()
        service_bar.setObjectName("full_service_bar")
        self._service_sb_layout = QVBoxLayout(service_bar)
        self._service_sb_layout.setContentsMargins(24, 18, 24, 18)
        self._service_sb_layout.setSpacing(10)

        self._service_row = QHBoxLayout()
        self._service_row.setSpacing(16)
        self._service_sb_layout.addLayout(self._service_row)

        outer.addWidget(service_bar)

        # Grid container — cards are children, positioned manually in resizeEvent.
        # Use a subclass so that when the Qt layout gives _grid_container its real
        # geometry (which may happen after _FullLayout.resizeEvent fires), the cards
        # are repositioned immediately rather than waiting for the next event cycle.
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
        # Synchronously flush the outer QVBoxLayout so _grid_container has the
        # correct geometry even when the widget is hidden (e.g. in tests where
        # resizeEvent may not fire on direct resize() calls).
        self.layout().setGeometry(QRect(0, 0, self.width(), self.height()))
        w = self._grid_container.width()
        h = self._grid_container.height()
        if w <= 0 or h <= 0:
            return

        card_w = (w - self._H_SPACING) / 2
        card_h = card_w / self._ASPECT

        if card_h * 2 + self._V_SPACING > h:
            card_h = (h - self._V_SPACING) / 2
            card_w = card_h * self._ASPECT

        card_w = int(min(card_w, self._MAX_CARD_W))
        card_h = int(min(card_h, self._MAX_CARD_H))

        grid_w = card_w * 2 + self._H_SPACING
        grid_h = card_h * 2 + self._V_SPACING
        ox = (w - grid_w) // 2
        oy = (h - grid_h) // 2

        positions = [
            (ox, oy),
            (ox + card_w + self._H_SPACING, oy),
            (ox, oy + card_h + self._V_SPACING),
            (ox + card_w + self._H_SPACING, oy + card_h + self._V_SPACING),
        ]
        for card, (x, y) in zip(self._cards, positions):
            card.setGeometry(x, y, card_w, card_h)

    def populate(self):
        """(Re-)attach shared widgets into the service bar and each card."""
        from tabs.multitoon._layout_utils import clear_layout

        # Service-bar row: toggle | <stretch> | pills | spacing | refresh
        clear_layout(self._service_row)
        # status_bar lives in the parent QVBoxLayout (self._service_sb_layout).
        # The QVBoxLayout has 2 items: [service_row (layout), status_bar (widget)].
        # Iterate from end and remove only the status_bar widget item — leave
        # service_row in place because it's our own cached row.
        for idx in range(self._service_sb_layout.count() - 1, -1, -1):
            item = self._service_sb_layout.itemAt(idx)
            w = item.widget()
            if w is self._tab.status_bar:
                self._service_sb_layout.takeAt(idx)
                w.setParent(None)

        self._tab.toggle_service_button.setMinimumWidth(180)
        self._service_row.addWidget(self._tab.toggle_service_button)
        self._service_row.addStretch()
        for pill in self._tab.profile_pills:
            self._service_row.addWidget(pill)
        self._service_row.addSpacing(8)
        self._service_row.addWidget(self._tab.refresh_button)
        self._service_sb_layout.addWidget(self._tab.status_bar)

        # Cards
        for card in self._cards:
            card.populate_active()
            # set_active forces visibility + pulse to match current state
            card.set_active(card._is_active)

    def deactivate(self):
        """Called when the Multitoon tab is leaving Full mode. Stops all
        per-card pulse animations so they don't keep running on hidden widgets."""
        for card in self._cards:
            card._stop_pulse()

    def apply_theme(self, c: dict) -> None:
        self.setStyleSheet(f"QWidget {{ background: {c['bg_app']}; }}")
        for card in self._cards:
            card.apply_theme(c)
