"""PrimaryToonSlot - the Launch tab account tile's 38px primary-toon portrait.

Set state: a filled circle (portraitBg token) showing the account's real toon
portrait, pulled from the SAME source the emblem radial menu accounts ring uses
(utils.overlay.radial_portrait.render_account_portrait -> the real Rendition
portrait via ToonPortraitWidget, disk-cached, with an async pose_ready refresh
for a cold cache). While a portrait is still loading (or for a Corporate Clash
toon with no DNA), it falls back to a tinted race silhouette. The circle is
ringed 3px in the toon's own accent (or the game accent when none is known).
Unset state: a dashed 2px ring with a centered "+" glyph. A 16x16 slot-number
badge rides the top-left corner in both states, drawn once a slot number is set.

Pure paintEvent - no QGraphicsEffect (kit law: this widget's paintEvent does
QPainter(self) directly, and attaching a QGraphicsEffect to it trips Qt's
"one painter at a time" conflict).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from utils.color_math import lighten_rgb, with_alpha
from utils.theme_manager import V2_ACCENTS
from utils.toon_silhouette import paint_race_silhouette

SIZE = 38
SILHOUETTE_FRACTION = 0.76
RING_W = 3
BADGE_SIZE = 16
BADGE_CENTER = 8.0
BADGE_RING_W = 2
DASH_W = 2
GLYPH_HALF = 6
GLYPH_W = 2


def _tokens(is_dark: bool) -> dict:
    if is_dark:
        return {
            "portrait_bg": with_alpha("#000000", 0.22),
            "dashed": with_alpha("#ffffff", 0.35),
            "sub": with_alpha("#ffffff", 0.62),
            "badge_ring": with_alpha("#000000", 0.28),
        }
    return {
        "portrait_bg": with_alpha("#0f172a", 0.06),
        "dashed": with_alpha("#0f172a", 0.35),
        "sub": with_alpha("#0f172a", 0.55),
        "badge_ring": with_alpha("#ffffff", 0.75),
    }


class PrimaryToonSlot(QWidget):
    clicked = Signal()

    def __init__(self, game: str, parent=None):
        super().__init__(parent)
        assert game in ("ttr", "cc")
        self._game = game
        self._toon_name: str | None = None
        self._dna: str | None = None
        self._species: str | None = None
        self._accent: str | None = None
        self._slot: int | None = None
        self._set = False
        self._is_dark = True
        self._portrait: QPixmap | None = None   # real toon portrait when loaded
        self._customizations = None             # ToonCustomizationsManager (pose etc.)
        self.setFixedSize(SIZE, SIZE)
        self.setCursor(Qt.PointingHandCursor)
        # Refresh the portrait when a cold-cache Rendition fetch completes, the
        # same way the radial accounts ring does. Auto-disconnected when this
        # widget is destroyed (Qt drops connections to a dead QObject receiver).
        try:
            from utils.rendition_poses import RenditionPoseFetcher
            RenditionPoseFetcher.instance().pose_ready.connect(self._on_pose_ready)
        except Exception:
            pass

    def sizeHint(self) -> QSize:
        return QSize(SIZE, SIZE)

    def set_toon(self, *, toon_name: str | None = None, dna: str | None = None,
                 species: str | None = None, accent: str | None = None,
                 slot_number: int | None = None) -> None:
        # A toon is "set" once it has a name or a species; passing all of those
        # as None leaves the UNSET (dashed) visual while still showing the
        # slot-number badge (the tile uses this for a dashed, numbered slot).
        # clear() remains the fully-empty (no badge) reset.
        changed = (toon_name != self._toon_name) or (dna != self._dna)
        self._toon_name = toon_name
        self._dna = dna
        self._species = species
        self._accent = accent
        self._slot = slot_number
        self._set = bool(toon_name or species)
        if changed:
            self._portrait = None
            self._load_portrait()
        self.update()

    def clear(self) -> None:
        self._set = False
        self._toon_name = None
        self._dna = None
        self._species = None
        self._accent = None
        self._slot = None
        self._portrait = None
        self.update()

    def is_set(self) -> bool:
        return self._set

    def has_portrait(self) -> bool:
        """True when the real toon portrait (not the silhouette fallback) is loaded."""
        return self._portrait is not None and not self._portrait.isNull()

    def set_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def set_customizations_manager(self, manager) -> None:
        """Inject the ToonCustomizationsManager so the portrait renders the toon's
        saved pose + customizations, matching the radial menu exactly. Reloads the
        portrait if one is already showing."""
        if manager is self._customizations:
            return
        self._customizations = manager
        if self._set and self._dna:
            self._portrait = None
            self._load_portrait()
            self.update()

    def _emit_click(self) -> None:
        self.clicked.emit()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    # ── portrait loading (radial-menu source) ───────────────────────────────
    def _load_portrait(self) -> None:
        """Render the real toon portrait from DNA (disk-cache-synchronous). On a
        cache miss the fetch is kicked off and _on_pose_ready fills it in later;
        until then the silhouette fallback shows. No DNA (Corporate Clash) keeps
        the silhouette."""
        self._portrait = None
        if not self._set or not self._dna:
            return
        try:
            from utils.overlay.radial_portrait import render_account_portrait
            render = render_account_portrait(
                self._game, self._toon_name, self._dna,
                self._customizations, SIZE)
            if render.status == "complete":
                self._portrait = render.pixmap
        except Exception:
            self._portrait = None

    def _on_pose_ready(self, dna, pose, pixmap) -> None:
        # Only react while we are still WAITING for this slot's portrait. Once it
        # is loaded, stop: render_account_portrait re-fires the fetch as a side
        # effect (set_dna -> fetcher.request), and a warm cache re-emits pose_ready
        # via singleShot(0) -- so re-rendering here re-arms the signal that called
        # us, an event-loop-saturating feedback storm (~130% CPU, ~15fps). This is
        # the same one-shot latch the radial accounts ring uses (its _loading set).
        # A DNA change resets _portrait to None (set_toon), so a new toon still
        # refreshes. pixmap is None is the fetcher's failure signal (skip likewise).
        if (not self._set or not self._dna or dna != self._dna
                or pixmap is None or self.has_portrait()):
            return
        try:
            from utils.overlay.radial_portrait import render_account_portrait
            render = render_account_portrait(
                self._game, self._toon_name, self._dna,
                self._customizations, SIZE)
            if render.status == "complete":
                self._portrait = render.pixmap
                self.update()
        except Exception:
            pass

    # ── painting ─────────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        t = _tokens(self._is_dark)
        game_accent = V2_ACCENTS[self._game]
        circle_rect = QRectF(0, 0, SIZE, SIZE)

        if self._set:
            self._paint_set_state(p, t, game_accent, circle_rect)
        else:
            self._paint_unset_state(p, t, circle_rect)

        if self._slot is not None:
            self._paint_slot_badge(p, t, game_accent)

        p.end()

    def _paint_set_state(self, p: QPainter, t: dict, game_accent: dict,
                          circle_rect: QRectF) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(t["portrait_bg"])
        p.drawEllipse(circle_rect)

        accent_hex = self._accent or game_accent["c"]
        if self.has_portrait():
            # Real toon portrait - already circular at SIZE from render_account_portrait.
            p.drawPixmap(0, 0, self._portrait)
        elif self._species:
            # Loading / no-DNA fallback: tinted race silhouette.
            inset = SIZE * (1 - SILHOUETTE_FRACTION) / 2
            sil_rect = circle_rect.adjusted(inset, inset, -inset, -inset).toRect()
            fill_hex = lighten_rgb(QColor(accent_hex), 0.5).name()
            paint_race_silhouette(p, sil_rect, self._species, fill_hex)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(accent_hex), RING_W))
        ring_rect = circle_rect.adjusted(RING_W / 2, RING_W / 2, -RING_W / 2, -RING_W / 2)
        p.drawEllipse(ring_rect)

    def _paint_unset_state(self, p: QPainter, t: dict, circle_rect: QRectF) -> None:
        p.setBrush(Qt.NoBrush)
        pen = QPen(t["dashed"], DASH_W, Qt.DashLine)
        p.setPen(pen)
        ring_rect = circle_rect.adjusted(DASH_W / 2, DASH_W / 2, -DASH_W / 2, -DASH_W / 2)
        p.drawEllipse(ring_rect)

        cx, cy = SIZE / 2, SIZE / 2
        glyph_pen = QPen(t["sub"], GLYPH_W, Qt.SolidLine, Qt.RoundCap)
        p.setPen(glyph_pen)
        p.drawLine(QPointF(cx - GLYPH_HALF, cy), QPointF(cx + GLYPH_HALF, cy))
        p.drawLine(QPointF(cx, cy - GLYPH_HALF), QPointF(cx, cy + GLYPH_HALF))

    def _paint_slot_badge(self, p: QPainter, t: dict, game_accent: dict) -> None:
        badge_rect = QRectF(0, 0, BADGE_SIZE, BADGE_SIZE)
        badge_rect.moveCenter(QPointF(BADGE_CENTER, BADGE_CENTER))

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(game_accent["b"]))
        p.drawEllipse(badge_rect)

        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(t["badge_ring"], BADGE_RING_W))
        ring_rect = badge_rect.adjusted(BADGE_RING_W / 2, BADGE_RING_W / 2,
                                         -BADGE_RING_W / 2, -BADGE_RING_W / 2)
        p.drawEllipse(ring_rect)

        p.setPen(QColor("#ffffff"))
        font = p.font()
        font.setPixelSize(9)
        font.setBold(True)
        p.setFont(font)
        p.drawText(badge_rect, Qt.AlignCenter, str(self._slot))
