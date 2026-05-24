"""Compact UI layout for the Multitoon tab - the layout that ships at default
window size. Content sits directly on the tab background and is centered
vertically within the available tab content area via leading/trailing stretches."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame

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
        outer_layout.setContentsMargins(12, 6, 12, 6)
        outer_layout.setSpacing(0)

        # Direction D drops the grouped outer card. Pieces sit directly
        # on the tab background; vertical centring is done by leading +
        # trailing stretches added in the outer_layout below.
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(8)

        # Service controls slot — empty until populate()
        self._service_layout = QVBoxLayout()
        self._service_layout.setContentsMargins(0, 0, 0, 0)
        self._service_layout.setSpacing(6)
        card_layout.addLayout(self._service_layout)

        # (Section divider removed - the status bar carries enough visual
        # weight as the separator between service controls and the
        # configuration row.)

        # Config row slot — empty until populate()
        self._config_row = QHBoxLayout()
        self._config_row.setSpacing(6)
        card_layout.addLayout(self._config_row)

        # Per-slot toon cards (4 frames, each with empty sub-layouts)
        for i in range(4):
            card_layout.addWidget(self._build_card_structure(i))

        # Vertical centring: a stretch above and below the content layout
        # gives ~equal breathing room at the default window height. With
        # ~24 px of slack in the 650 px tab content area, the content
        # block ends up ~12 px from top and ~12 px from bottom.
        outer_layout.addStretch(1)
        outer_layout.addLayout(card_layout)
        outer_layout.addStretch(1)

    def _build_card_structure(self, i: int) -> QFrame:
        """Build the persistent QFrame + sub-layouts for one card slot.
        Sub-layouts stay empty until populate() runs."""
        card = QFrame()
        card.setObjectName(f"toon_card_{i}")
        layout = QVBoxLayout(card)
        # Top padding shaved from 13 to 11 to move the header content
        # (portrait + name + stats) up 2 px. The 2 px is added back
        # below in the addSpacing above the header_divider, so divider
        # and body-row positions are unchanged.
        layout.setContentsMargins(14, 11, 14, 2)
        layout.setSpacing(0)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(4)
        stats_row.setContentsMargins(0, 0, 0, 0)

        layout.addLayout(top_row)

        # CC subtitle slot — populated in populate() with the shared
        # subtitle widget. Sits between top_row (name/badge/stats) and
        # ctrl_row (enable/chat/ka/selector). Hidden by default so
        # non-CC slots have zero visual change.
        cc_subtitle_row = QHBoxLayout()
        cc_subtitle_row.setContentsMargins(0, 0, 0, 0)
        cc_subtitle_row.setSpacing(0)
        layout.addLayout(cc_subtitle_row)

        # Hairline between the header (portrait + name + stats + CC chips)
        # and the body (Enable + chat + KA + bar + selector). Colour is
        # set in set_card_brand so theme swaps re-tint it.
        header_divider = QFrame()
        header_divider.setFrameShape(QFrame.HLine)
        header_divider.setObjectName(f"toon_card_divider_{i}")
        header_divider.setFixedHeight(1)

        # Push the header_divider (and everything below it) down. 3 px
        # of this absorbs the reduced bottom contentsMargin (5 -> 2);
        # the extra 2 px absorbs the reduced top contentsMargin
        # (13 -> 11) so the divider and body row stay in place while
        # the header content shifts up.
        layout.addSpacing(5)
        layout.addWidget(header_divider)

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
        ka_group_layout.setContentsMargins(4, 4, 4, 4)
        ka_group_layout.setSpacing(4)

        # Small breathing room between the hairline divider and the
        # body row. Paired with a 4 px reduction in the card's bottom
        # contentsMargin so total card height stays the same.
        layout.addSpacing(4)
        layout.addLayout(ctrl_row)

        # Cache slot refs for populate()
        self._card_slots.append({
            "card": card,
            "top_row": top_row,
            "stats_row": stats_row,
            "ctrl_row": ctrl_row,
            "cc_subtitle_row": cc_subtitle_row,
            "middle": middle,
            "ka_group": ka_group,
            "ka_group_layout": ka_group_layout,
            "header_divider": header_divider,
        })
        self._tab.toon_cards.append(card)
        self._tab.ka_groups.append(ka_group)

        # Status ring overlay - reuses the existing PulsingDot from
        # `toon_labels[i][1]` so it inherits the legacy pulse+glow
        # behaviour. Reparenting + positioning happens in populate()
        # / _position_status_rings(). The slot dict's "status_ring"
        # entry is left as a placeholder; populated in _populate_card.
        self._card_slots[-1]["status_ring"] = None

        return card

    def set_card_brand(self, i: int, game: str | None) -> None:
        """Apply Direction D chrome to card `i` for the given game.

        game in {"ttr", "cc", None}
            "ttr"  -> blue top stripe (game_pill_ttr)
            "cc"   -> orange top stripe (game_pill_cc)
            None   -> empty slot: muted solid stripe + solid L/R/B borders

        Reads colour tokens from get_theme_colors so light/dark palettes
        Just Work."""
        from utils.theme_manager import get_theme_colors, resolve_theme
        is_dark = resolve_theme(self._tab.settings_manager) == "dark"
        c = get_theme_colors(is_dark)
        card = self._card_slots[i]["card"]

        if game == "ttr":
            stripe = c["game_pill_ttr"]
            stripe_style = "solid"
            side_style = "solid"
            side_color = c["border_card"]
        elif game == "cc":
            stripe = c["game_pill_cc"]
            stripe_style = "solid"
            side_style = "solid"
            side_color = c["border_card"]
        else:
            # Empty slot: muted colour but solid stroke. The dashed treatment
            # added too much visual noise without enough payoff; the muted
            # colour alone is enough to signal "no toon here".
            stripe = c["border_light"]
            stripe_style = "solid"
            side_style = "solid"
            side_color = c["border_card"]

        card.setStyleSheet(
            f"#toon_card_{i} {{"
            f"  background: {c['bg_card']};"
            f"  border-top: 3px {stripe_style} {stripe};"
            f"  border-left: 1px {side_style} {side_color};"
            f"  border-right: 1px {side_style} {side_color};"
            f"  border-bottom: 1px {side_style} {side_color};"
            f"  border-radius: 9px;"
            f"}}"
        )
        divider = self._card_slots[i].get("header_divider")
        if divider is not None:
            divider.setStyleSheet(f"background: {c['border_muted']}; border: none;")

        # Refresh the portrait-overlay dot's cut-out ring so it matches
        # the current card backdrop.
        dot = self._card_slots[i].get("status_ring")
        if dot is not None and hasattr(dot, "set_cutout_border"):
            dot.set_cutout_border(c["bg_card"], width=2.5)

    # ── Populate ───────────────────────────────────────────────────────────
    def populate(self):
        """Clear slot layouts and re-add shared widgets in the correct order.
        Idempotent: safe to call after a layout-mode swap or theme refresh."""
        # Service status bar (3-state). Replaces the legacy
        # toggle_service_button + StatusBar pair.
        clear_layout(self._service_layout)
        self._service_layout.addWidget(self._tab.service_status_bar)

        # Config row. Refresh button moved into the status bar; the
        # profile-save button slot is filled in Task 5.
        clear_layout(self._config_row)
        self._config_row.addWidget(self._tab.config_label)
        self._config_row.addStretch()
        self._config_row.addWidget(self._tab.profile_pills_label)
        self._config_row.addSpacing(8)
        for pill in self._tab.profile_pills:
            self._config_row.addWidget(pill)
        self._config_row.addSpacing(6)
        self._config_row.addWidget(self._tab.profile_save_button)

        # Each card slot
        for i, slot in enumerate(self._card_slots):
            self._populate_card(i, slot)

        # Apply initial brand chrome based on each slot's currently-known
        # game (None for empty slots until the window manager assigns
        # them). The detection loop in _tab.py calls set_card_brand again
        # whenever a slot's game changes.
        for i in range(4):
            game = None
            badge = self._tab.game_badges[i] if i < len(self._tab.game_badges) else None
            if badge is not None and badge.isVisible():
                game = "cc" if badge.text() == "CC" else "ttr"
            self.set_card_brand(i, game)

        self._position_status_rings()

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

        # Direction D portrait sizing: tall-header design wants a fixed 50 px.
        badge = self._tab.slot_badges[i]
        badge.setMinimumSize(50, 50)
        badge.setMaximumSize(50, 50)

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

        # Direction D header: name uses an 11 pt (about 15 px on most DPI)
        # bold font for hierarchy against the smaller stats text.
        name_label, _ = self._tab.toon_labels[i]
        name_font = QFont()
        name_font.setPointSize(11)
        name_font.setBold(True)
        name_label.setFont(name_font)

        # Buttons: Full scales dynamically; constructor defaults are
        # 88×32 enable, 32×32 chat/KA/help, 14px icons.
        self._tab.toon_buttons[i].setFixedHeight(32)
        self._tab.toon_buttons[i].setFixedWidth(88)
        self._tab.chat_buttons[i].setFixedHeight(32)
        self._tab.chat_buttons[i].setFixedWidth(32)
        self._tab.keep_alive_buttons[i].setFixedHeight(32)
        self._tab.keep_alive_buttons[i].setFixedWidth(32)
        # Help button: prewarm/Full scales it to 43×43 with an 18px icon to
        # match the full-mode chat/KA reference size; without these resets
        # those values leak into Compact and the help button renders bigger
        # than the chat button next to it. Must come before iconSize so the
        # button has its compact bounds when the icon is re-baked.
        self._tab.help_buttons[i].setFixedHeight(32)
        self._tab.help_buttons[i].setFixedWidth(32)
        self._tab.chat_buttons[i].setIconSize(QSize(14, 14))
        self._tab.keep_alive_buttons[i].setIconSize(QSize(14, 14))
        self._tab.help_buttons[i].setIconSize(QSize(14, 14))
        self._tab.laff_labels[i].setIconSize(QSize(16, 16))
        self._tab.bean_labels[i].setIconSize(QSize(16, 16))

        # Direction D stats font: 10 pt (about 12.5 px) Medium weight to
        # balance the larger name above.
        stats_font = QFont()
        stats_font.setPointSize(10)
        stats_font.setWeight(QFont.Medium)
        self._tab.laff_labels[i].setFont(stats_font)
        self._tab.bean_labels[i].setFont(stats_font)

        # ── existing populate logic continues below ──
        # top_row: badge | name | game_badge | <stretch> | stats_row(laff bean)
        clear_layout(slot["top_row"])
        clear_layout(slot["stats_row"])
        slot["top_row"].addWidget(self._tab.slot_badges[i])
        name_label, status_dot = self._tab.toon_labels[i]
        slot["top_row"].addWidget(name_label)
        # PulsingDot is no longer added next to the name. Instead it
        # becomes the portrait status ring overlay (reparented to the
        # card; positioned in _position_status_rings()). Stash it in
        # the slot dict so the position helper can find it.
        status_dot.setParent(slot["card"])
        slot["status_ring"] = status_dot
        slot["top_row"].addWidget(self._tab.game_badges[i])
        slot["top_row"].addStretch()
        slot["stats_row"].addWidget(self._tab.laff_labels[i])
        slot["stats_row"].addWidget(self._tab.bean_labels[i])
        slot["top_row"].addLayout(slot["stats_row"])

        # CC subtitle (Compact-only enrichment). The shared widget sits
        # in a row of its own; hidden unless set_compact_cc_subtitle has
        # populated it.
        clear_layout(slot["cc_subtitle_row"])
        slot["cc_subtitle_row"].addWidget(
            self._tab._compact_cc_subtitles[i],
            alignment=Qt.AlignLeft,
        )

        # ctrl_row: toon_button | middle (ka_group + addStretch) | set_selector
        clear_layout(slot["ctrl_row"])
        clear_layout(slot["middle"])
        clear_layout(slot["ka_group_layout"])
        slot["ctrl_row"].addWidget(self._tab.toon_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.chat_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.help_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.keep_alive_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.ka_progress_bars[i], 1)
        slot["middle"].addWidget(slot["ka_group"], 1)
        slot["middle"].addStretch(1)
        slot["ctrl_row"].addLayout(slot["middle"], 1)
        slot["ctrl_row"].addWidget(self._tab.set_selectors[i])

    def _position_status_rings(self) -> None:
        """Re-position the portrait status-dot overlays after Qt has
        resolved layout. Called from showEvent / resizeEvent /
        populate()."""
        for i, slot in enumerate(self._card_slots):
            ring = slot.get("status_ring")
            if ring is None:
                continue
            badge = self._tab.slot_badges[i]
            if not badge.isVisible():
                continue
            # Convert badge bottom-right corner into card-local coords,
            # then offset so the visible dot cluster (10 px core + 2.5 px
            # cut-out ring on each side = 15 px) extends 2 px past the
            # corner, matching the design mockup's
            # `right: -2px; bottom: -2px`.
            br = badge.mapTo(slot["card"], badge.rect().bottomRight())
            ring.move(br.x() - 14, br.y() - 14)
            ring.show()
            ring.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_status_rings()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_status_rings()

    def _collapsed_ka_group_width(self, slot_index: int) -> int:
        """Width that ka_group must hold when KA is collapsed.

        ka_group's row contains chat + help + (hidden ka + hidden bar). When
        collapsed, only chat and help are visible, so the frame must be wide
        enough to fit BOTH plus inter-widget spacing plus contentsMargins.

        Each child's effective layout width is its `sizeHint().width()`
        clamped into `[minimumWidth, maximumWidth]`. Children with
        setFixedWidth/setFixedSize have min == max == fixed value, so the
        clamp pulls the sizeHint to the constrained value — matching how
        Qt itself computes the parent's natural sizeHint. Without the
        clamp, KeepAliveHelpButton (whose QToolButton sizeHint is 26 for
        an empty button while its setFixedSize forces 32) under-allocates
        and the help button is clipped on the right.
        """
        def _layout_width(w):
            sh = w.sizeHint().width()
            min_w = w.minimumWidth()
            max_w = w.maximumWidth()
            return min(max(sh, min_w), max_w)

        chat_btn = self._tab.chat_buttons[slot_index]
        help_btn = self._tab.help_buttons[slot_index]
        layout = self._card_slots[slot_index]["ka_group"].layout()
        margins = layout.contentsMargins()
        return (
            _layout_width(chat_btn)
            + _layout_width(help_btn)
            + layout.spacing()
            + margins.left()
            + margins.right()
        )

    def _set_keep_alive_collapsed(self, collapsed: bool) -> None:
        """Flip ka_group's stretch factor in each card's middle layout.
        collapsed=True  → ka_group=0, addStretch=1 (frame chat-only, spacer fills)
        collapsed=False → ka_group=1, addStretch=0 (frame fills, spacer collapsed)

        ka_group and addStretch must always be opposites — both at stretch 1
        would split the middle layout's leftover space, shrinking ka_group to
        roughly half of its pre-feature size."""
        ka_stretch = 0 if collapsed else 1
        spacer_stretch = 1 if collapsed else 0
        for slot in self._card_slots:
            middle = slot["middle"]
            # ka_group is at index 0; addStretch is at index 1.
            middle.setStretch(0, ka_stretch)
            middle.setStretch(1, spacer_stretch)
            middle.invalidate()

    def _animate_keep_alive_visibility(self, target_visible: bool) -> None:
        """Animate KA button + bar appearance/disappearance for all 4 cards.
        Compact-specific behavior: ka_group's fixed-width animates via
        QVariantAnimation between chat-only width and full row-filling width,
        with concurrent opacity fade on KA button + bar.

        Expand: 300 ms width 0→full + 250 ms opacity 0→1 (50 ms delay so
        reveal trails frame expansion).
        Collapse: 180 ms opacity 1→0 + 220 ms width full→chat (80 ms delay
        so frame stays open while widgets fade).

        Under the offscreen Qt platform plugin (used by the test suite), the
        QGraphicsOpacityEffect path crashes intermittently with an access
        violation in PySide6 6.11. The fade is purely cosmetic, so under
        offscreen we keep the width animation but skip the opacity effect
        and snap visibility instantly. Production never runs offscreen."""
        from PySide6.QtCore import (
            QVariantAnimation, QPropertyAnimation, QEasingCurve, QTimer,
        )
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        use_opacity_fx = QGuiApplication.platformName() != "offscreen"

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

            # Width ka_group needs when collapsed (chat + help visible). See
            # _collapsed_ka_group_width — formula must include the help
            # button now that v2.1.1's discovery affordance occupies the slot
            # alongside chat whenever KA is master-disabled.
            chat_only_width = self._collapsed_ka_group_width(i)

            if target_visible:
                # Expand: ka_group must claim layout space first. Spacer goes
                # to 0 so ka_group gets all of middle's leftover (otherwise
                # they'd split it 50/50 and shrink the frame).
                middle.setStretch(0, 1)
                middle.setStretch(1, 0)
                # Make widgets visible with opacity 0 so they can fade in.
                ka_btn.setVisible(True)
                ka_bar.setVisible(True)
                if use_opacity_fx:
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
                if use_opacity_fx:
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
                if use_opacity_fx:
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
                else:
                    # Headless: skip the fade and hide widgets directly so
                    # the rest of the collapse path (width animation) sees
                    # the same end-state the fade would have produced.
                    for w in (ka_btn, ka_bar):
                        w.setVisible(False)

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
                        # ka_group stretch 0, addStretch absorbs leftover.
                        mid.setStretch(0, 0)
                        mid.setStretch(1, 1)
                    return _done
                width_anim.finished.connect(
                    make_collapse_done(ka_group, middle, chat_only_width)
                )
                QTimer.singleShot(80, width_anim.start)
                self._ka_anims.append(width_anim)


