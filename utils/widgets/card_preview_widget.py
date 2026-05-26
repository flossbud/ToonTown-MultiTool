"""Hand-painted miniature card used as the live preview pane inside
ToonCustomizationDialog. Reads from a draft dict, consults the
resolver helpers, never touches the manager."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from utils.toon_customization_resolve import (
    resolve_accent,
    resolve_body,
    resolve_circle_outline,
    resolve_portrait_brush,
    resolve_portrait_pattern,
    resolve_silhouette_outline,
    resolve_silhouette_shadow,
)
from utils.toon_pattern_assets import tinted_pattern_pixmap
import utils.portrait_effects as portrait_effects


_PREVIEW_W = 360
_PREVIEW_H = 72

# Brand color defaults mirror tabs/multitoon/_compact_layout.set_card_brand
_TTR_BRAND = "#4A8FE7"
_CC_BRAND = "#F26D21"
_SLOT_DEFAULT_BG = "#4a4a4a"
_CARD_BG = "#1a1d29"
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
        rect = self.rect()

        # Card background. When the user has picked a non-default body
        # color the card paints it at full opacity so the on-card result
        # matches the swatch. Default body (None) keeps the theme card bg.
        body = resolve_body(self._draft)
        if body is not None:
            p.fillRect(rect, QColor(body))
        else:
            p.fillRect(rect, QColor(_CARD_BG))

        # Accent stripe (top 5 px)
        accent = resolve_accent(self._draft, _brand_fallback(self._game))
        p.fillRect(QRect(rect.left(), rect.top(), rect.width(), 5), accent)

        # Portrait circle (40 px, vertically centered, 10 px from left)
        circle_d = 40
        circle_rect = QRect(
            10,
            (rect.height() - circle_d) // 2 + 1,
            circle_d,
            circle_d,
        )
        portrait_brush = resolve_portrait_brush(
            self._draft, QColor(_SLOT_DEFAULT_BG)
        )
        p.setPen(Qt.NoPen)
        p.setBrush(portrait_brush)
        p.drawEllipse(circle_rect)

        pattern = resolve_portrait_pattern(self._draft)
        if pattern is not None:
            name, color = pattern
            pm = tinted_pattern_pixmap(name, color, tile_size=24)
            if not pm.isNull():
                path = QPainterPath()
                path.addEllipse(circle_rect)
                p.save()
                p.setClipPath(path)
                # Tile the pattern across the circle area.
                for y in range(circle_rect.top(), circle_rect.bottom() + 1, 24):
                    for x in range(circle_rect.left(), circle_rect.right() + 1, 24):
                        p.drawPixmap(x, y, pm)
                p.restore()

        # Pose pixmap layer (clipped to portrait circle, with transform).
        if self._pose_pixmap is not None and not self._pose_pixmap.isNull():
            from utils.toon_customization_resolve import resolve_portrait_transform
            zoom, off_x, off_y, rot = resolve_portrait_transform(self._draft)
            ox = int(off_x * circle_rect.width())
            oy = int(off_y * circle_rect.height())
            # Bake zoom into the downscale so the 512 source resamples once
            # to its final visible size (no two-stage scale-then-zoom).
            final_w = max(1, round(circle_rect.width() * zoom))
            final_h = max(1, round(circle_rect.height() * zoom))
            final_size = QSize(final_w, final_h)
            path = QPainterPath()
            path.addEllipse(circle_rect)
            p.save()
            p.setClipPath(path)
            p.translate(circle_rect.center())
            p.rotate(rot)
            # Offset is in unzoomed circle-fractions; scale by zoom so the
            # pan-while-zoomed behavior matches the pre-refactor painter.scale path.
            p.translate(ox * zoom, oy * zoom)
            scaled = self._pose_pixmap.scaled(
                final_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
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
                p.drawPixmap(
                    -scaled.width() // 2, -scaled.height() // 2, outline_pm,
                )
            p.drawPixmap(-scaled.width() // 2, -scaled.height() // 2, scaled)
            p.restore()

        # Circle outline (drawn on top of pose, outside the clip).
        circle_outline = resolve_circle_outline(self._draft)
        if circle_outline is not None:
            color, width = circle_outline
            inset = max(0, width // 2)
            p.setPen(QPen(color, width))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(circle_rect.adjusted(inset, inset, -inset, -inset))

        # Toon name
        p.setPen(QColor(_TEXT))
        f: QFont = p.font()
        f.setPixelSize(16)
        f.setBold(True)
        p.setFont(f)
        p.drawText(
            QRect(60, 6, rect.width() - 70, 24),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._toon_name or "Toon",
        )

        # Chip on right (outlined pill, accent border + text)
        chip_text = "TTR" if self._game == "ttr" else ("CC" if self._game == "cc" else "")
        if chip_text:
            chip_w = 38
            chip_h = 18
            chip_rect = QRect(
                rect.width() - chip_w - 8,
                (rect.height() - chip_h) // 2,
                chip_w,
                chip_h,
            )
            p.setPen(accent)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(chip_rect, 9, 9)
            f2: QFont = p.font()
            f2.setPixelSize(10)
            f2.setBold(True)
            p.setFont(f2)
            p.drawText(chip_rect, Qt.AlignCenter, chip_text)

        # Subtitle row
        p.setPen(QColor(_TEXT_DIM))
        f3: QFont = p.font()
        f3.setPixelSize(11)
        f3.setBold(False)
        p.setFont(f3)
        p.drawText(
            QRect(60, rect.height() - 26, rect.width() - 70, 20),
            Qt.AlignVCenter | Qt.AlignLeft,
            "Live preview",
        )
        p.end()
