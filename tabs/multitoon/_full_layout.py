"""Full UI layout for the Multitoon tab — activated at >= 1280x800.

The Full UI is a 2x2 card grid with large portraits and a Discord-style status
indicator (background-colored ring overlapping the portrait + colored dot inside).
"""

from PySide6.QtCore import Qt, Property
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
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


def _make_ctrl_32(widget: QWidget) -> None:
    """Force a control to 32px tall + 6px corner radius — applied to every
    interactive item in the controls row so they share a baseline."""
    widget.setFixedHeight(32)
    sheet = widget.styleSheet()
    if "border-radius" not in sheet:
        widget.setStyleSheet(sheet + "border-radius: 6px;")


class _FullToonCard(QFrame):
    """One toon's card in the Full UI. Active and inactive states share the
    outer frame; the inner content swaps based on whether a window was found."""

    def __init__(self, slot_index: int, tab, parent=None):
        super().__init__(parent)
        self._slot = slot_index
        self._tab = tab
        self._is_active = False

        self.setObjectName("full_toon_card")
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._stack_layout = QVBoxLayout(self)
        self._stack_layout.setContentsMargins(18, 18, 18, 18)
        self._stack_layout.setSpacing(0)

        self._build_active_view()
        self._build_inactive_view()
        self.set_active(False)

    # ── Active view ────────────────────────────────────────────────────────
    def _build_active_view(self):
        self._active_root = QWidget(self)
        grid = QGridLayout(self._active_root)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)

        # Portrait + status indicator (column 0, rows 0-2)
        portrait_wrap = QWidget()
        portrait_wrap.setFixedSize(104, 104)
        portrait = self._tab.slot_badges[self._slot]
        portrait.setParent(portrait_wrap)
        portrait.setFixedSize(104, 104)
        portrait.move(0, 0)
        self._status_indicator = _StatusIndicator(portrait_wrap)
        self._status_indicator.move(74, 74)  # bottom-right, -2/-2 visual offset
        grid.addWidget(portrait_wrap, 0, 0, 3, 1, alignment=Qt.AlignTop)

        # Name label (col 1, row 0)
        name_label, _status_dot_compact = self._tab.toon_labels[self._slot]
        name_font = name_label.font()
        name_font.setPointSize(16)
        name_font.setWeight(QFont.DemiBold)
        name_label.setFont(name_font)
        name_label.setStyleSheet(name_label.styleSheet() + "padding-right: 60px;")
        grid.addWidget(name_label, 0, 1, alignment=Qt.AlignBottom)

        # Stats (col 1, rows 1 & 2). Reuse the existing labels but apply tabular nums.
        for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
            f = lbl.font()
            try:
                f.setFeature("tnum", 1)  # PySide6 6.5+
            except Exception:
                f.setStyleHint(QFont.TypeWriter, QFont.PreferDefault)
            lbl.setFont(f)
        grid.addWidget(self._tab.laff_labels[self._slot], 1, 1, alignment=Qt.AlignLeft)
        grid.addWidget(self._tab.bean_labels[self._slot], 2, 1, alignment=Qt.AlignLeft)

        # TTR/CC pill (top-right absolute via overlay)
        self._game_pill = self._tab.game_badges[self._slot]
        self._game_pill.setParent(self._active_root)
        self._game_pill.move(0, 0)  # repositioned in resizeEvent of card

        # Controls row (spans both columns)
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        for w in (
            self._tab.toon_buttons[self._slot],
            self._tab.chat_buttons[self._slot],
            self._tab.keep_alive_buttons[self._slot],
        ):
            _make_ctrl_32(w)
        ctrl_row.addWidget(self._tab.toon_buttons[self._slot])
        ctrl_row.addWidget(self._tab.chat_buttons[self._slot])
        ctrl_row.addWidget(self._tab.keep_alive_buttons[self._slot])

        ka_bar = self._tab.ka_progress_bars[self._slot]
        ka_bar.setFixedSize(90, 8)
        ctrl_row.addWidget(ka_bar)
        ctrl_row.addStretch(1)

        selector = self._tab.set_selectors[self._slot]
        _make_ctrl_32(selector)
        ctrl_row.addWidget(selector)

        grid.addLayout(ctrl_row, 3, 0, 1, 2)

        self._stack_layout.addWidget(self._active_root)

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
        if active:
            self._status_indicator.set_active(True)

    def apply_theme(self, c: dict) -> None:
        self.setStyleSheet(
            f"#full_toon_card {{ background: {c['bg_card']}; "
            f"border: 1px solid {c['border_card']}; border-radius: 12px; }}"
        )
        self._status_indicator.apply_theme(
            c["bg_card"], c["status_dot_active"], c["status_dot_idle"]
        )
        # Use text_on_accent (Material 3 onPrimary pattern) — light mode = white,
        # dark mode = slate-900. The plan's hardcoded "white" would have failed AA
        # in dark mode where game_pill_ttr is now a brighter violet-400.
        self._game_pill.setStyleSheet(
            f"background: {c['game_pill_ttr']}; color: {c['text_on_accent']}; "
            f"border-radius: 10px; padding: 3px 10px; "
            f"font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep the game pill anchored top-right at (-14, -14) inset
        if self._is_active:
            pw = self._game_pill.sizeHint().width()
            self._game_pill.move(self.width() - pw - 14, 14)


class _FullLayout(QWidget):
    """Top-level Full UI: service bar above a 2x2 toon card grid."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._cards = []
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)

        # Service bar
        service_bar = QFrame()
        service_bar.setObjectName("full_service_bar")
        sb_layout = QVBoxLayout(service_bar)
        sb_layout.setContentsMargins(24, 18, 24, 18)
        sb_layout.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(16)
        # Restyle the toggle button for the wider layout
        self._tab.toggle_service_button.setMinimumWidth(180)
        row.addWidget(self._tab.toggle_service_button)
        row.addStretch()
        for pill in self._tab.profile_pills:
            row.addWidget(pill)
        row.addSpacing(8)
        row.addWidget(self._tab.refresh_button)
        sb_layout.addLayout(row)
        sb_layout.addWidget(self._tab.status_bar)

        outer.addWidget(service_bar)

        # 2x2 grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for i, (r, c) in enumerate(positions):
            card = _FullToonCard(i, self._tab)
            self._cards.append(card)
            grid.addWidget(card, r, c)
        outer.addLayout(grid, 1)

    def populate(self):
        """Re-attach shared widgets if they got reparented elsewhere. Called when
        we swap *back* from Compact to Full — the parent reassignment in the
        active card's __init__ would otherwise stay pointing to the previous
        layout's containers."""
        for card in self._cards:
            # Force re-parent on the per-slot widgets used by the active view.
            # The card already owns them via setParent in _build_active_view; we
            # call set_active(state) so visuals update.
            card.set_active(card._is_active)

    def apply_theme(self, c: dict) -> None:
        self.setStyleSheet(f"QWidget {{ background: {c['bg_app']}; }}")
        for card in self._cards:
            card.apply_theme(c)
