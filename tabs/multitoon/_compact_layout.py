"""Compact UI layout for the Multitoon tab — the layout that ships at default
window size. Below the Full UI breakpoint, the outer card clamps to 720 px and
centers horizontally so wider windows do not stretch it."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy

from tabs.multitoon._layout_utils import clear_layout


class _CompactLayout(QWidget):
    """Reproduces the default Multitoon layout. Two-phase construction:

    - `_build_structure` creates the persistent QFrame/QLayout tree.
    - `populate` (re-)adds the shared per-slot widgets into the cached slots.
    """

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        # Cached references to slot sub-layouts (populated in _build_structure)
        self._service_layout = None
        self._config_row = None
        self._card_slots = []  # list of dicts per card with sub-layout refs
        self._build_structure()
        self.populate()

    # ── Structure ──────────────────────────────────────────────────────────
    def _build_structure(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 12, 16, 12)
        outer_layout.setSpacing(0)

        outer_card = QFrame()
        outer_card.setMaximumWidth(720)
        # Expand-to-fill horizontally up to maxWidth. Combined with the
        # addStretch() pair below, this gives "fill when narrow, center
        # when wider than 720" — what the v2.0.3 layout did naturally
        # before the maxWidth clamp was introduced.
        outer_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._tab.outer_card = outer_card
        card_layout = QVBoxLayout(outer_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        # Service controls slot — empty until populate()
        self._service_layout = QVBoxLayout()
        self._service_layout.setContentsMargins(0, 0, 0, 0)
        self._service_layout.setSpacing(6)
        card_layout.addLayout(self._service_layout)

        # Section divider (no shared widgets — added directly here)
        card_layout.addSpacing(6)
        card_layout.addWidget(self._tab._section_divider, alignment=Qt.AlignHCenter)
        card_layout.addSpacing(6)

        # Config row slot — empty until populate()
        self._config_row = QHBoxLayout()
        self._config_row.setSpacing(6)
        card_layout.addLayout(self._config_row)

        # Per-slot toon cards (4 frames, each with empty sub-layouts)
        for i in range(4):
            card_layout.addWidget(self._build_card_structure(i))

        card_layout.addStretch()
        # Layout pattern: stretches with factor 1 on each side, card with
        # large factor (100). Qt distributes layout width by stretch factor
        # — card gets ~98% (100/102), each stretch ~1%. When window is
        # narrow the card fills nearly the full available width (matches
        # v2.0.3); when window > 720 the card hits its maxWidth and the
        # stretches absorb the leftover, centering the card.
        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.addStretch(1)
        center_row.addWidget(outer_card, 100)
        center_row.addStretch(1)
        outer_layout.addLayout(center_row)
        outer_layout.addStretch()

    def _build_card_structure(self, i: int) -> QFrame:
        """Build the persistent QFrame + sub-layouts for one card slot.
        Sub-layouts stay empty until populate() runs."""
        card = QFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(4)
        stats_row.setContentsMargins(0, 0, 0, 0)

        layout.addLayout(top_row)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        ka_group = QFrame()
        ka_group.setObjectName("ka_group")
        ka_group_layout = QHBoxLayout(ka_group)
        ka_group_layout.setContentsMargins(4, 4, 6, 4)
        ka_group_layout.setSpacing(4)

        layout.addLayout(ctrl_row)

        # Cache slot refs for populate()
        self._card_slots.append({
            "card": card,
            "top_row": top_row,
            "stats_row": stats_row,
            "ctrl_row": ctrl_row,
            "ka_group": ka_group,
            "ka_group_layout": ka_group_layout,
        })
        self._tab.toon_cards.append(card)
        self._tab.ka_groups.append(ka_group)
        return card

    # ── Populate ───────────────────────────────────────────────────────────
    def populate(self):
        """Clear slot layouts and re-add shared widgets in the correct order.
        Idempotent: safe to call after a layout-mode swap or theme refresh."""
        # Service controls
        clear_layout(self._service_layout)
        self._service_layout.addWidget(self._tab.toggle_service_button)
        self._service_layout.addWidget(self._tab.status_bar)

        # Config row
        clear_layout(self._config_row)
        self._config_row.addWidget(self._tab.config_label)
        self._config_row.addStretch()
        for pill in self._tab.profile_pills:
            self._config_row.addWidget(pill)
        self._config_row.addSpacing(4)
        self._config_row.addWidget(self._tab.refresh_button)

        # Each card slot
        for i, slot in enumerate(self._card_slots):
            self._populate_card(i, slot)

    def _populate_card(self, i: int, slot: dict):
        # Reset shared-widget sizes/styles that _FullLayout.populate_active
        # mutated. Restore the *original* constraints from each widget's
        # __init__, not just zero them out — Compact relies on the natural
        # size constraints to keep the cards compact.
        self._tab.set_selectors[i].setFixedHeight(28)  # Full scales dynamically; SetSelectorWidget defaults to 28

        # slot_badge: Full scales dynamically; ToonPortraitWidget's
        # constructor defaults are setMinimumSize(38, 38) + setMaximumSize(64, 64).
        # Without this reset the badge stays at 104x104 in Compact, which makes
        # the cards ~45px taller than designed.
        badge = self._tab.slot_badges[i]
        badge.setMinimumSize(38, 38)
        badge.setMaximumSize(64, 64)

        # ka_bar: Full scales dynamically; SmoothProgressBar's constructor
        # defaults are setFixedHeight(7) + setMinimumWidth(40), elastic max width.
        # Without this reset the bar fills the row's 32px height (drawing only
        # in a 7px stripe so the rest reads as transparent) AND has no minimum
        # width (so the layout can collapse it to 0 wide — invisible).
        ka_bar = self._tab.ka_progress_bars[i]
        ka_bar.setMinimumWidth(40)
        ka_bar.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
        ka_bar.setFixedHeight(7)

        # name_label: Full sets 16pt DemiBold + appends "padding-right: 60px;".
        # Reset to default font and clear the padding stanza. refresh_theme()
        # later sets its own stylesheet that determines the visible font-size.
        name_label, _ = self._tab.toon_labels[i]
        name_label.setFont(QFont())  # application default
        sheet = name_label.styleSheet()
        if "padding-right" in sheet:
            name_label.setStyleSheet(sheet.replace("padding-right: 60px;", "").strip())

        # Buttons: Full scales dynamically; constructor defaults are
        # 88×32 enable, 32×32 chat/KA.
        self._tab.toon_buttons[i].setFixedHeight(32)
        self._tab.toon_buttons[i].setFixedWidth(88)
        self._tab.chat_buttons[i].setFixedHeight(32)
        self._tab.chat_buttons[i].setFixedWidth(32)
        self._tab.keep_alive_buttons[i].setFixedHeight(32)
        self._tab.keep_alive_buttons[i].setFixedWidth(32)

        # ── existing populate logic continues below ──
        # top_row: badge | name | status_dot | game_badge | <stretch> | stats_row(laff bean)
        clear_layout(slot["top_row"])
        clear_layout(slot["stats_row"])
        slot["top_row"].addWidget(self._tab.slot_badges[i])
        name_label, status_dot = self._tab.toon_labels[i]
        slot["top_row"].addWidget(name_label)
        slot["top_row"].addWidget(status_dot)
        slot["top_row"].addWidget(self._tab.game_badges[i])
        slot["top_row"].addStretch()
        slot["stats_row"].addWidget(self._tab.laff_labels[i])
        slot["stats_row"].addWidget(self._tab.bean_labels[i])
        slot["top_row"].addLayout(slot["stats_row"])

        # ctrl_row: toon_button | ka_group(chat ka_btn ka_bar) | set_selector
        clear_layout(slot["ctrl_row"])
        clear_layout(slot["ka_group_layout"])
        slot["ctrl_row"].addWidget(self._tab.toon_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.chat_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.keep_alive_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.ka_progress_bars[i], 1)
        slot["ctrl_row"].addWidget(slot["ka_group"], 1)
        slot["ctrl_row"].addWidget(self._tab.set_selectors[i])
