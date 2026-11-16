"""Appearance editor body (design note 2026-11-16; handoff §4.2, §4.3, §4.6).

The second body of the focus-mode sheet: subject row, framing canvas, and
the controls in decision order (Looks, Backdrop, Pattern, Accent, Pose).
Nothing here writes: the editor changes an AppearanceDraft and emits
intents; the view hands the draft to LaunchTab, which performs the write.

Repaint discipline (handoff §5): colour and framing edits restyle the canvas
in place; only a pose change re-reads its render. Popovers are children of
this widget, raised over it, and at most one is open.
"""
from __future__ import annotations

import random
from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
    QWidget,
)

from utils import cc_race_assets
from utils.rendition_poses import POSE_NAMES
from utils.toon_renders import ToonRenders
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.account_sheet import GAME_NAMES
from utils.widgets.grandstand.appearance_controls import (
    ChipRow, ColorWell, ElidedLabel, FramingCanvas, GradientBar, GroupHeader,
    LooksRow, MiniLink, PoseStrip, ScopeDot, SliderRow, StandIn, SubjectPill,
    SwapButton, SwatchPopover, ToonSwitcher, species_label, transparent,
)
from utils.widgets.grandstand.appearance_draft import (
    FILL_GRADIENT, FILL_SOLID, POSE_LABELS, AppearanceDraft,
)
from utils.widgets.grandstand.draft import unique_toons
from utils.widgets.grandstand.look_paint import ART_INSET, HEAD_SCALE, HEAD_SHIFT
from utils.widgets.grandstand.model import (
    CARD_POSE, PORTRAIT_RENDER, PORTRAIT_SPECIES,
)

# Measurements, handoff §4.2.
STAGE_W = 272
COL_GAP = 20
APPBAR_GAP = 12
GROUP_GAP = 15
GROUP_INNER_GAP = 9
STAGE_PAD = 16
STAGE_GAP = 12
SLIDERS_MAX_W = 250

# Copy. Verbatim from the handoff unless noted in the design note §5; no
# em-dash reaches the user.
CROSS_LINK = "⚙ Account settings"
SCOPE = "the look follows the toon, not the account"
SURPRISE = "Surprise me"
RESET = "Reset all"
HINT = "Drag the portrait to reposition"
LOOKS_LABEL, LOOKS_NOTE = "Looks", "a whole backdrop in one click"
BACKDROP_LABEL, BACKDROP_NOTE = "Backdrop", "behind the portrait"
PATTERN_LABEL, PATTERN_NOTE = "Pattern", "tiled over the backdrop"
ACCENT_LABEL, ACCENT_NOTE = "Accent", "ring, badge and card wash"
POSE_LABEL = "Pose"
PORTRAIT_ART_LABEL = "Portrait art"
# The saved pose is drawn by the Multitoon badge and the radial menu; the
# hero stage draws one pose for every toon (model.STAGE_POSE).
POSE_NOTE = "{label} · Multitoon and the radial menu"
SPECIES_NOTE = "no render service for this game"
WAITING_NOTE = "no toon discovered yet"
NO_DNA_NOTE = "no render for this toon yet"
FILL_CHOICES = [(FILL_SOLID, "Solid"), (FILL_GRADIENT, "Gradient")]
PATTERN_NONE = "None"
AUTOMATIC = "automatic"
ACCENT_AUTOMATIC = "game accent · {hex}"
ACCENT_CLEAR = "Use game accent"
BACKDROP_CLEAR = "Use automatic backdrop"
SPECIES_TITLE = "{species} race icon"
SPECIES_BODY = (
    "Corporate Clash publishes no render service, so {toon} cannot be drawn "
    "from the game. The launcher uses the {species} race icon it ships with. "
    "Backdrop, pattern and accent all still apply, and they are what make "
    "this portrait yours.")
SPECIES_NO_TOON_BODY = (
    "Launch this account once so the launcher can discover a toon. Corporate "
    "Clash toons are shown with the race icon the launcher ships with.")
WAITING_BODY = (
    "Poses need a toon render. Launch this account once so the launcher can "
    "discover a toon, then every pose becomes selectable here.")
NO_DNA_BODY = (
    "Poses need a toon render, and the launcher has not read {toon}'s look "
    "from the game yet. Play this toon once more and every pose becomes "
    "selectable here.")
NOTE_SAVES = "Saves to toon_customizations.json · {key}"
NOTE_NOTHING = "Nothing to save until a toon is discovered"


def title_for(draft: AppearanceDraft) -> str:
    return f"Appearance · {draft.toon_name or draft.account_name}"


def subtitle_for(draft: AppearanceDraft) -> str:
    game = GAME_NAMES.get(draft.game) or (draft.game or "").upper()
    if not draft.has_toon:
        return f"{game} · {WAITING_NOTE}"
    return (f"{game} · this look follows {draft.toon_name} wherever the "
            "launcher shows it")


def note_for(draft: AppearanceDraft) -> str:
    """Footer note on the appearance surface (handoff §4.4)."""
    if not draft.has_toon:
        return NOTE_NOTHING
    return NOTE_SAVES.format(key=draft.store_key)


class AppearanceSheet(QWidget):
    changed = Signal()
    toon_switch_requested = Signal(str)        # toon name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        transparent(self, "gs_appearance_sheet")
        # Focusable itself, so the editor opens with focus inside the sheet
        # (Esc and Enter reach the shell) without lighting a focus ring on
        # the first control before anyone has pressed Tab.
        self.setFocusPolicy(Qt.StrongFocus)
        self._is_dark = True
        self._draft: Optional[AppearanceDraft] = None
        self._toons: list = []
        self._primary: Optional[str] = None
        self._open_well: Optional[ColorWell] = None
        self._watching = False
        self._rng = random.Random()
        self._renders = ToonRenders.instance()
        self._renders.render_landed.connect(self._on_render_landed)
        self._renders.set_promoted.connect(self._on_set_promoted)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(APPBAR_GAP)

        # ── subject row (handoff §4.3) ─────────────────────────────────────
        self.appbar = QWidget(self)
        transparent(self.appbar, "gs_appbar")
        bar = QHBoxLayout(self.appbar)
        bar.setContentsMargins(2, 0, 2, 0)
        bar.setSpacing(APPBAR_GAP)
        self.pill = SubjectPill(self.appbar)
        self.pill.clicked.connect(self._on_pill_clicked)
        bar.addWidget(self.pill, 0, Qt.AlignVCenter)
        scope = QHBoxLayout()
        scope.setContentsMargins(0, 0, 0, 0)
        scope.setSpacing(7)
        self.scope_dot = ScopeDot(self.appbar)
        self.scope = QLabel(SCOPE, self.appbar)
        scope.addWidget(self.scope_dot, 0, Qt.AlignVCenter)
        scope.addWidget(self.scope, 0, Qt.AlignVCenter)
        bar.addLayout(scope)
        bar.addStretch(1)
        self.surprise = MiniLink(SURPRISE, True, self.appbar)
        self.surprise.clicked.connect(self._on_surprise)
        self.reset = MiniLink(RESET, False, self.appbar)
        self.reset.clicked.connect(self._on_reset)
        bar.addWidget(self.surprise, 0, Qt.AlignVCenter)
        bar.addWidget(self.reset, 0, Qt.AlignVCenter)
        outer.addWidget(self.appbar)

        # ── the two columns, in a scroll area for a short band ─────────────
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.columns = QWidget()
        transparent(self.columns, "gs_app_cols")
        cols = QHBoxLayout(self.columns)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(COL_GAP)
        self.scroll.setWidget(self.columns)
        outer.addWidget(self.scroll, 1)

        # left: the framing canvas
        self.stage = QFrame(self.columns)
        self.stage.setObjectName("gs_app_stage")
        self.stage.setFixedWidth(STAGE_W)
        stage = QVBoxLayout(self.stage)
        stage.setContentsMargins(STAGE_PAD, STAGE_PAD, STAGE_PAD, STAGE_PAD)
        stage.setSpacing(STAGE_GAP)
        stage.addStretch(1)
        self.canvas = FramingCanvas(self.stage)
        self.canvas.framing_dragged.connect(self._on_canvas_dragged)
        stage.addWidget(self.canvas, 0, Qt.AlignHCenter)
        self.tag = QLabel(self.stage)
        self.tag.setAlignment(Qt.AlignCenter)
        stage.addWidget(self.tag, 0, Qt.AlignHCenter)
        self.hint = QLabel(HINT.upper(), self.stage)
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        stage.addWidget(self.hint)
        self.sliders = QWidget(self.stage)
        transparent(self.sliders, "gs_app_sliders")
        self.sliders.setMaximumWidth(SLIDERS_MAX_W)
        sliders = QVBoxLayout(self.sliders)
        sliders.setContentsMargins(0, 0, 0, 0)
        sliders.setSpacing(7)
        self.zoom_row = SliderRow("gs_app_zoom", "Zoom", 50, 300, True, self.sliders)
        self.zoom_row.value_changed.connect(self._on_zoom_changed)
        self.turn_row = SliderRow("gs_app_turn", "Turn", -180, 180, False, self.sliders)
        self.turn_row.value_changed.connect(self._on_turn_changed)
        sliders.addWidget(self.zoom_row)
        sliders.addWidget(self.turn_row)
        stage.addWidget(self.sliders)
        stage.addStretch(1)
        cols.addWidget(self.stage)

        # right: the controls, whole look first, then the pieces
        self.controls = QWidget(self.columns)
        transparent(self.controls, "gs_app_controls")
        right = QVBoxLayout(self.controls)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(GROUP_GAP)
        cols.addWidget(self.controls, 1)

        self.looks_header = GroupHeader("gs_grp_looks", LOOKS_LABEL, self.controls)
        self.looks_header.set_note(LOOKS_NOTE)
        self.looks = LooksRow(self.controls)
        self.looks.look_clicked.connect(self._on_look_clicked)
        right.addLayout(self._group(self.looks_header, self.looks))

        self.wells: dict[str, ColorWell] = {}
        self.backdrop_header = GroupHeader("gs_grp_backdrop", BACKDROP_LABEL, self.controls)
        self.backdrop_header.set_note(BACKDROP_NOTE)
        self.backdrop_row = QWidget(self.controls)
        transparent(self.backdrop_row, "gs_row_backdrop")
        row = self._row(self.backdrop_row)
        self.fill_chips = ChipRow("gs_chips_fill", self.backdrop_row)
        self.fill_chips.set_choices(FILL_CHOICES)
        self.fill_chips.value_changed.connect(self._on_fill_changed)
        row.addWidget(self.fill_chips)
        row.addStretch(1)
        self.color_readout = self._readout(self.backdrop_row)
        self.gradient_bar = GradientBar(self.backdrop_row)
        self.swap_button = SwapButton(self.backdrop_row)
        self.swap_button.clicked.connect(self._on_swap)
        row.addWidget(self._well("color", self.backdrop_row))
        row.addWidget(self.color_readout)
        row.addWidget(self._well("g_start", self.backdrop_row))
        row.addWidget(self.gradient_bar, 1)
        row.addWidget(self._well("g_end", self.backdrop_row))
        row.addWidget(self.swap_button)
        right.addLayout(self._group(self.backdrop_header, self.backdrop_row))

        self.pattern_header = GroupHeader("gs_grp_pattern", PATTERN_LABEL, self.controls)
        self.pattern_header.set_note(PATTERN_NOTE)
        self.pattern_row = QWidget(self.controls)
        transparent(self.pattern_row, "gs_row_pattern")
        row = self._row(self.pattern_row)
        self.pattern_chips = ChipRow("gs_chips_pattern", self.pattern_row)
        self.pattern_chips.value_changed.connect(self._on_pattern_changed)
        row.addWidget(self.pattern_chips)
        row.addStretch(1)
        self.pattern_readout = self._readout(self.pattern_row)
        row.addWidget(self._well("pat_color", self.pattern_row))
        row.addWidget(self.pattern_readout)
        right.addLayout(self._group(self.pattern_header, self.pattern_row))

        self.accent_header = GroupHeader("gs_grp_accent", ACCENT_LABEL, self.controls)
        self.accent_header.set_note(ACCENT_NOTE)
        self.accent_row = QWidget(self.controls)
        transparent(self.accent_row, "gs_row_accent")
        row = self._row(self.accent_row)
        self.accent_readout = self._readout(self.accent_row)
        row.addWidget(self._well("accent", self.accent_row))
        row.addWidget(self.accent_readout)
        row.addStretch(1)
        right.addLayout(self._group(self.accent_header, self.accent_row))

        self.pose_header = GroupHeader("gs_grp_pose", POSE_LABEL, self.controls)
        self.pose_strip = PoseStrip(self.controls)
        self.pose_strip.pose_clicked.connect(self._on_pose_clicked)
        self.standin = StandIn(self.controls)
        self.waiting = QLabel(self.controls)
        self.waiting.setWordWrap(True)
        pose_group = QVBoxLayout()
        pose_group.setContentsMargins(0, 0, 0, 0)
        pose_group.setSpacing(GROUP_INNER_GAP)
        pose_group.addWidget(self.pose_header)
        pose_group.addWidget(self.pose_strip)
        pose_group.addWidget(self.standin)
        pose_group.addWidget(self.waiting)
        right.addLayout(pose_group)
        right.addStretch(1)

        # ── popovers: children of the editor, raised over the columns ──────
        self.swatch_popover = SwatchPopover(self)
        self.swatch_popover.color_picked.connect(self._on_color_picked)
        self.switcher = ToonSwitcher(self)
        self.switcher.toon_picked.connect(self._on_toon_picked)

        self.apply_theme(True)
        self._apply_mode()

    # ── construction helpers ───────────────────────────────────────────────

    def _group(self, header: QWidget, body: QWidget) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(GROUP_INNER_GAP)
        col.addWidget(header)
        col.addWidget(body)
        return col

    def _row(self, host: QWidget) -> QHBoxLayout:
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        return row

    def _well(self, key: str, parent: QWidget) -> ColorWell:
        well = ColorWell(key, parent)
        well.clicked.connect(self._on_well_clicked)
        self.wells[key] = well
        return well

    def _readout(self, parent: QWidget) -> ElidedLabel:
        """A hex readout: its text's width when the row has room, elided
        before it would push the row past the column."""
        return ElidedLabel(parent, natural=True)

    # ── inbound ────────────────────────────────────────────────────────────

    def open(self, draft: AppearanceDraft, toons: list, primary_name) -> None:
        """Show one toon's look. `toons` is the account's raw record list,
        newest first; rename ghosts collapse here as they do in the account
        sheet and the browser."""
        self._close_popovers()
        self._draft = draft
        self._toons = unique_toons(list(toons))
        self._primary = primary_name
        self.pattern_chips.set_choices(
            [(None, PATTERN_NONE)] + draft.pattern_choices())
        self._apply_mode()
        self._load_art()
        self._sync()
        if draft.can_pose:
            self.pose_strip.reveal(draft.pose)

    def clear(self) -> None:
        self._close_popovers()
        self._draft = None
        self._toons = []
        self._primary = None

    def is_open(self) -> bool:
        return self._draft is not None

    def draft(self) -> Optional[AppearanceDraft]:
        return self._draft

    def account_id(self) -> str:
        return self._draft.account_id if self._draft is not None else ""

    def toon_count(self) -> int:
        return len(self._toons)

    def set_random(self, rng) -> None:
        """Surprise me's dice, replaceable so a test can seed them."""
        self._rng = rng

    def tab_chain(self) -> list[QWidget]:
        """Visual order; the shell appends Cancel and Save."""
        chain: list[QWidget] = [self.pill, self.surprise, self.reset,
                                self.zoom_row.slider, self.turn_row.slider]
        chain += self.looks.swatches
        chain += self.fill_chips.chips()
        chain += [self.wells["color"], self.wells["g_start"],
                  self.wells["g_end"], self.swap_button]
        chain += self.pattern_chips.chips()
        chain += [self.wells["pat_color"], self.wells["accent"]]
        chain += self.pose_strip.tiles
        return chain

    def focus_first(self) -> None:
        self.setFocus()

    # ── capability (handoff §4.6) ──────────────────────────────────────────

    def _apply_mode(self) -> None:
        """Show the pose group's variant for this draft's portrait mode, and
        the framing controls only where a stored framing is drawn."""
        d = self._draft
        mode = d.mode if d is not None else PORTRAIT_RENDER
        has_toon = d is not None and d.has_toon
        can_frame = d is not None and d.can_frame

        self.canvas.set_draggable(can_frame)
        self.hint.setVisible(can_frame)
        self.sliders.setVisible(can_frame)
        self.tag.setVisible(mode == PORTRAIT_SPECIES and has_toon)
        self.pose_strip.setVisible(mode == PORTRAIT_RENDER)
        self.standin.setVisible(mode == PORTRAIT_SPECIES)
        self.waiting.setVisible(mode not in (PORTRAIT_RENDER, PORTRAIT_SPECIES))
        self.pose_header.set_label(
            POSE_LABEL if mode == PORTRAIT_RENDER else PORTRAIT_ART_LABEL)
        # With no toon there is no look to edit: a look is stored per toon.
        self.controls.setEnabled(has_toon)
        self.surprise.setEnabled(has_toon)
        self.reset.setEnabled(has_toon)
        if d is None:
            return

        if mode == PORTRAIT_SPECIES:
            species = species_label(d.species)
            self.tag.setText(SPECIES_TITLE.format(species=species).upper())
            if has_toon:
                self.pose_header.set_note(SPECIES_NOTE)
                self.standin.set_copy(
                    d.species, SPECIES_TITLE.format(species=species),
                    SPECIES_BODY.format(toon=d.toon_name, species=species.lower()))
            else:
                self.pose_header.set_note(WAITING_NOTE)
                self.standin.set_copy(None, PORTRAIT_ART_LABEL, SPECIES_NO_TOON_BODY)
        elif mode != PORTRAIT_RENDER:
            if has_toon:
                self.pose_header.set_note(NO_DNA_NOTE)
                self.waiting.setText(NO_DNA_BODY.format(toon=d.toon_name))
            else:
                self.pose_header.set_note(WAITING_NOTE)
                self.waiting.setText(WAITING_BODY)

    # ── art (a cache consumer: reads, never writes) ────────────────────────

    def _read(self, pose: str) -> Optional[QPixmap]:
        d = self._draft
        if d is None or d.mode != PORTRAIT_RENDER:
            return None
        hit = self._renders.pixmap_for(d.game, d.toon_name, pose)
        return hit[0] if hit is not None else None

    def _species_art(self) -> Optional[QPixmap]:
        """The race icon production paints: the user's own choice
        (`icon_stem`, set in the old customizer) before the species'."""
        d = self._draft
        if d is None or not d.has_toon:
            return None
        chosen = d.base.get("icon_stem")
        stem = None
        if isinstance(chosen, str) and chosen:
            stem = chosen
        if stem is None or cc_race_assets.load_race_pixmap(stem) is None:
            stem = cc_race_assets.asset_stem_for_species(d.species)
        return cc_race_assets.load_race_pixmap(stem) if stem else None

    def _load_canvas_art(self) -> None:
        d = self._draft
        if d is None:
            self.canvas.set_art(None, 1.0, False)
        elif d.mode == PORTRAIT_RENDER:
            self.canvas.set_art(self._read(d.pose), 1.0, True)
        elif d.mode == PORTRAIT_SPECIES:
            self.canvas.set_art(self._species_art(), ART_INSET, False)
        else:
            self.canvas.set_art(None, 1.0, False)

    def _load_art(self) -> None:
        d = self._draft
        if d is None:
            return
        if d.mode == PORTRAIT_RENDER:
            self.looks.set_art(self._read(CARD_POSE), HEAD_SCALE, HEAD_SHIFT)
            for pose in POSE_NAMES:
                self.pose_strip.set_pixmap(pose, self._read(pose))
        elif d.mode == PORTRAIT_SPECIES:
            self.looks.set_art(self._species_art(), ART_INSET, 0.0)
        else:
            self.looks.set_art(None, 1.0, 0.0)
        self._load_canvas_art()
        self.pill.portrait.set_toon(
            d.game, d.toon_name, d.species, d.dna, QColor(d.resolved_accent()))
        self.pill.set_name(d.toon_name or d.account_name)

    def _on_render_landed(self, game: str, name: str, pose: str) -> None:
        d = self._draft
        if d is None or game != d.game:
            return
        if pose == CARD_POSE and self.switcher.isVisible():
            self.switcher.refresh_portraits()
        if name != d.toon_name or d.mode != PORTRAIT_RENDER:
            return
        pm = self._read(pose)
        if pm is None:
            return                      # a landing never clears
        self.pose_strip.set_pixmap(pose, pm)
        if pose == d.pose:
            self.canvas.set_art(pm, 1.0, True)
        if pose == CARD_POSE:
            self.looks.set_art(pm, HEAD_SCALE, HEAD_SHIFT)
            self.pill.portrait.refresh()

    def _on_set_promoted(self, game: str, name: str) -> None:
        d = self._draft
        if d is None or game != d.game:
            return
        if self.switcher.isVisible():
            self.switcher.refresh_portraits()
        if name == d.toon_name:
            self._load_art()

    # ── one repaint for every change ───────────────────────────────────────

    def _sync_canvas(self) -> None:
        d = self._draft
        if d is None:
            return
        self.canvas.set_look(d.preview_entry(), QColor(d.accent_fallback))
        self.zoom_row.set_value(round(d.zoom * 100), f"{d.zoom:.2f}×")
        self.turn_row.set_value(round(d.rotate), f"{round(d.rotate)}°")

    def _sync(self) -> None:
        d = self._draft
        if d is None:
            return
        self._sync_canvas()
        fallback = QColor(d.accent_fallback)
        ring = QColor(d.resolved_accent())
        self.scope_dot.set_color(ring)
        self.pill.portrait.set_ring(ring)

        self.looks.set_accent_fallback(fallback)
        self.looks.set_selected(d.matching_look())

        gradient = d.fill == FILL_GRADIENT
        self.fill_chips.set_value(d.fill)
        self.wells["color"].set_color(d.color, d.color or AUTOMATIC.capitalize())
        self.color_readout.set_full_text(d.color or AUTOMATIC)
        self.wells["g_start"].set_color(d.g_start)
        self.wells["g_end"].set_color(d.g_end)
        self.gradient_bar.set_stops(d.g_start, d.g_end)
        for widget in (self.wells["color"], self.color_readout):
            widget.setVisible(not gradient)
        for widget in (self.wells["g_start"], self.gradient_bar,
                       self.wells["g_end"], self.swap_button):
            widget.setVisible(gradient)

        self.pattern_chips.set_value(d.pat_name)
        self.wells["pat_color"].set_color(d.pat_color)
        self.pattern_readout.set_full_text(d.pat_color)
        for widget in (self.wells["pat_color"], self.pattern_readout):
            widget.setVisible(bool(d.pat_name))

        self.wells["accent"].set_color(d.accent, d.accent or d.accent_fallback)
        self.accent_readout.set_full_text(
            d.accent or ACCENT_AUTOMATIC.format(hex=d.accent_fallback))

        if d.can_pose:
            self.pose_strip.set_selected(d.pose)
            self.pose_header.set_note(POSE_NOTE.format(label=POSE_LABELS[d.pose]))

    def _edited(self) -> None:
        self._sync()
        self.changed.emit()

    # ── edits ──────────────────────────────────────────────────────────────

    def _on_look_clicked(self, index: int) -> None:
        if self._draft is None:
            return
        self._close_popovers()
        self._draft.apply_look(index)
        self._edited()

    def _on_fill_changed(self, fill) -> None:
        if self._draft is None:
            return
        self._close_popovers()
        self._draft.fill = fill
        self._edited()

    def _on_pattern_changed(self, name) -> None:
        if self._draft is None:
            return
        self._close_popovers()
        self._draft.pat_name = name
        self._edited()

    def _on_swap(self) -> None:
        if self._draft is None:
            return
        self._close_popovers()
        self._draft.swap_gradient()
        self._edited()

    def _on_pose_clicked(self, pose: str) -> None:
        d = self._draft
        if d is None or not d.can_pose:
            return
        self._close_popovers()
        if pose != d.pose:
            d.pose = pose
            self._load_canvas_art()         # the one edit that re-reads a render
        self._edited()

    def _on_zoom_changed(self, value: int) -> None:
        if self._draft is None or not self._draft.can_frame:
            return
        self._draft.set_framing(zoom=value / 100.0)
        self._sync_canvas()
        self.changed.emit()

    def _on_turn_changed(self, value: int) -> None:
        if self._draft is None or not self._draft.can_frame:
            return
        self._draft.set_framing(rotate=value)
        self._sync_canvas()
        self.changed.emit()

    def _on_canvas_dragged(self, off_x: float, off_y: float) -> None:
        if self._draft is None or not self._draft.can_frame:
            return
        self._draft.set_framing(off_x=off_x, off_y=off_y)
        self._sync_canvas()
        self.changed.emit()

    def _on_surprise(self) -> None:
        d = self._draft
        if d is None or not d.has_toon:
            return
        self._close_popovers()
        d.surprise(self._rng)
        self._load_canvas_art()
        self._edited()
        if d.can_pose:
            self.pose_strip.reveal(d.pose)

    def _on_reset(self) -> None:
        d = self._draft
        if d is None or not d.has_toon:
            return
        self._close_popovers()
        d.reset()
        self._load_canvas_art()
        self._edited()
        if d.can_pose:
            self.pose_strip.reveal(d.pose)

    # ── popovers: one open at a time, closed by a click anywhere else ──────

    def open_well(self) -> Optional[ColorWell]:
        return self._open_well

    def _on_well_clicked(self) -> None:
        well = self.sender()
        d = self._draft
        if d is None or not isinstance(well, ColorWell):
            return
        if self._open_well is well:
            self._close_popovers()
            return
        self._close_popovers()
        clear = {"accent": ACCENT_CLEAR, "color": BACKDROP_CLEAR}.get(well.key, "")
        self._open_well = well
        well.set_open(True)
        self.swatch_popover.open_for(well, getattr(d, well.key), clear)
        self._watch(True)

    def _on_color_picked(self, hex_) -> None:
        d, well = self._draft, self._open_well
        self._close_popovers()
        if d is None or well is None:
            return
        if hex_ is None and well.key not in ("accent", "color"):
            return                      # only those two have an "unset"
        setattr(d, well.key, hex_)
        self._edited()

    def _on_pill_clicked(self) -> None:
        d = self._draft
        if d is None:
            return
        if self.switcher.isVisible():
            self._close_popovers()
            return
        self._close_popovers()
        # Built now, not at paint time, so the warning reflects the edits
        # made since the editor opened (handoff §4.3).
        self.switcher.open_for(self.pill, d.game, d.account_name, self._toons,
                               d.toon_name, d.is_dirty())
        self._watch(True)

    def set_retarget_only(self, retarget_only: bool) -> None:
        """The toon switcher picks whose look is edited and nothing more
        (the primary toon is set elsewhere)."""
        self.switcher.set_retarget_only(retarget_only)
        self.pill.setToolTip("Edit another toon's look" if retarget_only
                             else "Change which toon this account shows")

    def _on_toon_picked(self, toon_name: str) -> None:
        self._close_popovers()
        self.toon_switch_requested.emit(toon_name)

    def _open_popover(self) -> Optional[QWidget]:
        if self.swatch_popover.isVisible():
            return self.swatch_popover
        if self.switcher.isVisible():
            return self.switcher
        return None

    def _close_popovers(self) -> None:
        if self._open_well is not None:
            self._open_well.set_open(False)
            self._open_well = None
        self.swatch_popover.close_popover()
        self.switcher.close_popover()
        self._watch(False)

    def _watch(self, on: bool) -> None:
        """The application event filter is installed only while a popover is
        open, and always removed when it closes."""
        app = QApplication.instance()
        if app is None or on == self._watching:
            return
        if on:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)
        self._watching = on

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.MouseButtonPress and isinstance(obj, QWidget):
            popover = self._open_popover()
            if popover is not None:
                anchor = popover.anchor()
                inside = (obj is popover or popover.isAncestorOf(obj)
                          or obj is anchor
                          or (anchor is not None and anchor.isAncestorOf(obj)))
                if not inside:
                    # The click still lands where it was aimed, as a click
                    # outside a web popover does.
                    self._close_popovers()
        elif (kind == QEvent.KeyPress and event.key() == Qt.Key_Escape
              and self._open_popover() is not None):
            self._close_popovers()       # Esc closes the popover, not the sheet
            return True
        return False

    def hideEvent(self, event) -> None:
        self._close_popovers()
        super().hideEvent(event)

    # ── theme ──────────────────────────────────────────────────────────────

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        stage = gp.appearance_stage(is_dark)
        ink = gp.appearance_group_ink(is_dark)
        thumb = gp.shelf_scroll(is_dark)["thumb"]
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            " QScrollArea > QWidget#qt_scrollarea_viewport {"
            " background: transparent; }"
            " QScrollBar:vertical { width: 6px; background: transparent;"
            " margin: 0; }"
            " QScrollBar::handle:vertical { border-radius: 3px;"
            f" min-height: 24px; background: {thumb.name()}; }}"
            " QScrollBar::add-line:vertical,"
            " QScrollBar::sub-line:vertical { height: 0; }"
            " QScrollBar::add-page:vertical,"
            " QScrollBar::sub-page:vertical { background: transparent; }")
        self.stage.setStyleSheet(
            f"QFrame#gs_app_stage {{ background: {stage['bg'].name()};"
            f" border: 1px solid {stage['border'].name()}; border-radius: 9px; }}")
        self.hint.setStyleSheet(
            f"color: {stage['hint'].name()}; font-size: 10px; font-weight: 800;"
            " letter-spacing: 0.8px; background: transparent;")
        self.tag.setStyleSheet(
            f"color: {stage['tag_ink'].name()};"
            f" background: {stage['tag_bg'].name(QColor.HexArgb)};"
            f" border: 1px solid {stage['tag_border'].name(QColor.HexArgb)};"
            " border-radius: 10px; padding: 3px 10px; font-size: 10px;"
            " font-weight: 800; letter-spacing: 0.7px;")
        self.scope.setStyleSheet(
            f"color: {ink['scope'].name()}; font-size: 11px;"
            " background: transparent;")
        for readout in (self.color_readout, self.pattern_readout,
                        self.accent_readout):
            readout.setStyleSheet(
                f"color: {ink['readout'].name()}; font-size: 10px;"
                " background: transparent;")
        self.waiting.setStyleSheet(
            f"color: {ink['body'].name()}; font-size: 11px;"
            " background: transparent;")
        for widget in (self.pill, self.surprise, self.reset, self.canvas,
                       self.zoom_row, self.turn_row, self.looks_header,
                       self.looks, self.backdrop_header, self.fill_chips,
                       self.gradient_bar, self.swap_button,
                       self.pattern_header, self.pattern_chips,
                       self.accent_header, self.pose_header, self.pose_strip,
                       self.standin, self.swatch_popover, self.switcher,
                       *self.wells.values()):
            widget.apply_theme(is_dark)
