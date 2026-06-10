"""Full UI layout for the Multitoon tab — a structural clone of the
compact layout with cards arranged in a 2x2 grid instead of a single
column. Each card is pinned at compact's _LOCKED_CONTENT_WIDTH so
cards do not scale with the window in full mode (the wider window
just gives the grid more breathing room).

Future incremental changes to full-mode cards will diverge from
compact here, but until then this file deliberately mirrors
_compact_layout.py."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QEvent, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QTransform
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
    QGraphicsView, QGraphicsScene, QGraphicsProxyWidget
)

from utils.theme_manager import make_heart_icon, make_jellybean_icon
from tabs.multitoon._layout_utils import clear_layout
from tabs.multitoon._compact_layout import (
    _LOCKED_CONTENT_WIDTH,
    _muted_brand,
    _CardStripe,
)


# Full-mode card height. Replaces the prior `int(natural * 1.5)`
# rule once the placeholder grew (which would make natural * 1.5
# balloon past 270). Derived from: 13 (margins) + 120 (placeholder/
# top_row) + 6 (spacing) + 2 (divider) + 2 (spacing) + 40 (ctrl_row) +
# 2 (bottom margin) = 185, plus 5 px of breathing room absorbed by
# the leading stretch. The visible 130-px portrait overlay is bigger
# than the 120 placeholder; _position_portraits places it manually
# centered between the stripe bottom and the divider top, so the
# overflow rides into the existing stretch + spacing budget without
# growing the card.
_FULL_CARD_HEIGHT = 190


def _blend_hex(fg_hex: str, bg_hex: str, alpha: float) -> str:
    """Pre-blend `fg_hex` over `bg_hex` at the given alpha and return
    the resulting solid color as #rrggbb. Used for the header divider
    in full mode, where QGraphicsOpacityEffect (compact's mechanism)
    renders the widget invisible inside the QGraphicsView proxy in
    PySide6 6.11. Painting the divider in the pre-blended solid color
    looks identical to a 45 % effect over the same card body but
    avoids alpha compositing entirely."""
    fh = fg_hex.lstrip("#")
    bh = bg_hex.lstrip("#")
    fr, fg, fb = int(fh[0:2], 16), int(fh[2:4], 16), int(fh[4:6], 16)
    br, bg_, bb = int(bh[0:2], 16), int(bh[2:4], 16), int(bh[4:6], 16)
    r = int(round(fr * alpha + br * (1 - alpha)))
    g = int(round(fg * alpha + bg_ * (1 - alpha)))
    b = int(round(fb * alpha + bb * (1 - alpha)))
    return f"#{r:02x}{g:02x}{b:02x}"


class _FullContent(QWidget):
    """Inner content widget for full mode. Reproduces the compact card layout with cards in a 2x2 grid; lives inside a _FullLayout QGraphicsView wrapper that scales the rendered output 1.125x.

    Public API mirrors _CompactLayout so prewarm_full_layout and the
    mode-switch hook in _tab.py don't need to know which class they
    are talking to:

      - populate()
      - apply_theme(c)
      - deactivate()
      - set_card_brand(i, game, enabled)
      - _animate_keep_alive_visibility(target_visible)
      - _position_portraits / _position_status_rings / _position_stripes
      - _position_cards (compatibility shim for prewarm_full_layout)
      - _set_keep_alive_collapsed(collapsed)
    """

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._service_layout = None
        self._config_row = None
        self._card_slots = []
        self._card_grid = None
        self._ka_anims = []
        # Cold-start machinery lives only in compact; full populates after
        # compact has already been visible. _cold_start_in_progress stays
        # False so set_card_brand never gates the stripe.
        self._cold_start_in_progress = False
        self._build_structure()
        self.populate()

    # ── Structure ──────────────────────────────────────────────────────────
    def _build_structure(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(12, 6, 12, 6)
        outer_layout.setSpacing(0)

        # Top controls live in a 551 px centered wrapper, identical to
        # compact. Cards sit in a separate centered grid block below
        # with its own (wider) intrinsic width.
        controls = QWidget()
        controls.setFixedWidth(_LOCKED_CONTENT_WIDTH)
        ctrl_v = QVBoxLayout(controls)
        ctrl_v.setContentsMargins(0, 0, 0, 0)
        ctrl_v.setSpacing(8)

        self._service_layout = QVBoxLayout()
        self._service_layout.setContentsMargins(0, 0, 0, 0)
        self._service_layout.setSpacing(6)
        ctrl_v.addLayout(self._service_layout)

        self._config_row = QHBoxLayout()
        self._config_row.setSpacing(6)
        ctrl_v.addLayout(self._config_row)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.addStretch(1)
        controls_row.addWidget(controls)
        controls_row.addStretch(1)

        # Cards in a 2x2 grid, centered horizontally as their own block.
        grid_host = QWidget()
        self._card_grid = QGridLayout(grid_host)
        self._card_grid.setContentsMargins(0, 0, 0, 0)
        self._card_grid.setHorizontalSpacing(8)
        self._card_grid.setVerticalSpacing(8)
        for i in range(4):
            card = self._build_card_structure(i)
            row, col = divmod(i, 2)
            self._card_grid.addWidget(card, row, col)

        grid_row = QHBoxLayout()
        grid_row.setContentsMargins(0, 0, 0, 0)
        grid_row.addStretch(1)
        grid_row.addWidget(grid_host)
        grid_row.addStretch(1)

        # Vertical anchoring: trailing stretch only, so controls + grid
        # hug the top of the tab content area regardless of how tall the
        # window grows. Matches compact's anchoring.
        outer_layout.addLayout(controls_row)
        outer_layout.addSpacing(12)
        outer_layout.addLayout(grid_row)
        outer_layout.addStretch(1)

    def _build_card_structure(self, i: int) -> QFrame:
        """Build the persistent QFrame + sub-layouts for one card slot.
        Sub-layouts stay empty until populate() runs."""
        card = QFrame()
        card.setObjectName(f"toon_card_{i}")
        # Full-mode difference vs compact: pin each card at compact's
        # locked content width so the 2x2 grid shows 551 px cards
        # regardless of how wide the full-mode wrapper grows.
        card.setFixedWidth(_LOCKED_CONTENT_WIDTH)
        layout = QVBoxLayout(card)
        # Top padding shaved from 13 to 11 to move the header content
        # (portrait + name + stats) up 2 px. The 2 px is added back
        # below in the addSpacing above the header_divider, so divider
        # and body-row positions are unchanged.
        layout.setContentsMargins(14, 11, 14, 2)
        layout.setSpacing(0)

        # Full-mode card is 50 % taller than its natural content height
        # (set per-card in populate() via setFixedHeight). This leading
        # stretch absorbs the extra space so the content stays anchored
        # to the bottom edge of the card.
        layout.addStretch(1)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Vertical meta column: name on top, stats/CC-subtitle sub-line
        # underneath. Stretches inside top_row so the mode chip lands
        # flush against the right edge.
        meta_col = QVBoxLayout()
        meta_col.setContentsMargins(0, 0, 0, 0)
        meta_col.setSpacing(0)

        # Sub-line that hosts laff/bean (TTR) and cc_subtitle (CC) - the
        # existing per-widget show/hide logic in _tab.py drives which one
        # is visible per mode. We host all three here so neither mode
        # needs structural changes when toggling.
        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(0, 0, 0, 0)
        sub_row.setSpacing(8)

        layout.addLayout(top_row)

        # Hairline between the header (portrait + name + stats + CC chips)
        # and the body (Enable + chat + KA + bar + selector). Colour is
        # set in set_card_brand so theme swaps re-tint it.
        header_divider = QFrame()
        # NoFrame (not HLine) so the widget paints purely as its QSS
        # background. QFrame.HLine ignores the QSS background and draws
        # its line via palette colors instead - which kept the divider
        # reading as default gray even when set_card_brand set the
        # background to the body-derived darkened color.
        header_divider.setFrameShape(QFrame.NoFrame)
        header_divider.setObjectName(f"toon_card_divider_{i}")
        # 2 px so the body-derived color in set_card_brand actually reads
        # against the card body. addSpacing above (line ~158) trimmed
        # from 7 to 6 to keep total card height pixel-identical.
        header_divider.setFixedHeight(2)
        # 45% opacity look is achieved in set_card_brand by pre-blending
        # the border color over the card body and painting the divider
        # in that solid blend (set_card_brand picks the right card-body
        # color for the blend). We do NOT use QGraphicsOpacityEffect
        # here: inside the QGraphicsView proxy wrapper that hosts this
        # widget, QGraphicsOpacityEffect renders the widget entirely
        # invisible in PySide6 6.11 (same bug as _set_widget_opacity
        # guards against in _tab.py). The pre-blended-color approach
        # avoids alpha compositing entirely, so it renders correctly
        # both inside and outside the proxy.

        # Push the header_divider (and everything below it) down. 3 px
        # of this absorbs the reduced bottom contentsMargin (5 -> 2);
        # the extra 2 px absorbs the reduced top contentsMargin
        # (13 -> 11) so the divider and body row stay in place while
        # the header content shifts up. +2 px (5 -> 7) drops the divider
        # 2 px lower; paired with the addSpacing(4 -> 2) below the
        # divider, the body row keeps its position and card height is
        # unchanged.
        # 6 px (was 7) to absorb the divider growing from 1 to 2 px so
        # total card height is unchanged.
        layout.addSpacing(6)
        layout.addWidget(header_divider)

        # 5 px animated top stripe. Position is set in _position_stripes().
        card_stripe = _CardStripe(card)
        card_stripe.hide()  # shown after the first position pass

        # Portrait placeholder: reserves the original 50x50 layout slot in
        # top_row so the row's geometry stays put while the real
        # ToonPortraitWidget renders larger (64x64) as a free-floating
        # overlay positioned manually in _position_portraits().
        # The transparent QSS overrides main.py's container-level
        # `QWidget { background: bg_app }` rule - without it the
        # placeholder paints in bg_app and shows through the badge's
        # transparent corners as darker squares.
        portrait_placeholder = QWidget()
        # Full-mode divergence vs compact: placeholder reserves 120x120
        # in the layout. The visible badge overlay is 130 (set in
        # _populate_card); it overflows past the placeholder bounds
        # by 5 px on each side, riding into the existing layout
        # spacing budget. Compact's placeholder is still 50x50.
        portrait_placeholder.setFixedSize(120, 120)
        portrait_placeholder.setStyleSheet("background: transparent;")

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
        # contentsMargin so total card height stays the same. Trimmed
        # from 4 -> 2 to compensate for the +2 px above the divider
        # (keeps body row position + card height unchanged).
        layout.addSpacing(2)
        layout.addLayout(ctrl_row)

        # Cache slot refs for populate()
        self._card_slots.append({
            "card": card,
            "top_row": top_row,
            "meta_col": meta_col,
            "sub_row": sub_row,
            "ctrl_row": ctrl_row,
            "middle": middle,
            "ka_group": ka_group,
            "ka_group_layout": ka_group_layout,
            "header_divider": header_divider,
            "card_stripe": card_stripe,
            "portrait_placeholder": portrait_placeholder,
        })
        # Full mode does NOT append to self._tab.toon_cards / ka_groups —
        # those lists are owned by compact and are iterated by code in
        # _tab.py (refresh_theme's per-card stylesheet pass, the
        # set_card_brand rebrand loop) that must not double-process the
        # parallel full-mode frames. Full's per-card chrome is driven
        # through self._card_slots directly.

        # Status ring overlay - reuses the existing PulsingDot from
        # `toon_labels[i][1]` so it inherits the legacy pulse+glow
        # behaviour. Reparenting + positioning happens in populate()
        # / _position_status_rings(). The slot dict's "status_ring"
        # entry is left as a placeholder; populated in _populate_card.
        self._card_slots[-1]["status_ring"] = None

        return card

    def set_card_brand(self, i: int, game: str | None, enabled: bool = False) -> None:
        """Apply Direction D chrome to card `i`.

        Stripe colour is driven by (game, enabled):
            empty (game is None)            -> border_light  (rank 0)
            found (game set, enabled False) -> _muted_brand  (rank 1)
            enabled (game set, enabled True)-> full brand    (rank 2)

        Card chrome QSS no longer writes a `border-top` - the painted
        _CardStripe widget owns that 5 px region. We reserve the space
        with `border-top: 5px solid transparent` so the card's interior
        layout stays at its current dimensions.
        """
        from utils.theme_manager import get_theme_colors, resolve_theme
        is_dark = resolve_theme(self._tab.settings_manager) == "dark"
        c = get_theme_colors(is_dark)
        card = self._card_slots[i]["card"]
        stripe = self._card_slots[i]["card_stripe"]

        from utils.toon_customization_resolve import resolve_accent
        toon_name = self._tab.toon_names[i] if i < len(self._tab.toon_names) else None
        entry: dict = {}
        if game in ("cc", "ttr") and toon_name and self._tab.customizations is not None:
            entry = self._tab.customizations.get(game, toon_name)

        if game == "ttr":
            brand = QColor(c["game_pill_ttr"])
            brand = resolve_accent(entry, brand)
            target = brand if enabled else _muted_brand(brand)
            side_style = "solid"
            side_color = c["border_card"]
        elif game == "cc":
            brand = QColor(c["game_pill_cc"])
            brand = resolve_accent(entry, brand)
            target = brand if enabled else _muted_brand(brand)
            side_style = "solid"
            side_color = c["border_card"]
        else:
            target = QColor(c["border_light"])
            side_style = "solid"
            side_color = c["border_card"]

        card.setStyleSheet(
            f"#toon_card_{i} {{"
            f"  background: {c['bg_card']};"
            f"  border-top: 5px solid transparent;"
            f"  border-left: 1px {side_style} {side_color};"
            f"  border-right: 1px {side_style} {side_color};"
            f"  border-bottom: 1px {side_style} {side_color};"
            f"  border-radius: 9px;"
            f"}}"
        )

        # Drive the animated stripe. Held back during the cold-start
        # window so all four stripes can animate together when the
        # deferred brand pass fires (otherwise early game-detection
        # would race ahead and complete the fill before the 1 s delay
        # had even elapsed).
        if not self._cold_start_in_progress:
            stripe.set_color(target)

        # Resolve any user-picked body color once; the border (divider +
        # ka_group) and the tint widget both consume it.
        from utils.toon_customization_resolve import resolve_body
        from utils.widgets.card_body_tint import CardBodyTint
        from utils.color_math import darken_hsl
        body_color = None
        if game in ("cc", "ttr") and toon_name and self._tab.customizations is not None:
            body_color = resolve_body(entry)

        # Body-derived chrome for the controls region. When the user picks
        # a body color, three things follow it so the wrapper reads as
        # unambiguously body-tinted (not "still grey same as idle"):
        #   - Wrapper interior (ka_group bg): darken_hsl(body, 0.65) — a
        #     visibly-tinted recessed shade, lighter than the border.
        #   - Wrapper border (divider + ka_group outline): darken_hsl(
        #     body, 0.4) — deep enough to define the wrapper's edge
        #     against the interior and against the surrounding body.
        #   - Progress bar track: matches border for cohesion.
        # When body is None, all three fall back to today's theme colors.
        if body_color is not None:
            border_color = darken_hsl(body_color, 0.4).name()
            wrapper_bg = darken_hsl(body_color, 0.65).name()
        else:
            border_color = c["border_muted"]
            wrapper_bg = c["bg_input"]

        # Refresh the portrait-overlay dot's cut-out ring so it tracks
        # the card body. When the user picks a body color, the dot must
        # match it to preserve the cutout illusion; otherwise it follows
        # the theme card backdrop. Lives after body_color is resolved
        # so re-brand triggers (theme refresh, body change, body clear)
        # all flow through one resolution path.
        dot = self._card_slots[i].get("status_ring")
        if dot is not None and hasattr(dot, "set_cutout_border"):
            ring_color = body_color.name() if body_color is not None else c["bg_card"]
            dot.set_cutout_border(ring_color, width=2.5)

        divider = self._card_slots[i].get("header_divider")
        if divider is not None:
            # Pre-blend the border color at 45 % over the card body to
            # simulate QGraphicsOpacityEffect(0.45) without the effect —
            # the effect renders invisible inside the QGraphicsView
            # proxy in PySide6 6.11. Card body behind the divider is
            # the body color when set (full opacity via CardBodyTint),
            # else the theme bg_card.
            card_bg_hex = body_color.name() if body_color is not None else c["bg_card"]
            divider_color = _blend_hex(border_color, card_bg_hex, 0.45)
            divider.setStyleSheet(
                f"background: {divider_color}; border: none;"
            )
        # Use this slot's ka_group directly. Full owns its own QFrame
        # tree separately from compact: self._tab.ka_groups holds only
        # compact's frames (see the architectural note in
        # _build_card_structure). Pulling from slot["ka_group"] keeps
        # the two layouts' chrome independent.
        ka_group = self._card_slots[i].get("ka_group")
        if ka_group is not None:
            ka_group.setStyleSheet(
                f"QFrame#ka_group {{"
                f"  background: {wrapper_bg};"
                f"  border: 2px solid {border_color};"
                f"  border-radius: 8px;"
                f"}}"
            )
        # Progress bar track inside the wrapper. Currently theme grey
        # regardless of body, which is what dominates the user's
        # perception of "the wrapper" (it is the largest grey surface
        # inside the rounded rect). Follow the body-derived border_color
        # so the whole wrapper reads as one coherent body-tinted unit.
        if i < len(self._tab.ka_progress_bars):
            ka_bar = self._tab.ka_progress_bars[i]
            if hasattr(ka_bar, "set_bg_color"):
                ka_bar.set_bg_color(border_color)

        # Body tint widget (lazy; only created when an override is present).
        slot = self._card_slots[i]
        tint = slot.get("body_tint")
        if body_color is None:
            if tint is not None:
                tint.hide()
            return
        if tint is None:
            tint = CardBodyTint(body_color, parent=card)
            slot["body_tint"] = tint
            # Cover the card body, starting flush against the bottom
            # edge of the 5 px stripe so no bg_card row shows between
            # the accent stripe and the body color.
            card_w = card.width()
            card_h = card.height()
            tint.setGeometry(1, 5, card_w - 2, card_h - 6)
            tint.lower()
        tint.set_color(body_color)
        tint.show()

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

        # Full-mode card height: 50 % taller than the natural content
        # sizeHint. The actual measurement + setFixedHeight is deferred
        # via QTimer.singleShot(0, ...) so Qt has processed the layout
        # from _populate_card before sizeHint is read. Running it
        # synchronously here returns a too-small sizeHint (Qt hasn't
        # activated the layout yet) and clips the card content.
        QTimer.singleShot(0, self._apply_full_card_heights)

        # Seed each card stripe to the theme's empty colour BEFORE the
        # initial brand pass. Two purposes: (1) the stripes paint
        # immediately so the cards are not visually empty during the
        # brief gap before the brand pass; (2) the brand pass then sees
        # a valid current colour and animates the transition properly
        # (without this seed, _CardStripe.set_color short-circuits its
        # first call).
        from utils.theme_manager import get_theme_colors, resolve_theme
        is_dark = resolve_theme(self._tab.settings_manager) == "dark"
        c = get_theme_colors(is_dark)
        empty_color = QColor(c["border_light"])
        for slot in self._card_slots:
            stripe = slot.get("card_stripe")
            if stripe is not None:
                stripe.set_color(empty_color)

        self._position_portraits()
        self._position_status_rings()
        self._position_stripes()

        # Full mode populates after compact has already been visible, so
        # there's no cold-start window to wait through. Apply initial
        # brand chrome immediately.
        self._apply_initial_brands()

    def _apply_initial_brands(self) -> None:
        """Run the initial set_card_brand pass over all 4 slots. Reads
        each slot's currently-known game from its game_badge. The
        detection loop in _tab.py keeps calling set_card_brand again
        whenever a slot's game changes."""
        for i in range(4):
            game = None
            badge = self._tab.game_badges[i] if i < len(self._tab.game_badges) else None
            if badge is not None and badge.isVisible():
                game = "cc" if badge.text() == "CC" else "ttr"
            self.set_card_brand(i, game)

    def _populate_card(self, i: int, slot: dict):
        # Reset shared-widget sizes/styles that other layouts may have
        # mutated. Restore the *original* constraints from each widget's
        # __init__ so the cards stay at their compact-clone reference
        # sizing.
        self._tab.set_selectors[i].setFixedHeight(28)
        self._tab.set_selectors[i].setMinimumWidth(130)
        self._tab.set_selectors[i].setMaximumWidth(16777215)
        if hasattr(self._tab.set_selectors[i], "set_paint_scale"):
            self._tab.set_selectors[i].set_paint_scale(1.0)

        # Direction D portrait sizing: the visible portrait renders at 64x64
        # as a free-floating overlay (reparented to the card, positioned in
        # _position_portraits). The layout reserves a 50x50 placeholder so
        # card height/row spacing stay unchanged; the extra size extends into
        # the card's top and left padding via the offset in _position_portraits.
        badge = self._tab.slot_badges[i]
        # Full-mode badge is 130x130 (compact uses 64x64). Pinned via
        # both min and max because slot_badges is a shared widget; the
        # compact populate_card resets it back to 64x64 on the next
        # mode swap.
        badge.setMinimumSize(130, 130)
        badge.setMaximumSize(130, 130)
        badge.setParent(slot["card"])

        # ka_bar: SmoothProgressBar's constructor defaults are
        # setFixedHeight(7) + setMinimumWidth(40), elastic max width.
        ka_bar = self._tab.ka_progress_bars[i]
        ka_bar.setMinimumWidth(40)
        ka_bar.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
        ka_bar.setFixedHeight(7)

        # Cap laff/bean QPushButton height so the sub_row fits inside
        # the 50 px portrait placeholder. Without this the system style
        # chrome inflates the button sizeHint to ~28-32 px in the real
        # app (Fusion vertical padding), pushing meta_col content (name
        # 29 px + button) past 50 and growing the card by ~11 px when
        # laff data populates.
        self._tab.laff_labels[i].setIcon(make_heart_icon(16))
        self._tab.bean_labels[i].setIcon(make_jellybean_icon(16))
        self._tab.laff_labels[i].setFixedHeight(20)
        self._tab.bean_labels[i].setFixedHeight(20)

        game_badge = self._tab.game_badges[i]
        game_badge.setMinimumSize(0, 0)
        game_badge.setMaximumSize(16777215, 16777215)

        # Direction D header: name at 23 px bold for hierarchy against
        # the smaller stats text. setPixelSize so rendered size matches
        # the design mockup regardless of DPI scaling.
        # Also update the stylesheet font-size so Qt's CSS cascade does
        # not override the QFont set above. refresh_theme() writes
        # font-size: 21px on name_label (compact size); clearing that
        # stylesheet rule here lets the full-mode QFont take effect.
        c = self._tab._c()
        name_label, _ = self._tab.toon_labels[i]
        name_font = QFont()
        name_font.setPixelSize(23)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setStyleSheet(
            f"font-size: 23px; font-weight: bold; color: {c['text_primary']}; "
            f"background: none; border: none; padding-left: 6px;"
        )

        # Buttons: constructor defaults are 88x32 enable, 32x32
        # chat/KA/help, 14px icons.
        self._tab.toon_buttons[i].setFixedHeight(32)
        self._tab.toon_buttons[i].setFixedWidth(88)
        self._tab.chat_buttons[i].setFixedHeight(32)
        self._tab.chat_buttons[i].setFixedWidth(32)
        self._tab.click_sync_buttons[i].setFixedHeight(32)
        self._tab.click_sync_buttons[i].setFixedWidth(32)
        self._tab.keep_alive_buttons[i].setFixedHeight(32)
        self._tab.keep_alive_buttons[i].setFixedWidth(32)
        # Help button: keep it at the same 32×32 reference as chat/KA so
        # the discovery affordance reads in the same row geometry.
        self._tab.help_buttons[i].setFixedHeight(32)
        self._tab.help_buttons[i].setFixedWidth(32)
        self._tab.chat_buttons[i].setIconSize(QSize(14, 14))
        self._tab.click_sync_buttons[i].setIconSize(QSize(14, 14))
        self._tab.keep_alive_buttons[i].setIconSize(QSize(14, 14))
        self._tab.help_buttons[i].setIconSize(QSize(14, 14))
        self._tab.laff_labels[i].setIconSize(QSize(17, 17))
        self._tab.bean_labels[i].setIconSize(QSize(17, 17))

        # Direction D stats font: 15 px Medium weight to balance the
        # larger name above. setPixelSize so the rendered size matches
        # the design mockup regardless of DPI scaling.
        # Stylesheet updated to match so Qt's CSS cascade does not
        # override the QFont (refresh_theme writes font-size: 14px).
        stats_font = QFont()
        stats_font.setPixelSize(15)
        stats_font.setWeight(QFont.Medium)
        self._tab.laff_labels[i].setFont(stats_font)
        self._tab.bean_labels[i].setFont(stats_font)
        stat_style = (
            f"border: none; background: transparent; font-weight: 500; "
            f"font-size: 15px; color: {c['text_primary']}; "
            f"padding: 0; min-height: 0;"
        )
        self._tab.laff_labels[i].setStyleSheet(stat_style)
        self._tab.bean_labels[i].setStyleSheet(stat_style)

        # top_row: portrait_placeholder | meta_col(name + sub_row) | game_badge
        # The real 64x64 badge is overlaid on top of the placeholder via
        # _position_portraits (free-floating child of the card).
        clear_layout(slot["top_row"])
        clear_layout(slot["meta_col"])
        clear_layout(slot["sub_row"])

        # sub_row hosts both mode-specific info sets. _tab.py drives the
        # per-widget visibility: laff/bean stay hidden when no laff data
        # is available (CC mode), and cc_subtitle is shown only when
        # set_compact_cc_subtitle has been called with a non-None
        # playground. Adding all three here means neither mode needs
        # structural changes during runtime toggles.
        slot["sub_row"].addWidget(self._tab.laff_labels[i])
        slot["sub_row"].addWidget(self._tab.bean_labels[i])
        slot["sub_row"].addWidget(
            self._tab._compact_cc_subtitles[i],
            alignment=Qt.AlignLeft,
        )
        slot["sub_row"].addStretch()

        # meta_col: name on top, sub_row underneath. Stretches above and
        # below the content vertically center the block in the top_row's
        # 50 px slot — when sub_row is empty (no laff data and no CC
        # subtitle) the name alone sits between the card top and the
        # divider; when sub_row has content the stretches collapse and
        # the 2-line stack fills the row.
        name_label, status_dot = self._tab.toon_labels[i]
        slot["meta_col"].addStretch()
        slot["meta_col"].addWidget(name_label)
        slot["meta_col"].addLayout(slot["sub_row"])
        slot["meta_col"].addStretch()

        # top_row: portrait_placeholder | meta_col (stretch=1) | game_badge.
        # stretch on meta_col pushes the chip flush against the right
        # edge of the header.
        slot["top_row"].addWidget(slot["portrait_placeholder"])
        slot["top_row"].addLayout(slot["meta_col"], 1)
        slot["top_row"].addWidget(
            self._tab.game_badges[i], alignment=Qt.AlignTop
        )

        # PulsingDot is no longer added next to the name. Instead it
        # becomes the portrait status ring overlay (reparented to the
        # card; positioned in _position_status_rings()). Stash it in
        # the slot dict so the position helper can find it.
        status_dot.setParent(slot["card"])
        slot["status_ring"] = status_dot

        # ctrl_row: toon_button | middle (ka_group + addStretch) | set_selector
        clear_layout(slot["ctrl_row"])
        clear_layout(slot["middle"])
        clear_layout(slot["ka_group_layout"])
        slot["ctrl_row"].addWidget(self._tab.toon_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.chat_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.click_sync_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.help_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.keep_alive_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.ka_progress_bars[i], 1)
        slot["middle"].addWidget(slot["ka_group"], 1)
        slot["middle"].addStretch(1)
        slot["ctrl_row"].addLayout(slot["middle"], 1)
        slot["ctrl_row"].addWidget(self._tab.set_selectors[i])

    def _position_portraits(self) -> None:
        """Position each card's 130x130 portrait widget. Horizontal:
        9 px left of the placeholder's top-left so the extra size
        extends into the card's left padding. Vertical: centered
        between the stripe bottom (y=5, just below the 5 px accent
        border-top) and the divider top, so the portrait reads as
        anchored in the visible top section with body color showing
        above and below it. Must be called AFTER Qt has resolved the
        layout and BEFORE _position_status_rings (which uses
        badge.bottomRight for the corner dot)."""
        for i, slot in enumerate(self._card_slots):
            placeholder = slot.get("portrait_placeholder")
            divider = slot.get("header_divider")
            if placeholder is None or divider is None:
                continue
            badge = self._tab.slot_badges[i]
            card = slot["card"]
            ph_top_left = placeholder.mapTo(card, placeholder.rect().topLeft())
            div_top_y = divider.mapTo(card, divider.rect().topLeft()).y()
            # Stripe occupies the card's 5 px transparent border-top.
            stripe_bottom_y = 5
            center_y = (stripe_bottom_y + div_top_y) // 2
            badge_x = ph_top_left.x() - 9
            badge_y = center_y - badge.height() // 2
            badge.move(badge_x, badge_y)
            badge.show()
            badge.raise_()

    def _position_status_rings(self) -> None:
        """Re-position the portrait status-dot overlays after Qt has
        resolved layout. Called from showEvent / resizeEvent /
        populate()."""
        from tabs.multitoon._compact_layout import _is_descendant_of
        for i, slot in enumerate(self._card_slots):
            ring = slot.get("status_ring")
            if ring is None:
                continue
            badge = self._tab.slot_badges[i]
            if not badge.isVisible():
                continue
            card = slot["card"]
            # Skip if the badge has been reparented out of this full
            # card (e.g., during compact-mode operations while full is
            # still warming or transitioning). mapTo on a non-ancestor
            # target prints a Qt warning and returns junk coords; the
            # ring will be repositioned correctly when full reclaims
            # ownership.
            if not _is_descendant_of(badge, card):
                continue
            # Anchor the status dot at badge.bottomRight() with a small
            # overhang past the badge bounding-box corner: 3 px right,
            # 2 px down. Compact's literal (-18, -19) was the same idea
            # for a 21x21 dot widget (21 - 3, 21 - 2). Here we compute
            # the offset from the live widget size so the dot scales
            # cleanly when set_size flips it between compact 13 (widget
            # 21) and full 24 (widget 32). At 32x32 this resolves to
            # (-29, -30), which keeps the dot center sitting at the
            # visible-circle bottom-right of the 120 badge instead of
            # drifting past the corner.
            br = badge.mapTo(card, badge.rect().bottomRight())
            ring.move(br.x() - (ring.width() - 3), br.y() - (ring.height() - 2))
            ring.show()
            ring.raise_()

    def _position_stripes(self) -> None:
        """Place each card's stripe widget at the top edge of the card.
        Called from showEvent / resizeEvent and from populate()."""
        for slot in self._card_slots:
            stripe = slot.get("card_stripe")
            if stripe is None:
                continue
            card = slot["card"]
            stripe.setGeometry(0, 0, card.width(), 5)
            stripe.show()
            stripe.raise_()

    def _position_cards(self) -> None:
        """Compatibility shim for prewarm_full_layout, which calls this
        after ensurePolished() to warm the layout-resolution + paint
        paths. The compact-clone layout has no per-card geometry to
        position (cards live in a QGridLayout that Qt resolves
        automatically); the only positioning work is the portrait /
        status ring / stripe overlays, which we re-run here so prewarm
        warms those paths too."""
        self._position_portraits()
        self._position_status_rings()
        self._position_stripes()

    def _apply_full_card_heights(self) -> None:
        """Set each card's fixed height to _FULL_CARD_HEIGHT (190).
        Hardcoded rather than computed from sizeHint because the
        enlarged top-section placeholder (120 vs compact's 50) would
        push `sizeHint * 1.5` (the prior dynamic-measurement rule that
        existed before this constant was introduced) to ~280, far past
        the user-approved
        190.

        Called deferred via QTimer.singleShot(0, ...) from populate()
        for consistency with the rest of the populate flow; no
        functional reason to defer a hardcoded constant, but the
        deferral is harmless and matches the existing shape."""
        for slot in self._card_slots:
            card = slot.get("card")
            if card is None:
                continue
            card.setFixedHeight(_FULL_CARD_HEIGHT)
        # Reposition the badge / status ring / stripe overlays — but
        # ONLY if the shared widgets are currently parented to full's
        # cards. At init the sequence is: _CompactLayout.populate runs
        # (parents widgets into compact); _FullLayout constructor runs
        # (parents widgets into full + schedules this method via
        # QTimer.singleShot(0)); _compact.populate runs again (parents
        # widgets back to compact). By the time this deferred method
        # fires, the widgets live in compact's cards. Calling the
        # position helpers anyway would use full's slot["card"] coords
        # via mapTo, then apply them to widgets whose parent is
        # compact's card — sliding the badges down past compact's
        # divider line. Skip the position pass when we don't own the
        # widgets; full's own populate path will run the helpers
        # synchronously when full mode actually becomes active.
        if self._owns_shared_widgets():
            self._position_portraits()
            self._position_status_rings()
            self._position_stripes()

    def _owns_shared_widgets(self) -> bool:
        """True if slot_badges[0] is a descendant of this layout's
        card 0. Used to gate the deferred position pass against the
        init-time ownership race (compact ends up with the badges by
        the time the QTimer.singleShot(0) tick lands)."""
        if not self._card_slots or not self._tab.slot_badges:
            return False
        target_card = self._card_slots[0].get("card")
        if target_card is None:
            return False
        parent = self._tab.slot_badges[0].parentWidget()
        while parent is not None:
            if parent is target_card:
                return True
            parent = parent.parentWidget()
        return False

    def showEvent(self, event):
        super().showEvent(event)
        self._position_portraits()
        self._position_status_rings()
        self._position_stripes()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_portraits()
        self._position_status_rings()
        self._position_stripes()

    def _collapsed_ka_group_width(self, slot_index: int) -> int:
        """Width that ka_group must hold when KA is collapsed.

        ka_group's row contains chat + click-sync + help + (hidden ka +
        hidden bar). When collapsed, chat and help are visible (plus the
        click-sync button when its master switch shows it), so the frame
        must be wide enough to fit them plus inter-widget spacing plus
        contentsMargins.

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
        cs_btn = self._tab.click_sync_buttons[slot_index]
        help_btn = self._tab.help_buttons[slot_index]
        layout = self._card_slots[slot_index]["ka_group"].layout()
        margins = layout.contentsMargins()
        width = (
            _layout_width(chat_btn)
            + _layout_width(help_btn)
            + layout.spacing()
            + margins.left()
            + margins.right()
        )
        # The click-sync button only takes layout space when shown by the
        # Settings master switch. isHidden() (not isVisible()) matches how
        # QLayout allocates space — isVisible() is False for the whole tree
        # before the window is shown.
        if not cs_btn.isHidden():
            width += _layout_width(cs_btn) + layout.spacing()
        return width

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
        Compact-clone behavior: ka_group's fixed-width animates via
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

    def apply_theme(self, c: dict) -> None:
        """Walk every slot and reapply brand chrome. Used by prewarm and the
        mode-swap hook in _tab.py. The actual theme palette is already in
        `c`; set_card_brand re-resolves theme + body color."""
        for i in range(4):
            badge = self._tab.game_badges[i] if i < len(self._tab.game_badges) else None
            game = None
            if badge is not None and badge.isVisible():
                game = "cc" if badge.text() == "CC" else "ttr"
            enabled = (
                self._tab.enabled_toons[i]
                if i < len(self._tab.enabled_toons) else False
            )
            self.set_card_brand(i, game, enabled=enabled)

    def deactivate(self):
        """Called when leaving Full mode. Cancel in-flight KA animations so
        finish handlers don't land on widgets being reparented."""
        for a in getattr(self, "_ka_anims", []):
            try:
                a.stop()
            except RuntimeError:
                pass
        self._ka_anims = []


class _FullLayout(QWidget):
    """QGraphicsView wrapper that scales _FullContent uniformly via _SCALE.

    The actual widget tree (controls + 2x2 card grid) lives in
    _FullContent. _FullLayout hosts it via a QGraphicsScene +
    QGraphicsProxyWidget and applies the _SCALE transform on the view.
    Every public method (populate, apply_theme, deactivate, etc.) and
    selected attributes (_card_slots, _card_grid, _ka_anims) are
    forwarded to self._content so _tab.py callers don't know about
    the wrapping.
    """

    _SCALE = 1.125

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._content = _FullContent(tab)

        self._scene = QGraphicsScene(self)
        self._proxy = self._scene.addWidget(self._content)
        self._proxy.setPos(0, 0)

        self._view = QGraphicsView(self._scene, self)
        self._view.setRenderHints(
            QPainter.Antialiasing
            | QPainter.SmoothPixmapTransform
            | QPainter.TextAntialiasing
        )
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setFrameStyle(QFrame.NoFrame)
        self._view.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        # Transparent viewport so the tab background bleeds through.
        # Four overlapping mechanisms because each catches a different
        # Qt-version/theme failure mode:
        #   - setBackgroundBrush(Qt.transparent): QGraphicsView's scene
        #     background fill, the primary signal to Qt's painter.
        #   - QSS background: transparent: handles QSS-aware themes that
        #     would otherwise paint a default palette background.
        #   - WA_TranslucentBackground: required on some Linux WMs where
        #     the previous two are otherwise composited under an opaque
        #     window-system background.
        #   - viewport().setAutoFillBackground(False): the actual viewport
        #     QWidget under the scene, which would otherwise honor its
        #     palette role and paint a fill before the scene renders.
        # Dropping any one of these has produced visible regressions in
        # one Qt environment or another.
        self._view.setBackgroundBrush(Qt.transparent)
        self._view.setStyleSheet(
            "QGraphicsView { background: transparent; border: none; }"
        )
        self._view.setAttribute(Qt.WA_TranslucentBackground, True)
        self._view.viewport().setAutoFillBackground(False)

        # Idempotent: setTransform replaces the current transform
        # instead of multiplying, so if __init__ ever ran twice the
        # scale wouldn't compound.
        self._view.setTransform(QTransform().scale(self._SCALE, self._SCALE))

        # Keep the scene rect synced to the content's natural size so
        # the view's transform shows the entire content at _SCALE without
        # blank scene area or cropping.
        self._sync_scene_rect()
        self._content.installEventFilter(self)

        outer.addWidget(self._view)

    def eventFilter(self, obj, ev):
        if obj is self._content and ev.type() == QEvent.Resize:
            self._sync_scene_rect()
        return super().eventFilter(obj, ev)

    def _sync_scene_rect(self):
        hint = self._content.sizeHint()
        size = self._content.size()
        w = max(hint.width(), size.width(), 1)
        h = max(hint.height(), size.height(), 1)
        self._scene.setSceneRect(0, 0, w, h)

    # ── Forwarded public API ──────────────────────────────────────────

    def populate(self):
        self._content.populate()

    def apply_theme(self, c):
        self._content.apply_theme(c)

    def deactivate(self):
        self._content.deactivate()

    def set_card_brand(self, i, game, enabled=False):
        self._content.set_card_brand(i, game, enabled=enabled)

    def _animate_keep_alive_visibility(self, target_visible):
        self._content._animate_keep_alive_visibility(target_visible)

    def _set_keep_alive_collapsed(self, collapsed):
        self._content._set_keep_alive_collapsed(collapsed)

    def _position_portraits(self):
        self._content._position_portraits()

    def _position_status_rings(self):
        self._content._position_status_rings()

    def _position_stripes(self):
        self._content._position_stripes()

    def _position_cards(self):
        self._content._position_cards()

    # ── Forwarded attributes (read-only properties) ──────────────────

    @property
    def _card_slots(self):
        return self._content._card_slots

    @property
    def _card_grid(self):
        return self._content._card_grid

    @property
    def _ka_anims(self):
        return self._content._ka_anims
