"""Compact UI layout for the Multitoon tab — the layout that ships at default
window size. Below the Full UI breakpoint, the outer card clamps to 720 px and
centers horizontally so wider windows do not stretch it."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy

from utils.theme_manager import make_heart_icon, make_jellybean_icon
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

        # Nested middle layout: ka_group | addStretch
        # The middle wrapper exists so we can flip ka_group's stretch factor
        # between 1 (master ON, fills row) and 0 (master OFF, sizes to chat
        # alone) — and have addStretch absorb the leftover when ka_group is
        # collapsed, keeping selector pinned at the right edge.
        middle = QHBoxLayout()
        middle.setSpacing(0)
        middle.setContentsMargins(0, 0, 0, 0)

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
            "middle": middle,
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
        self._tab.set_selectors[i].setMinimumWidth(130)
        self._tab.set_selectors[i].setMaximumWidth(16777215)
        if hasattr(self._tab.set_selectors[i], "set_paint_scale"):
            self._tab.set_selectors[i].set_paint_scale(1.0)

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

        self._tab.laff_labels[i].setIcon(make_heart_icon(16))
        self._tab.bean_labels[i].setIcon(make_jellybean_icon(16))

        game_badge = self._tab.game_badges[i]
        game_badge.setMinimumSize(0, 0)
        game_badge.setMaximumSize(16777215, 16777215)

        name_label, _ = self._tab.toon_labels[i]
        name_label.setFont(QFont())

        # Buttons: Full scales dynamically; constructor defaults are
        # 88×32 enable, 32×32 chat/KA.
        self._tab.toon_buttons[i].setFixedHeight(32)
        self._tab.toon_buttons[i].setFixedWidth(88)
        self._tab.chat_buttons[i].setFixedHeight(32)
        self._tab.chat_buttons[i].setFixedWidth(32)
        self._tab.keep_alive_buttons[i].setFixedHeight(32)
        self._tab.keep_alive_buttons[i].setFixedWidth(32)
        self._tab.chat_buttons[i].setIconSize(QSize(14, 14))
        self._tab.keep_alive_buttons[i].setIconSize(QSize(14, 14))
        self._tab.laff_labels[i].setIconSize(QSize(16, 16))
        self._tab.bean_labels[i].setIconSize(QSize(16, 16))

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

        # ctrl_row: toon_button | middle (ka_group + addStretch) | set_selector
        clear_layout(slot["ctrl_row"])
        clear_layout(slot["middle"])
        clear_layout(slot["ka_group_layout"])
        slot["ctrl_row"].addWidget(self._tab.toon_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.chat_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.keep_alive_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.ka_progress_bars[i], 1)
        slot["middle"].addWidget(slot["ka_group"], 1)
        slot["middle"].addStretch(1)
        slot["ctrl_row"].addLayout(slot["middle"], 1)
        slot["ctrl_row"].addWidget(self._tab.set_selectors[i])

    def _set_keep_alive_collapsed(self, collapsed: bool) -> None:
        """Flip ka_group's stretch factor in each card's middle layout.
        collapsed=True  → stretch 0 (frame sizes to chat-only natural width)
        collapsed=False → stretch 1 (frame fills the row)"""
        target_stretch = 0 if collapsed else 1
        for slot in self._card_slots:
            middle = slot["middle"]
            # ka_group is at index 0 of middle.
            middle.setStretch(0, target_stretch)
            middle.invalidate()

    def _animate_keep_alive_visibility(self, target_visible: bool) -> None:
        """Animate KA button + bar appearance/disappearance for all 4 cards.
        Compact-specific behavior: ka_group's fixed-width animates via
        QVariantAnimation between chat-only width and full row-filling width,
        with concurrent opacity fade on KA button + bar.

        Expand: 300 ms width 0→full + 250 ms opacity 0→1 (50 ms delay so
        reveal trails frame expansion).
        Collapse: 180 ms opacity 1→0 + 220 ms width full→chat (80 ms delay
        so frame stays open while widgets fade)."""
        from PySide6.QtCore import (
            QVariantAnimation, QPropertyAnimation, QEasingCurve, QTimer,
        )
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        if not hasattr(self, "_ka_anims"):
            self._ka_anims = []
        for a in self._ka_anims:
            a.stop()
        self._ka_anims = []

        QWIDGETSIZE_MAX_VAL = 16777215

        for i, slot in enumerate(self._card_slots):
            ka_group = slot["ka_group"]
            middle = slot["middle"]
            ka_btn = self._tab.keep_alive_buttons[i]
            ka_bar = self._tab.ka_progress_bars[i]

            # Compute target widths.
            chat_btn = self._tab.chat_buttons[i]
            chat_natural = chat_btn.sizeHint().width()
            ka_group_margins = ka_group.layout().contentsMargins()
            chat_only_width = (
                chat_natural
                + ka_group_margins.left()
                + ka_group_margins.right()
            )

            if target_visible:
                # Expand: ka_group must claim layout space first.
                middle.setStretch(0, 1)
                # Make widgets visible with opacity 0 so they can fade in.
                ka_btn.setVisible(True)
                ka_bar.setVisible(True)
                for w in (ka_btn, ka_bar):
                    effect = QGraphicsOpacityEffect(w)
                    effect.setOpacity(0.0)
                    w.setGraphicsEffect(effect)

                # Width animation: chat_only_width → full row width.
                # Use ka_group's current width as start (it's chat-only-sized
                # because master was off).
                width_start = ka_group.width()
                # Compute target as middle layout's available width.
                width_end = middle.geometry().width() if middle.geometry().width() > 0 else 600
                ka_group.setFixedWidth(width_start)

                width_anim = QVariantAnimation()
                width_anim.setDuration(300)
                width_anim.setStartValue(int(width_start))
                width_anim.setEndValue(int(width_end))
                width_anim.setEasingCurve(QEasingCurve.OutCubic)

                def make_width_step(group):
                    def _step(value):
                        group.setFixedWidth(int(value))
                    return _step
                width_anim.valueChanged.connect(make_width_step(ka_group))

                def make_width_done(group):
                    def _done():
                        group.setMaximumWidth(QWIDGETSIZE_MAX_VAL)
                        group.setMinimumWidth(0)
                    return _done
                width_anim.finished.connect(make_width_done(ka_group))
                width_anim.start()
                self._ka_anims.append(width_anim)

                # Opacity animations for ka_btn + ka_bar (delayed 50 ms).
                for w in (ka_btn, ka_bar):
                    effect = w.graphicsEffect()

                    op_anim = QPropertyAnimation(effect, b"opacity")
                    op_anim.setDuration(250)
                    op_anim.setEasingCurve(QEasingCurve.OutCubic)
                    op_anim.setStartValue(0.0)
                    op_anim.setEndValue(1.0)

                    def make_op_done(w_local):
                        def _done():
                            w_local.setGraphicsEffect(None)
                        return _done
                    op_anim.finished.connect(make_op_done(w))
                    QTimer.singleShot(50, op_anim.start)
                    self._ka_anims.append(op_anim)

            else:
                # Collapse: opacity fade-out first, then frame width collapses.
                for w in (ka_btn, ka_bar):
                    effect = QGraphicsOpacityEffect(w)
                    effect.setOpacity(1.0)
                    w.setGraphicsEffect(effect)

                    op_anim = QPropertyAnimation(effect, b"opacity")
                    op_anim.setDuration(180)
                    op_anim.setEasingCurve(QEasingCurve.InCubic)
                    op_anim.setStartValue(1.0)
                    op_anim.setEndValue(0.0)

                    def make_op_done(w_local):
                        def _done():
                            w_local.setVisible(False)
                            w_local.setGraphicsEffect(None)
                        return _done
                    op_anim.finished.connect(make_op_done(w))
                    op_anim.start()
                    self._ka_anims.append(op_anim)

                # Width collapse, delayed 80 ms.
                width_start = ka_group.width()
                width_anim = QVariantAnimation()
                width_anim.setDuration(220)
                width_anim.setStartValue(int(width_start))
                width_anim.setEndValue(int(chat_only_width))
                width_anim.setEasingCurve(QEasingCurve.InCubic)

                def make_width_step(group):
                    def _step(value):
                        group.setFixedWidth(int(value))
                    return _step
                width_anim.valueChanged.connect(make_width_step(ka_group))

                def make_collapse_done(group, mid, target_w):
                    def _done():
                        group.setFixedWidth(target_w)
                        mid.setStretch(0, 0)
                    return _done
                width_anim.finished.connect(
                    make_collapse_done(ka_group, middle, chat_only_width)
                )
                QTimer.singleShot(80, width_anim.start)
                self._ka_anims.append(width_anim)
