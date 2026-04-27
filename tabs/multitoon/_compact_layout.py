"""Compact UI layout for the Multitoon tab — the layout that ships at default
window size. Below the Full UI breakpoint, the outer card clamps to 720 px and
centers horizontally so wider windows do not stretch it."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame


class _CompactLayout(QWidget):
    """Reproduces the layout previously built inline in MultitoonTab.build_ui."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._build()

    def _build(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 12, 16, 12)
        outer_layout.setSpacing(0)

        outer_card = QFrame()
        outer_card.setMaximumWidth(720)
        self._tab.outer_card = outer_card
        card_layout = QVBoxLayout(outer_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        # Service controls
        service_layout = QVBoxLayout()
        service_layout.setContentsMargins(0, 0, 0, 0)
        service_layout.setSpacing(6)
        service_layout.addWidget(self._tab.toggle_service_button)
        service_layout.addWidget(self._tab.status_bar)
        card_layout.addLayout(service_layout)

        # Section divider
        card_layout.addSpacing(6)
        card_layout.addWidget(self._tab._section_divider, alignment=Qt.AlignHCenter)
        card_layout.addSpacing(6)

        # Config row
        config_row = QHBoxLayout()
        config_row.setSpacing(6)
        config_row.addWidget(self._tab.config_label)
        config_row.addStretch()
        for pill in self._tab.profile_pills:
            config_row.addWidget(pill)
        config_row.addSpacing(4)
        config_row.addWidget(self._tab.refresh_button)
        card_layout.addLayout(config_row)

        # Per-slot toon cards
        for i in range(4):
            card_layout.addWidget(self._build_card(i))

        card_layout.addStretch()
        outer_layout.addWidget(outer_card, alignment=Qt.AlignHCenter)
        outer_layout.addStretch()

    def _build_card(self, i: int) -> QFrame:
        card = QFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(self._tab.slot_badges[i])
        name_label, status_dot = self._tab.toon_labels[i]
        top_row.addWidget(name_label)
        top_row.addWidget(status_dot)
        top_row.addWidget(self._tab.game_badges[i])
        top_row.addStretch()

        stats_row = QHBoxLayout()
        stats_row.setSpacing(4)
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.addWidget(self._tab.laff_labels[i])
        stats_row.addWidget(self._tab.bean_labels[i])
        top_row.addLayout(stats_row)
        layout.addLayout(top_row)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        ctrl_row.addWidget(self._tab.toon_buttons[i])

        ka_group = QFrame()
        ka_group.setObjectName("ka_group")
        ka_group_layout = QHBoxLayout(ka_group)
        ka_group_layout.setContentsMargins(4, 4, 6, 4)
        ka_group_layout.setSpacing(4)
        ka_group_layout.addWidget(self._tab.chat_buttons[i])
        ka_group_layout.addWidget(self._tab.keep_alive_buttons[i])
        ka_group_layout.addWidget(self._tab.ka_progress_bars[i], 1)
        self._tab.ka_groups.append(ka_group)
        ctrl_row.addWidget(ka_group, 1)

        ctrl_row.addWidget(self._tab.set_selectors[i])
        layout.addLayout(ctrl_row)

        self._tab.toon_cards.append(card)
        return card
