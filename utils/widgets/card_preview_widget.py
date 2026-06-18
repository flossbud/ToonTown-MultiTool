"""Hand-painted miniature card used as the live preview pane inside
ToonCustomizationDialog. Reads from a draft dict, consults the
resolver helpers, never touches the manager."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import QWidget

from utils.color_math import darken_rgb
from utils.toon_customization_resolve import (
    resolve_accent,
    resolve_body,
    resolve_portrait_brush,
    resolve_portrait_pattern,
    resolve_silhouette_outline,
    resolve_silhouette_shadow,
)
from utils.toon_pattern_assets import tinted_pattern_pixmap
import utils.portrait_effects as portrait_effects


_PREVIEW_W = 300
_PREVIEW_H = 176

# Geometry constants (proportional to live card in _compact_layout.py)
_CARD_RADIUS = 20       # matches CARD_RADIUS in the live card
_CARD_BORDER_W = 5      # matches CARD_BORDER in the live card
_PORTRAIT_D = 80        # portrait circle diameter (mini scale of PORTRAIT=172)
_PORTRAIT_X = 12        # left margin for portrait
_PORTRAIT_RING = 3      # accent ring width around portrait circle

# Brand color defaults mirror tabs/multitoon/_compact_layout.set_card_brand
_TTR_BRAND = "#4A8FE7"
_CC_BRAND = "#F26D21"
_SLOT_DEFAULT_BG = "#4a4a4a"
_TEXT = "#e8e8f0"
_TEXT_DIM = "#9a9aa8"


def _brand_fallback(game: str) -> QColor:
    if game == "ttr":
        return QColor(_TTR_BRAND)
    if game == "cc":
        return QColor(_CC_BRAND)
    return QColor(_SLOT_DEFAULT_BG)


class CardPreviewWidget(QWidget):
    def __init__(
        self,
        game: str,
        toon_name: str,
        draft: dict,
        parent=None,
        *,
        dna: Optional[str] = None,
    ):
        super().__init__(parent)
        self._game = game
        self._toon_name = toon_name
        self._draft: dict = dict(draft)
        self._dna = dna
        self._pose_pixmap: Optional[QPixmap] = None
        self._silhouette_cache: dict[tuple, tuple] = {}
        # key: (id(pose_pm), pose_size_tuple, outline_color or None, outline_width,
        #       shadow_color or None, shadow_blur)
        # value: (outline_pixmap or None, shadow_pixmap or None)
        # bounded to 4 entries (drop oldest on insert).
        self.setMinimumSize(_PREVIEW_W, _PREVIEW_H)
        self.setMaximumSize(_PREVIEW_W, _PREVIEW_H)

        # Subscribe to the fetcher for this widget's lifetime.
        if self._dna:
            from utils.rendition_poses import RenditionPoseFetcher
            self._fetcher = RenditionPoseFetcher.instance()
            self._fetcher.pose_ready.connect(self._on_pose_ready)
            # Kick off the initial fetch for the current draft pose.
            self._request_current_pose()
        else:
            self._fetcher = None

    def draft(self) -> dict:
        return dict(self._draft)

    def dna(self) -> Optional[str]:
        return self._dna

    def current_portrait_transform(self) -> tuple[float, float, float, float]:
        """Test hook: returns the (zoom, off_x, off_y, rotate) tuple
        the next paintEvent will apply to the pose pixmap."""
        from utils.toon_customization_resolve import resolve_portrait_transform
        return resolve_portrait_transform(self._draft)

    def _current_pose(self) -> str:
        from utils.toon_customization_resolve import resolve_pose
        return resolve_pose(self._draft, "portrait")

    def _request_current_pose(self) -> None:
        if not self._dna or self._fetcher is None:
            return
        self._fetcher.request(self._dna, self._current_pose())

    def set_draft(self, draft: dict) -> None:
        prev_pose = self._current_pose()
        self._draft = dict(draft)
        new_pose = self._current_pose()
        if new_pose != prev_pose and self._dna and self._fetcher is not None:
            self._pose_pixmap = None  # show spinner while refetching
            self._fetcher.request(self._dna, new_pose)
        self.update()

    def _get_silhouette_bundle(
        self, pose_pm: "QPixmap", scaled_size,
    ) -> tuple:
        """Look up or build outline + shadow pixmaps for the current
        draft + supplied pose pixmap. Returns (outline_pm, shadow_pm,
        shadow_offset_x, shadow_offset_y). Either pixmap may be None.
        Cache is bounded to 4 entries (drop oldest)."""
        outline = resolve_silhouette_outline(self._draft)
        shadow = resolve_silhouette_shadow(self._draft)
        if outline is None and shadow is None:
            return (None, None, 0, 0)
        ocol_name = outline[0].name() if outline else None
        owidth = outline[1] if outline else 0
        scol_name = shadow[0].name() if shadow else None
        sblur = shadow[1] if shadow else 0
        soff_x = shadow[2] if shadow else 0
        soff_y = shadow[3] if shadow else 0
        key = (
            id(pose_pm),
            (scaled_size.width(), scaled_size.height()),
            ocol_name, owidth,
            scol_name, sblur,
        )
        cached = self._silhouette_cache.get(key)
        if cached is not None:
            o_pm, s_pm = cached
            return (o_pm, s_pm, soff_x, soff_y)
        # Build fresh. Scale the pose pixmap to the same size as the
        # rendered circle so effects align.
        scaled = pose_pm.scaled(
            scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        outline_pm = None
        shadow_pm = None
        if outline is not None:
            outline_pm = portrait_effects.build_silhouette_outline_pixmap(
                scaled, outline[0], owidth,
            )
        if shadow is not None:
            shadow_pm = portrait_effects.build_silhouette_shadow_pixmap(
                scaled, shadow[0], sblur,
            )
        # Bounded LRU: drop oldest when full.
        if len(self._silhouette_cache) >= 4:
            oldest = next(iter(self._silhouette_cache))
            self._silhouette_cache.pop(oldest)
        self._silhouette_cache[key] = (outline_pm, shadow_pm)
        return (outline_pm, shadow_pm, soff_x, soff_y)

    def _on_pose_ready(self, dna: str, pose: str, pixmap) -> None:
        if dna != self._dna:
            return
        if pose != self._current_pose():
            return
        self._pose_pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()

        accent = resolve_accent(self._draft, _brand_fallback(self._game))
        body_override = resolve_body(self._draft)

        # Card body: rounded rectangle (no concave cutout in the preview)
        # with a deep accent gradient, mirroring _QuadCardBackground.
        # If body override is set, it drives the gradient base instead of accent.
        base = QColor(body_override) if body_override is not None else accent
        card_path = QPainterPath()
        card_path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), _CARD_RADIUS, _CARD_RADIUS)

        # Body gradient: darken_rgb(base, 0.28) top → darken_rgb(base, 0.14) bottom,
        # same formula as _QuadCardBackground for the lit (non-dimmed) state.
        top_col = darken_rgb(base, 0.28)
        bot_col = darken_rgb(base, 0.14)
        grad = QLinearGradient(0, 0, w * 0.38, h)
        grad.setColorAt(0.0, top_col)
        grad.setColorAt(1.0, bot_col)
        p.fillPath(card_path, grad)

        # 5px inner accent border: stroke at 2x width clipped to path so
        # only the inner half survives, matching _QuadCardBackground's border.
        p.save()
        p.setClipPath(card_path)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(accent, _CARD_BORDER_W * 2))
        p.drawPath(card_path)
        p.restore()

        # Portrait circle (80 px, vertically centred, _PORTRAIT_X from left)
        circle_y = (h - _PORTRAIT_D) // 2
        circle_rect = QRect(_PORTRAIT_X, circle_y, _PORTRAIT_D, _PORTRAIT_D)

        # Portrait fill (solid base from draft resolver)
        portrait_brush = resolve_portrait_brush(self._draft, QColor(_SLOT_DEFAULT_BG))
        p.setPen(Qt.NoPen)
        p.setBrush(portrait_brush)
        p.drawEllipse(circle_rect)

        # Portrait pattern overlay (clipped to circle)
        pattern = resolve_portrait_pattern(self._draft)
        if pattern is not None:
            pat_name, pat_color = pattern
            pm = tinted_pattern_pixmap(pat_name, pat_color, tile_size=24)
            if not pm.isNull():
                clip = QPainterPath()
                clip.addEllipse(circle_rect)
                p.save()
                p.setClipPath(clip)
                for ty in range(circle_rect.top(), circle_rect.bottom() + 1, 24):
                    for tx in range(circle_rect.left(), circle_rect.right() + 1, 24):
                        p.drawPixmap(tx, ty, pm)
                p.restore()

        # Pose pixmap (clipped to portrait circle, with draft transform)
        if self._pose_pixmap is not None and not self._pose_pixmap.isNull():
            from utils.toon_customization_resolve import resolve_portrait_transform
            zoom, off_x, off_y, rot = resolve_portrait_transform(self._draft)
            ox = int(off_x * circle_rect.width())
            oy = int(off_y * circle_rect.height())
            # Bake zoom into the downscale so the 512 source resamples once.
            final_w = max(1, round(circle_rect.width() * zoom))
            final_h = max(1, round(circle_rect.height() * zoom))
            final_size = QSize(final_w, final_h)
            pose_clip = QPainterPath()
            pose_clip.addEllipse(circle_rect)
            p.save()
            p.setClipPath(pose_clip)
            p.translate(circle_rect.center())
            p.rotate(rot)
            # Offset is in unzoomed circle-fractions; scale by zoom so
            # pan-while-zoomed matches the pre-refactor painter.scale path.
            p.translate(ox * zoom, oy * zoom)
            scaled = self._pose_pixmap.scaled(
                final_size, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            outline_pm, shadow_pm, sx, sy = self._get_silhouette_bundle(
                self._pose_pixmap, final_size,
            )
            if shadow_pm is not None and not shadow_pm.isNull():
                pad_x = (shadow_pm.width() - scaled.width()) // 2
                pad_y = (shadow_pm.height() - scaled.height()) // 2
                p.drawPixmap(
                    -scaled.width() // 2 - pad_x + sx,
                    -scaled.height() // 2 - pad_y + sy,
                    shadow_pm,
                )
            if outline_pm is not None and not outline_pm.isNull():
                p.drawPixmap(-scaled.width() // 2, -scaled.height() // 2, outline_pm)
            p.drawPixmap(-scaled.width() // 2, -scaled.height() // 2, scaled)
            p.restore()

        # Accent portrait ring: drawn after pose so it's always visible at
        # the circle edge, mirroring _PortraitFrame's accent ring treatment.
        ring_inset = _PORTRAIT_RING // 2
        p.setPen(QPen(accent, _PORTRAIT_RING))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(circle_rect.adjusted(ring_inset, ring_inset, -ring_inset, -ring_inset))

        # Text column: right of the portrait circle
        text_x = _PORTRAIT_X + _PORTRAIT_D + 12
        text_w = w - text_x - 10
        # Centre the two-line block alongside the portrait
        text_block_h = 24 + 6 + 18   # name + gap + stats
        text_top = circle_y + (_PORTRAIT_D - text_block_h) // 2

        # Toon name (bold, white)
        p.setPen(QColor(_TEXT))
        fn: QFont = p.font()
        fn.setPixelSize(16)
        fn.setBold(True)
        p.setFont(fn)
        p.drawText(
            QRect(text_x, text_top, text_w, 24),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._toon_name or "Toon",
        )

        # Laff / beans placeholder row (dim, smaller font)
        p.setPen(QColor(_TEXT_DIM))
        fs: QFont = p.font()
        fs.setPixelSize(11)
        fs.setBold(False)
        p.setFont(fs)
        p.drawText(
            QRect(text_x, text_top + 24 + 6, text_w, 18),
            Qt.AlignVCenter | Qt.AlignLeft,
            "♥  --      ◆  --",
        )
        p.end()
