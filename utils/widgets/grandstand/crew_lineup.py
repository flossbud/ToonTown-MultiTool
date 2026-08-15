"""The hero's toon lineup (handoff §4.1b): up to four figures on one stage.

A single painted widget. Four child widgets would each need their own rotation,
overlap order and animated `right` offset, which Qt's layout system actively
fights; one paint surface makes the 320ms reflow a matter of interpolating
numbers instead of re-parenting widgets.

`set_entries` diffs against the current slots so a toon that survives a
selection change slides to its new position rather than being destroyed and
rebuilt — the difference between a stage and a slideshow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QPointF, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

import utils.motion as motion
from utils.cc_race_assets import load_race_pixmap
from utils.rendition_poses import RenditionPoseFetcher
from utils.toon_silhouette import paint_race_silhouette
from utils.widgets.grandstand import palette as gp
from utils.widgets.grandstand.model import LineupEntry

# Offsets from the lineup's right edge, per party size, so 1-4 toons all sit
# composed instead of clinging to one edge (handoff §8).
CREW_SLOTS = {1: [168], 2: [252, 84], 3: [300, 168, 36], 4: [336, 224, 112, 0]}
ROT = [-3, 2, -2, 3]

STANDING = (212, 300)
BUST = (196, 196)
CAMEO = 180
PLACEHOLDER = 92

STANDING_BOTTOM = -62
BUST_BOTTOM = -14
CAMEO_BOTTOM = 22

REFLOW_MS = 320
FADE_MS = 260


@dataclass
class Slot:
    """One figure on the stage, plus its animated state."""

    account_id: str
    treatment: str
    pose: str
    dna: str
    icon_stem: Optional[str]
    species: Optional[str]
    accent: str
    initial: str
    right: float = 0.0
    target_right: float = 0.0
    start_right: float = 0.0
    start_opacity: float = 0.0
    start_lift: float = 26.0
    rotation: float = 0.0
    opacity: float = 1.0
    lift: float = 0.0
    is_new: bool = True
    requested_key: Optional[tuple[str, str]] = None
    pixmap: Optional[QPixmap] = field(default=None, repr=False)

    @property
    def size(self) -> tuple[int, int]:
        if self.treatment == "standing":
            return STANDING
        if self.treatment == "bust":
            return BUST
        if self.treatment == "cameo":
            return (CAMEO, CAMEO)
        return (PLACEHOLDER, PLACEHOLDER)


class CrewLineup(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._slots: list[Slot] = []
        self._is_dark = True
        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._tick)
        self._elapsed = 0

        self._fetcher = RenditionPoseFetcher.instance()
        self._fetcher.pose_ready.connect(self._on_pose_ready)

    # ── inbound ────────────────────────────────────────────────────────────

    def slots(self) -> list[Slot]:
        return list(self._slots)

    def slot_for(self, account_id: str) -> Optional[Slot]:
        for slot in self._slots:
            if slot.account_id == account_id:
                return slot
        return None

    def set_entries(self, entries: list[LineupEntry]) -> None:
        """Diff the lineup while preserving slots that survive a reflow."""
        entries = list(entries)[:4]
        existing = {slot.account_id: slot for slot in self._slots}
        new: list[Slot] = []
        for entry in entries:
            slot = existing.get(entry.account_id)
            if slot is None:
                slot = Slot(
                    account_id=entry.account_id,
                    treatment=entry.treatment,
                    pose=entry.pose,
                    dna=entry.dna,
                    icon_stem=entry.icon_stem,
                    species=entry.species,
                    accent=entry.accent,
                    initial=entry.initial,
                    opacity=0.0,
                    lift=26.0,
                )
                self._load_art(slot)
            else:
                art_key_changed = (
                    slot.treatment != entry.treatment
                    or slot.pose != entry.pose
                    or slot.dna != entry.dna
                    or slot.icon_stem != entry.icon_stem
                    or slot.species != entry.species
                )
                slot.treatment, slot.pose = entry.treatment, entry.pose
                slot.dna = entry.dna
                slot.icon_stem = entry.icon_stem
                slot.species = entry.species
                slot.accent, slot.initial = entry.accent, entry.initial
                if art_key_changed:
                    slot.pixmap = None
                    self._load_art(slot)
            new.append(slot)

        offsets = CREW_SLOTS.get(len(new), [])
        for index, slot in enumerate(new):
            slot.target_right = float(offsets[index])
            slot.rotation = float(ROT[index % len(ROT)])
            if slot.is_new:
                # A brand-new slot fades in already at its final position; only
                # survivors have somewhere to slide FROM. Track this explicitly:
                # keying off opacity breaks when set_entries runs twice before
                # the first tick, teleporting survivors still sitting at 0.
                slot.right = slot.target_right
                slot.is_new = False
            # Capture where this slot IS, not where a fresh entrance would
            # start. `_elapsed` is shared and resets each reflow, so
            # recomputing from zero would replay a half-finished entrance
            # backwards — opacity dropping, lift jumping up.
            slot.start_right = slot.right
            slot.start_opacity = slot.opacity
            slot.start_lift = slot.lift

        self._slots = new
        if motion.is_reduced():
            self.settle()
            return
        self._elapsed = 0
        self._anim.start()
        self.update()

    def settle(self) -> None:
        """Snap every slot to its complete visual state and stop animating."""
        self._anim.stop()
        for slot in self._slots:
            slot.right = slot.target_right
            slot.opacity = 1.0
            slot.lift = 0.0
        self.update()

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    # ── art ────────────────────────────────────────────────────────────────

    def _load_art(self, slot: Slot) -> None:
        """Use cached art synchronously and request only cache misses."""
        slot.requested_key = None
        if slot.treatment == "cameo":
            slot.pixmap = (
                load_race_pixmap(slot.icon_stem) if slot.icon_stem else None
            )
            return
        if slot.treatment == "placeholder" or not slot.dna:
            slot.pixmap = None
            return
        slot.pixmap = self._fetcher.cached_pixmap(slot.dna, slot.pose)
        if slot.pixmap is None:
            slot.requested_key = (slot.dna, slot.pose)
            self._fetcher.request(*slot.requested_key)

    def _on_pose_ready(self, dna: str, pose: str, pixmap) -> None:
        """Ignore asynchronous replies no current slot is waiting for."""
        touched = False
        key = (dna, pose)
        for slot in self._slots:
            if slot.requested_key == key:
                slot.pixmap = pixmap
                slot.requested_key = None
                touched = True
        if touched:
            self.update()

    # ── animation ──────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._elapsed += self._anim.interval()
        t = min(1.0, self._elapsed / REFLOW_MS)
        eased = 1 - pow(1 - t, 3)
        done = True
        for slot in self._slots:
            fade = min(1.0, self._elapsed / FADE_MS)
            slot.opacity = (
                slot.start_opacity + (1.0 - slot.start_opacity) * fade
            )
            slot.lift = slot.start_lift * (1.0 - eased)
            slot.right = (
                slot.start_right
                + (slot.target_right - slot.start_right) * eased
            )
            if (slot.opacity < 1.0 or slot.lift > 0.01
                    or abs(slot.target_right - slot.right) > 0.01):
                done = False
        self.update()
        if done or t >= 1.0:
            self.settle()

    # ── paint ──────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        if not self._slots:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        for slot in self._slots:
            self._paint_slot(painter, slot)
        painter.end()

    def _paint_slot(self, painter: QPainter, slot: Slot) -> None:
        ink = gp.lineup_ink(self._is_dark)
        width, height = slot.size
        x = self.width() - slot.right - width
        if slot.treatment == "standing":
            y = self.height() - height - STANDING_BOTTOM
        elif slot.treatment == "bust":
            y = self.height() - height - BUST_BOTTOM
        elif slot.treatment == "cameo":
            y = self.height() - height - CAMEO_BOTTOM
        else:
            y = self.height() - height - 40

        painter.save()
        painter.setOpacity(slot.opacity)
        painter.translate(QPointF(x + width / 2, y + height / 2 + slot.lift))
        painter.rotate(slot.rotation)
        painter.translate(QPointF(-width / 2, -height / 2))
        box = QRect(0, 0, width, height)

        if slot.treatment == "cameo":
            painter.setPen(Qt.NoPen)
            painter.setBrush(ink["cameo_disc"])
            painter.drawEllipse(box)
            ring = QPen(QColor(slot.accent))
            ring.setWidth(4)
            painter.setPen(ring)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(box.adjusted(2, 2, -2, -2))
            if slot.pixmap is not None and not slot.pixmap.isNull():
                inset = int(width * 0.11)
                painter.drawPixmap(
                    box.adjusted(inset, inset, -inset, -inset), slot.pixmap
                )
            else:
                paint_race_silhouette(
                    painter,
                    box.adjusted(24, 24, -24, -24),
                    slot.species,
                    slot.accent,
                )
        elif slot.treatment == "placeholder":
            pen = QPen(ink["placeholder_border"])
            pen.setWidth(2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(box)
            painter.setPen(ink["placeholder_ink"])
            font = painter.font()
            font.setPointSize(22)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(box, Qt.AlignCenter, slot.initial)
        elif slot.pixmap is not None and not slot.pixmap.isNull():
            painter.drawPixmap(box, slot.pixmap)
        else:
            paint_race_silhouette(
                painter, box, slot.species, slot.accent
            )
        painter.restore()
