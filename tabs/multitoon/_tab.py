from __future__ import annotations

import math
import queue
import sys
import threading
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QGraphicsDropShadowEffect, QStackedWidget
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QVariantAnimation, QEasingCurve, QRectF, QPointF, QSize
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPainterPath, QPixmap
from services.input_service import InputService
from services.sleep_inhibitor import SleepInhibitor
from utils.theme_manager import (
    resolve_theme, get_theme_colors, apply_card_shadow,
    make_chat_icon, make_click_sync_icon, make_click_sync_warning_icon,
    make_refresh_icon, make_lightning_icon,
    make_heart_icon, make_jellybean_icon,
    get_set_color, SmoothProgressBar, make_section_label,
)
from utils.shared_widgets import PulsingDot, ElidingLabel
from utils.symbols import S
from utils.ttr_api import get_toon_names_by_slot, invalidate_port_to_wid_cache, clear_stale_names
from utils import cc_api
from utils.game_registry import GameRegistry
from utils import logical_actions
from utils.toon_customizations_manager import ToonCustomizationsManager
from utils.settings_keys import CLICK_SYNC_ENABLED
from utils.color_math import lighten_rgb
from utils.widgets.scale_press import ScalePushButton
from tabs.multitoon._keep_alive_help_button import KeepAliveHelpButton
from utils.card_dim import dim_color, dim_pixmap, lerp_color


# ── Custom Widgets ─────────────────────────────────────────────────────────





# ── Toon Portrait Widget ────────────────────────────────────────────────────

def _lighten_hex(hex_color: str, amount: float = 0.25) -> str:
    """Lighten a hex color by `amount` in HSL lightness (0.0–1.0)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return f"#{hex_color}"
    r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        h = s = 0.0
    else:
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r:   h = (g - b) / d + (6 if g < b else 0)
        elif mx == g: h = (b - r) / d + 2
        else:         h = (r - g) / d + 4
        h /= 6
    l = min(1.0, l + amount)
    if s == 0:
        r = g = b = l
    else:
        def _hue2rgb(p, q, t):
            if t < 0: t += 1
            if t > 1: t -= 1
            if t < 1/6: return p + (q - p) * 6 * t
            if t < 1/2: return q
            if t < 2/3: return p + (q - p) * (2/3 - t) * 6
            return p
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = _hue2rgb(p, q, h + 1/3)
        g = _hue2rgb(p, q, h)
        b = _hue2rgb(p, q, h - 1/3)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


class ToonPortraitWidget(QWidget):
    """Slot badge: shows a rendered toon portrait when available, otherwise
    falls back to a colored circle with the slot number."""

    clicked = Signal()
    edit_icon_requested = Signal()

    def __init__(self, slot: int, parent=None):
        super().__init__(parent)
        self._slot    = slot
        self._peek_opacity = 1.0   # extra hover-peek dim factor for the toon image
        self._dim_progress = 0.0
        self._dim_cache = None        # QPixmap; built lazily while dimmed
        self._dim_cache_size = None   # QSize the cache was built for
        self._bg      = QColor("#4a4a4a")
        self._text    = QColor("#ffffff")
        self._border_color = None
        self._pixmap  = None
        self._silhouette_cache: dict[tuple, tuple] = {}
        self._loading = False
        self._suppress_fallback_glyph = False
        self._dna     = None
        self._pose: str = "portrait"
        self._cc_mode = False
        self._cc_skin: QColor | None = None
        self._cc_accent: QColor | None = None
        self._cc_gloves: QColor | None = None
        self._cc_emoji: str = ""
        self._customizations = None            # ToonCustomizationsManager
        self._toon_name: str | None = None
        self._game: str | None = None
        self._cc_auto_species: str | None = None
        self._hovered = False
        self._press_consumed_by_pencil = False
        self.setMinimumSize(38, 38)
        self.setMaximumSize(64, 64)
        self.setCursor(Qt.PointingHandCursor)
        from utils.rendition_poses import RenditionPoseFetcher
        self._fetcher = RenditionPoseFetcher.instance()
        self._fetcher.pose_ready.connect(self._on_pose_ready)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() != Qt.LeftButton:
            return
        # The pencil overlay is its own affordance: a press inside it fires
        # the edit signal (no need to wait for release, since this opens a
        # modal anyway). Returning early ensures mouseReleaseEvent will not
        # ALSO emit `clicked` for the same gesture.
        if self._can_show_pencil():
            from utils.cc_badge_paint import pencil_rect_for
            if pencil_rect_for(self.rect()).contains(event.position().toPoint()):
                self.edit_icon_requested.emit()
                self._press_consumed_by_pencil = True
                return
        self._press_consumed_by_pencil = False

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton:
            return
        # Standard Qt button convention: emit on release, only if release
        # lands inside the widget. Skip if the press was already handled
        # by the pencil overlay.
        if getattr(self, "_press_consumed_by_pencil", False):
            self._press_consumed_by_pencil = False
            return
        if self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def set_colors(self, bg: str, text: str):
        self._bg   = QColor(bg)
        self._text = QColor(text)
        self._dim_cache = None
        self.update()

    def set_border_color(self, color: str):
        if color:
            self._border_color = QColor(color)
        else:
            self._border_color = None
        self._dim_cache = None
        self.update()

    def set_suppress_fallback_glyph(self, on: bool):
        """When True, the no-pixmap paint branch draws neither the loading
        ellipsis nor the slot number. The radial accounts-ring uses this to
        grab a clean background-only portrait and draw its own spinner."""
        self._suppress_fallback_glyph = bool(on)
        self.update()

    def set_dna(self, dna):
        """Load portrait from Rendition via the shared fetcher. Pass None
        to revert to the fallback circle."""
        if not dna:
            # Always clear when explicitly told to (even if dna was
            # already None) so callers can use set_dna(None) to reset
            # a stale pixmap left behind from a prior fetch.
            self._dna = None
            self._pixmap = None
            self._loading = False
            self._dim_cache = None
            self.update()
            return
        if dna == self._dna:
            return
        self._dna = dna
        # Pick pose from the customizations manager if available.
        self._pose = self._resolve_pose_from_manager()
        self._loading = True
        self._dim_cache = None
        self.update()
        self._fetcher.request(dna, self._pose)

    def _resolve_pose_from_manager(self) -> str:
        from utils.toon_customization_resolve import resolve_pose
        if self._customizations is None or not self._toon_name or self._game not in ("cc", "ttr"):
            return "portrait"
        entry = self._customizations.get(self._game, self._toon_name)
        return resolve_pose(entry, "portrait")

    def set_pose(self, pose: str) -> None:
        """Switch the rendered pose. Triggers a refetch through the
        shared fetcher. Called by _tab.py after a customization Save."""
        if pose == self._pose:
            return
        self._pose = pose
        if self._dna:
            self._pixmap = None
            self._loading = True
            self._dim_cache = None
            self.update()
            self._fetcher.request(self._dna, pose)

    def _on_pose_ready(self, dna: str, pose: str, pixmap) -> None:
        """Receives QPixmap or None from the shared fetcher on the GUI
        thread. Filter by the widget's CURRENT (dna, pose) - stale
        results from prior fetches must be ignored."""
        if dna != self._dna or pose != self._pose:
            return
        self._loading = False
        if pixmap is not None and not pixmap.isNull():
            self._pixmap = pixmap
        else:
            self._pixmap = None
        self._dim_cache = None   # fetched pixmap changes content -> rebuild dim
        self.update()

    def set_cc_mode(self, skin_rgb, accent_rgb, gloves_rgb, emoji):
        """Enable CC paint mode for this badge.

        Pass `skin_rgb=None` to disable CC mode and fall back to the
        default colored-circle rendering.

        Paint now delegates to `utils.cc_badge_paint.paint_cc_badge`,
        which uses only `skin_rgb` plus the resolved asset (from the
        overrides manager or auto-detected species). The `accent_rgb`,
        `gloves_rgb`, and `emoji` parameters are kept on the signature
        for call-site compatibility but are no longer used; remove in
        a follow-up cleanup."""
        if not skin_rgb:
            self._cc_mode = False
            self._cc_skin = None
            self._cc_accent = None
            self._cc_gloves = None
            self._cc_emoji = ""
            self._dim_cache = None
            self.update()
            return
        self._cc_mode = True
        self._cc_skin = QColor.fromRgbF(*skin_rgb)
        self._cc_accent = QColor.fromRgbF(*(accent_rgb or skin_rgb))
        self._cc_gloves = QColor.fromRgbF(*(gloves_rgb or (1.0, 1.0, 1.0)))
        self._cc_emoji = emoji
        self._dim_cache = None
        self.update()

    def set_customizations_manager(self, manager) -> None:
        """Inject the ToonCustomizationsManager (drives portrait lookups)."""
        if self._customizations is manager:
            return
        self._customizations = manager
        self._dim_cache = None
        self.update()

    def set_game(self, game: str | None) -> None:
        """Set the game tag ('cc', 'ttr', or None). Triggers a repaint
        and re-resolves the pose against the manager if a DNA + name
        are already known (same race fix as `set_toon_name`)."""
        if self._game == game:
            return
        self._game = game
        self._dim_cache = None
        self.update()
        if self._dna and self._toon_name and game in ("cc", "ttr"):
            new_pose = self._resolve_pose_from_manager()
            if new_pose != self._pose:
                self.set_pose(new_pose)

    @property
    def game(self) -> str | None:
        return self._game

    def current_portrait_brush(self):
        """Test hook: returns the QBrush the next paintEvent will use for
        the portrait circle."""
        from utils.toon_customization_resolve import resolve_portrait_brush
        entry = {}
        if self._customizations is not None and self._toon_name and self._game:
            entry = self._customizations.get(self._game, self._toon_name)
        return resolve_portrait_brush(entry, self._bg)

    def current_portrait_transform(self):
        """Test hook: returns the (zoom, off_x, off_y, rotate) tuple
        the next paintEvent will apply to the pose pixmap."""
        from utils.toon_customization_resolve import resolve_portrait_transform
        entry = {}
        if self._customizations is not None and self._toon_name and self._game:
            entry = self._customizations.get(self._game, self._toon_name)
        return resolve_portrait_transform(entry)

    def set_toon_name(self, name: str | None) -> None:
        """Set the toon name used as the override key. Triggers a repaint.

        If a DNA is already known, re-resolve the pose against the
        customizations manager - on initial load `set_dna` runs before
        `set_toon_name` (see `_apply_merged_toon_data`), so the first
        fetch always asks for the default "portrait". Once the name
        lands here we re-check the manager and refetch the saved pose
        if it differs."""
        if self._toon_name == name:
            return
        self._toon_name = name
        self._dim_cache = None
        self.update()
        if self._dna and name:
            new_pose = self._resolve_pose_from_manager()
            if new_pose != self._pose:
                self.set_pose(new_pose)

    def set_cc_auto_species(self, species_name: str | None) -> None:
        """Set the auto-detected CC species name (e.g. 'DOG'). Triggers a repaint."""
        if self._cc_auto_species != species_name:
            self._cc_auto_species = species_name
            self._dim_cache = None
            self.update()

    @property
    def toon_name(self) -> str | None:
        return self._toon_name

    @property
    def cc_auto_species(self) -> str | None:
        return self._cc_auto_species

    @property
    def cc_skin(self):
        return self._cc_skin

    def _get_silhouette_bundle(self, pose_pm, scaled_size, entry):
        from utils.toon_customization_resolve import (
            resolve_silhouette_outline, resolve_silhouette_shadow,
        )
        import utils.portrait_effects as portrait_effects
        outline = resolve_silhouette_outline(entry)
        shadow = resolve_silhouette_shadow(entry)
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
        if len(self._silhouette_cache) >= 4:
            oldest = next(iter(self._silhouette_cache))
            self._silhouette_cache.pop(oldest)
        self._silhouette_cache[key] = (outline_pm, shadow_pm)
        return (outline_pm, shadow_pm, soff_x, soff_y)

    def _resolve_asset_stem(self) -> str | None:
        """Resolve which asset stem to render: manual override > auto > None."""
        from utils import cc_race_assets
        if self._customizations is not None and self._toon_name:
            entry = self._customizations.get("cc", self._toon_name)
            override = entry.get("icon_stem")
            if isinstance(override, str):
                return override
        return cc_race_assets.asset_stem_for_species(self._cc_auto_species)

    def _paint_pencil_overlay(self, painter, rect) -> None:
        """Draw the hover-revealed pencil icon at the given rect."""
        from utils.icon_factory import make_edit_icon
        # White circular background with subtle shadow.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        shadow = rect.adjusted(1, 1, 1, 1)
        painter.drawEllipse(shadow)
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawEllipse(rect)
        # Pencil icon centered, ~60% of pencil diameter.
        # Reuses the existing make_edit_icon factory (no duplicate icon).
        icon_size = int(rect.width() * 0.6)
        icon = make_edit_icon(icon_size, color=QColor(40, 50, 70))
        pm = icon.pixmap(icon_size, icon_size)
        x = rect.x() + (rect.width() - icon_size) // 2
        y = rect.y() + (rect.height() - icon_size) // 2
        painter.drawPixmap(x, y, pm)

    def enterEvent(self, event):
        self._hovered = True
        if self._can_show_pencil():
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if self._can_show_pencil():
            self.update()
        super().leaveEvent(event)

    def _can_show_pencil(self) -> bool:
        return bool(self._toon_name) and self._game in ("cc", "ttr")

    def set_peek_opacity(self, opacity: float) -> None:
        """Extra hover-peek translucency factor for the toon image (1.0 = none).
        Multiplies on top of the card's content opacity, so the image lands a bit
        more see-through than the controls/text."""
        opacity = float(opacity)
        if opacity != self._peek_opacity:
            self._peek_opacity = opacity
            self.update()

    def set_dim_progress(self, t: float) -> None:
        # Deliberately does NOT clear _dim_cache: progress changes the BLEND, not
        # the dim pixmap's content. The cache is invalidated by the content
        # setters and resizeEvent (not here), so it survives the whole fade.
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else float(t))
        if t != self._dim_progress:
            self._dim_progress = t
            self.update()

    def set_dimmed(self, on: bool) -> None:
        self.set_dim_progress(1.0 if on else 0.0)

    def resizeEvent(self, event):
        self._dim_cache = None
        super().resizeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        if self._peek_opacity < 1.0:
            p.setOpacity(self._peek_opacity)
        prog = self._dim_progress
        if prog <= 0.0:
            self._render_content(p)
        elif prog >= 1.0:
            p.drawPixmap(0, 0, self._dimmed_pixmap())
        else:
            # TRUE cross-fade: fade the lit toon OUT as the dim toon fades IN.
            # The previous version drew the lit toon at FULL (base) opacity and
            # only the dim pixmap at base*prog; that is linear only at base==1.0.
            # Under transparent/float hover-peek (base < 1.0) the dim overlay's
            # opacity maxes at base*prog and can never fully cover the lit toon,
            # so the lit showed through the whole fade and the portrait only
            # reached full dim in a jump at prog==1 -- making it lag the body
            # (which color-lerps linearly at any opacity). Fading the lit out by
            # (1-prog) makes the portrait dim linearly at ANY opacity, in unison
            # with the rest of the card. base==1.0 (windowed) is unchanged in
            # appearance. peek_opacity already applied to `p` above (base_op).
            base_op = p.opacity()
            p.setOpacity(base_op * (1.0 - prog))
            self._render_content(p)
            p.setOpacity(base_op * prog)
            p.drawPixmap(0, 0, self._dimmed_pixmap())
            p.setOpacity(base_op)
        # Pencil overlay is hover-dependent and must stay LIVE (never cached):
        # drawn on top in both dim and active paths.
        rect = self.rect()
        if self._hovered and self._can_show_pencil():
            from utils.cc_badge_paint import pencil_rect_for
            self._paint_pencil_overlay(p, pencil_rect_for(rect))
        p.end()

    def _dimmed_pixmap(self):
        size = self.size()
        if self._dim_cache is not None and self._dim_cache_size == size:
            return self._dim_cache
        buf = QPixmap(size)
        buf.fill(Qt.transparent)
        bp = QPainter(buf)
        self._render_content(bp)
        bp.end()
        self._dim_cache = dim_pixmap(buf)
        self._dim_cache_size = size
        return self._dim_cache

    def _render_content(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(Qt.NoPen)
        rect = self.rect()
        size = min(rect.width(), rect.height())

        if self._cc_mode and self._cc_skin is not None:
            from utils.cc_badge_paint import paint_cc_badge
            from utils.toon_customization_resolve import (
                resolve_portrait_brush, resolve_portrait_pattern,
            )
            stem = self._resolve_asset_stem()
            entry = {}
            if self._customizations is not None and self._toon_name:
                entry = self._customizations.get("cc", self._toon_name)
            # CC fallback brush is the historic complement of skin color,
            # so we pass None and let paint_cc_badge derive it.
            brush = None
            portrait = entry.get("portrait") if isinstance(entry, dict) else None
            if isinstance(portrait, dict) and (portrait.get("color") or portrait.get("gradient")):
                brush = resolve_portrait_brush(entry, self._cc_skin)
            silhouette_outline_pm = None
            silhouette_shadow_pm = None
            silhouette_shadow_off = (0, 0)
            if self._pixmap and not self._pixmap.isNull():
                from PySide6.QtCore import QSize
                bg_rect = rect.adjusted(2, 2, -2, -2)
                target = min(bg_rect.width(), bg_rect.height())
                outline_pm, shadow_pm, sx, sy = self._get_silhouette_bundle(
                    self._pixmap, QSize(target, target), entry,
                )
                silhouette_outline_pm = outline_pm
                silhouette_shadow_pm = shadow_pm
                silhouette_shadow_off = (sx, sy)
            paint_cc_badge(
                p, rect, self._cc_skin, stem, self._slot,
                portrait_brush=brush,
                pattern=resolve_portrait_pattern(entry),
                silhouette_outline_pixmap=silhouette_outline_pm,
                silhouette_shadow_pixmap=silhouette_shadow_pm,
                silhouette_shadow_offset=silhouette_shadow_off,
            )
            # Pencil overlay is drawn once at the end of paintEvent so it
            # appears for both CC and TTR badges.
        else:
            # Non-CC paint path (TTR / unknown game).
            # Restore pen/brush state for non-CC paint path
            p.setPen(Qt.NoPen)
            cx = self.width() / 2.0
            cy = self.height() / 2.0
            r  = min(cx, cy) - 2.0  # leave room for a 2px border

            # Always draw colored circle background first
            if self._border_color:
                p.setPen(QPen(self._border_color, 2.0))
            else:
                p.setPen(Qt.NoPen)
            entry = {}
            if self._customizations is not None and self._toon_name and self._game:
                entry = self._customizations.get(self._game, self._toon_name)
            from utils.toon_customization_resolve import (
                resolve_portrait_brush, resolve_portrait_pattern,
            )
            p.setBrush(resolve_portrait_brush(entry, self._bg))
            p.drawEllipse(QPointF(cx, cy), r, r)

            pattern = resolve_portrait_pattern(entry)
            if pattern is not None:
                from utils.toon_pattern_assets import tinted_pattern_pixmap
                name, color = pattern
                pm = tinted_pattern_pixmap(name, color, tile_size=24)
                if not pm.isNull():
                    path = QPainterPath()
                    path.addEllipse(QPointF(cx, cy), r, r)
                    p.save()
                    p.setClipPath(path)
                    d = int(r * 2)
                    top = int(cy - r)
                    left = int(cx - r)
                    for y in range(top, top + d + 1, 24):
                        for x in range(left, left + d + 1, 24):
                            p.drawPixmap(x, y, pm)
                    p.restore()

            if self._pixmap and not self._pixmap.isNull():
                from utils.toon_customization_resolve import resolve_portrait_transform
                zoom, off_x, off_y, rot = resolve_portrait_transform(entry)
                circle_w = int(r * 2)
                ox = int(off_x * circle_w)
                oy = int(off_y * circle_w)
                path = QPainterPath()
                path.addEllipse(QPointF(cx, cy), r, r)
                p.save()
                p.setClipPath(path)
                p.translate(cx, cy)
                p.rotate(rot)
                # Offset is in unzoomed circle-fractions; scale by zoom so the
                # pan-while-zoomed behavior matches the pre-refactor painter.scale path.
                p.translate(ox * zoom, oy * zoom)
                # Bake zoom into the downscale so the 512 source resamples once
                # to its final visible size (no two-stage scale-then-zoom).
                target = max(1, round(circle_w * zoom))
                scaled = self._pixmap.scaled(
                    target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
                from PySide6.QtCore import QSize
                outline_pm, shadow_pm, sx, sy = self._get_silhouette_bundle(
                    self._pixmap, QSize(target, target), entry,
                )
                if shadow_pm is not None and not shadow_pm.isNull():
                    pad_x = (shadow_pm.width() - scaled.width()) // 2
                    pad_y = (shadow_pm.height() - scaled.height()) // 2
                    p.drawPixmap(
                        int(-scaled.width() / 2) - pad_x + sx,
                        int(-scaled.height() / 2) - pad_y + sy,
                        shadow_pm,
                    )
                if outline_pm is not None and not outline_pm.isNull():
                    p.drawPixmap(
                        int(-scaled.width() / 2),
                        int(-scaled.height() / 2),
                        outline_pm,
                    )
                p.drawPixmap(
                    int(-scaled.width() / 2),
                    int(-scaled.height() / 2),
                    scaled,
                )
                p.restore()
            elif not self._suppress_fallback_glyph:
                font = QFont()
                font.setPixelSize(14)
                font.setBold(True)
                if self._loading:
                    p.setPen(QColor(180, 180, 180))
                    font.setPixelSize(12)
                    p.setFont(font)
                    p.drawText(self.rect(), Qt.AlignCenter, "…")
                else:
                    p.setFont(font)
                    p.setPen(self._text)
                    p.drawText(self.rect(), Qt.AlignCenter, str(self._slot))

class StatusDots(QWidget):
    """Compact 4-dot row: 0=off, 1=found, 2=active."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Height matches the StatusBar layout cell (34px bar - 2px borders -
        # 16px top/bottom margins = 16px). Anything taller overflows and Qt
        # clamps the widget to the cell top, pushing dots below the text.
        self.setFixedSize(66, 16)
        self._states = [0, 0, 0, 0]
        self._colors = {0: QColor("#333"), 1: QColor("#555"), 2: QColor("#56c856")}
        # When set to 0/1/2, dots painted in that state get a soft white
        # halo (matches the mockup's `box-shadow: 0 0 6px ...` on
        # `.status-dot.active` inside the broadcasting bar). None means
        # no halo on any dot (the default for the Idle palette).
        self._glow_state: int | None = None

    def set_states(self, states: list):
        self._states = (states or [0, 0, 0, 0])[:4]
        while len(self._states) < 4:
            self._states.append(0)
        self.update()

    def set_colors(self, off: str, found: str, active: str, glow_state: int | None = None):
        """`glow_state` selects which dot state (0=off, 1=found, 2=active)
        gets the soft halo. None disables the halo entirely."""
        self._colors = {0: QColor(off), 1: QColor(found), 2: QColor(active)}
        self._glow_state = glow_state
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        diameter = 11
        gap = 6
        total_w = diameter * 4 + gap * 3
        x0 = (self.width() - total_w) / 2.0
        y = (self.height() - diameter) / 2.0
        r = diameter / 2.0
        for i in range(4):
            x = x0 + i * (diameter + gap)
            cx = x + r
            cy = y + r
            state = self._states[i]
            # Soft halo behind any dot whose state matches glow_state.
            # Matches the mockup's `box-shadow: 0 0 6px rgba(255,255,255,0.6)`
            # on `.status-dot.active`.
            if self._glow_state is not None and state == self._glow_state:
                halo_r = r + 4
                grad = QRadialGradient(cx, cy, halo_r)
                halo = QColor(255, 255, 255, 153)  # ~60% white at centre
                grad.setColorAt(0.0, halo)
                halo_edge = QColor(255, 255, 255, 0)
                grad.setColorAt(1.0, halo_edge)
                p.setBrush(grad)
                p.drawEllipse(QRectF(cx - halo_r, cy - halo_r, halo_r * 2, halo_r * 2))
            # Core dot.
            p.setBrush(self._colors.get(state, self._colors[0]))
            p.drawEllipse(QRectF(x, y, diameter, diameter))
        p.end()


class KeepAliveBtn(ScalePushButton):
    """Keep-alive toggle button with a progress ring.

    Short click   → toggle keep-alive on/off.
    Hold 5 s      → toggle rapid-fire for this toon only (independent of the
                    global delay setting). The first 2 s is a silent pre-hold
                    where the button looks like a normal press; the final 3 s
                    shows a red arc growing clockwise around the button.
                    Releasing during the silent pre-hold acts as a click;
                    releasing during the visible countdown cancels.
    """
    rapid_fire_toggled = Signal(bool)

    _PRE_HOLD_MS = 2000   # silent pre-hold before the visible countdown begins
    _COUNTDOWN_MS = 3000  # visible red-arc countdown duration
    _CHARGE_MS = _PRE_HOLD_MS + _COUNTDOWN_MS  # total hold to fire rapid-fire

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_rapid_fire = False
        self._progress = 0.0        # cycle ring progress (0–1), set by _tick_glow
        self._charge_progress = 0.0  # hold-charge arc progress (0–1)
        self._charging = False
        self._long_press_fired = False
        self._charge_start = 0.0

        self._press_timer = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.setInterval(self._CHARGE_MS)
        self._press_timer.timeout.connect(self._on_long_press)

        self._charge_tick = QTimer(self)
        self._charge_tick.setInterval(16)  # ~60 fps
        self._charge_tick.timeout.connect(self._tick_charge)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._long_press_fired = False
            self._charge_start = time.monotonic()
            self._charging = True
            self._charge_progress = 0.0
            self._press_timer.start()
            self._charge_tick.start()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            was_long = self._long_press_fired
            self._long_press_fired = False
            self._press_timer.stop()
            elapsed_ms = (
                (time.monotonic() - self._charge_start) * 1000
                if self._charging else 0
            )
            countdown_visible = self._charging and elapsed_ms >= self._PRE_HOLD_MS
            if self._charging:
                self._charging = False
                self._charge_tick.stop()
                self._charge_progress = 0.0
                self.update()
            # Block the click signal in two cases:
            #   - long press fired (rapid-fire already toggled)
            #   - released after the visible countdown started (explicit cancel)
            if was_long or countdown_visible:
                self.blockSignals(True)
                super().mouseReleaseEvent(e)
                self.blockSignals(False)
                return
        super().mouseReleaseEvent(e)

    def _tick_charge(self):
        elapsed_ms = (time.monotonic() - self._charge_start) * 1000
        if elapsed_ms < self._PRE_HOLD_MS:
            return  # silent pre-hold: keep _charge_progress at 0, skip repaint
        countdown_elapsed = elapsed_ms - self._PRE_HOLD_MS
        self._charge_progress = min(1.0, countdown_elapsed / self._COUNTDOWN_MS)
        self.update()

    def _on_long_press(self):
        if not self.isEnabled():
            # Master flag flipped off mid-hold; suppress the rapid-fire toggle.
            self._charging = False
            self._charge_tick.stop()
            self._charge_progress = 0.0
            self._long_press_fired = False
            return
        self._charging = False
        self._charge_tick.stop()
        self._charge_progress = 0.0
        self._long_press_fired = True
        self.is_rapid_fire = not self.is_rapid_fire
        self.rapid_fire_toggled.emit(self.is_rapid_fire)
        self.update()

    def set_progress(self, val: float):
        clamped = max(0.0, min(1.0, val))
        if clamped == self._progress:
            return
        self._progress = clamped
        self.update()

    def paintEvent(self, event):
        if self.paint_scale == 1.0:
            super().paintEvent(event)          # ScalePushButton -> styled chrome
            if self._charging and self._charge_progress > 0.001:
                p = QPainter(self)
                self._paint_charge_arc(p)
                p.end()
            return
        # Pressed/animating: draw the styled chrome AND the charge arc through one
        # center-scaled painter so the whole button shrinks together.
        p = self._begin_scaled_paint()
        self._draw_button_chrome(p)
        if self._charging and self._charge_progress > 0.001:
            self._paint_charge_arc(p)
        p.end()

    def _paint_charge_arc(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        margin = 3
        rect = QRectF(margin, margin,
                      self.width() - 2 * margin,
                      self.height() - 2 * margin)
        pen = QPen(QColor("#E05252"), 3, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, 90 * 16, int(-self._charge_progress * 360 * 16))


class SetSelectorWidget(QWidget):
    """Horizontal movement-set selector — custom-painted rounded rect with edge arrows."""
    index_changed = Signal(int)

    ARROW_ZONE = 24  # px width of each clickable arrow zone

    def __init__(self, keymap_manager, parent=None):
        super().__init__(parent)
        self.keymap_manager = keymap_manager
        self._index = 0
        self._enabled = True
        self._bg = "#4A8FE7"
        self._text_color = "#ffffff"
        self._border_color = "#6AAFFF"
        self._dim_progress = 0.0
        self._display_text = "Default"
        self._hover_zone = None  # "left", "right", or None
        self._paint_scale = 1.0
        self._toon_game: str | None = None  # set by parent tab via set_toon_game()
        self._has_conflict: bool = False
        self._conflict_tooltip: str = ""

        self.setFixedHeight(32)
        self.setMinimumWidth(130)
        self.setCursor(Qt.ArrowCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._refresh_display()

    def set_paint_scale(self, scale: float):
        self._paint_scale = max(0.5, float(scale))
        self.update()

    def set_dim_progress(self, t: float) -> None:
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else float(t))
        if t != self._dim_progress:
            self._dim_progress = t
            self.update()

    def set_dimmed(self, on: bool) -> None:
        self.set_dim_progress(1.0 if on else 0.0)

    def _resolved_colors(self):
        """Effective (bg, text, border) QColors at the current _dim_progress."""
        t = self._dim_progress
        bg = lerp_color(QColor(self._bg), dim_color(QColor(self._bg)), t)
        text = lerp_color(QColor(self._text_color), dim_color(QColor(self._text_color)), t)
        border = lerp_color(QColor(self._border_color), dim_color(QColor(self._border_color)), t)
        return bg, text, border

    def set_has_conflict(self, has: bool, conflict_pairs: list[tuple[str, str]] | None = None):
        if has == self._has_conflict:
            return
        self._has_conflict = has
        if has and conflict_pairs:
            from tabs.keymap_tab import ACTION_LABELS
            pretty_pairs = [
                f"{ACTION_LABELS.get(a, a.title())} <-> {ACTION_LABELS.get(b, b.title())}"
                for (a, b) in conflict_pairs
            ]
            self._conflict_tooltip = "Keyset conflicts: " + ", ".join(pretty_pairs)
        else:
            self._conflict_tooltip = ""
        self.setToolTip(self._conflict_tooltip)
        self.update()

    def _refresh_conflict(self):
        game = self._toon_game or "ttr"
        idx = self.currentIndex()
        if not self.keymap_manager:
            self.set_has_conflict(False)
            return
        has, pairs = self.keymap_manager.has_conflicts(game, idx)
        self.set_has_conflict(has, pairs)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtGui import QFont
        bg_c, text_c, border_c = self._resolved_colors()

        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        show_arrows = self._enabled and self._count() > 1
        s = self._paint_scale
        az = max(16, int(self.ARROW_ZONE * s))
        radius = max(4, int(6 * s))

        # Fill
        p.setPen(Qt.NoPen)
        p.setBrush(bg_c)
        p.drawRoundedRect(rect, radius, radius)

        # Arrow zone hover highlights
        if show_arrows and self._hover_zone:
            highlight = QColor(255, 255, 255, 35)
            p.setBrush(highlight)
            p.setPen(Qt.NoPen)
            if self._hover_zone == "left":
                clip = QPainterPath()
                clip.addRoundedRect(rect, radius, radius)
                p.setClipPath(clip)
                p.drawRect(QRectF(1, 1, az, self.height() - 2))
                p.setClipping(False)
            elif self._hover_zone == "right":
                clip = QPainterPath()
                clip.addRoundedRect(rect, radius, radius)
                p.setClipPath(clip)
                p.drawRect(QRectF(self.width() - az - 1, 1, az, self.height() - 2))
                p.setClipping(False)

        # Border
        pen = QPen(border_c, max(1, int(2 * s)))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)

        # Center text (name only, no arrows in string)
        font = QFont()
        font.setPixelSize(max(10, int(12 * s)))
        font.setBold(True)
        p.setFont(font)
        p.setPen(text_c)
        text_rect = QRectF(az, 0, self.width() - az * 2, self.height())
        p.drawText(text_rect, Qt.AlignCenter, self._display_text)

        # Draw arrows pinned to edges
        if show_arrows:
            arrow_font = QFont()
            arrow_font.setPixelSize(max(12, int(16 * s)))
            arrow_font.setBold(True)
            p.setFont(arrow_font)

            # Arrow opacity: brighter on hover
            left_alpha = 220 if self._hover_zone == "left" else 100
            right_alpha = 220 if self._hover_zone == "right" else 100

            if self._text_color == "#ffffff":
                left_color = QColor(255, 255, 255, left_alpha)
                right_color = QColor(255, 255, 255, right_alpha)
            else:
                left_color = QColor(0, 0, 0, left_alpha)
                right_color = QColor(0, 0, 0, right_alpha)

            pad = max(4, int(4 * s))
            left_rect = QRectF(pad, 0, az - pad, self.height())
            p.setPen(left_color)
            p.drawText(left_rect, Qt.AlignCenter, S("‹", "<"))

            right_rect = QRectF(self.width() - az, 0, az - pad, self.height())
            p.setPen(right_color)
            p.drawText(right_rect, Qt.AlignCenter, S("›", ">"))

        # Conflict marker: red triangle with "!" in top-right corner
        if self._has_conflict:
            from PySide6.QtGui import QPolygon
            from PySide6.QtCore import QPoint
            scale = self._paint_scale or 1.0
            size = int(12 * scale)
            margin = int(4 * scale)
            x = self.width() - size - margin
            y = margin
            tri = QPolygon([
                QPoint(x, y + size),
                QPoint(x + size, y + size),
                QPoint(x + size // 2, y),
            ])
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#d04040"))
            p.drawPolygon(tri)
            f = QFont(self.font())
            f.setBold(True)
            f.setPixelSize(max(8, int(size * 0.7)))
            p.setFont(f)
            p.setPen(QColor("white"))
            p.drawText(x, y, size, size, Qt.AlignCenter, "!")

        p.end()

    def mousePressEvent(self, event):
        if not self._enabled or self._count() <= 1:
            return
        x = event.position().x() if hasattr(event, 'position') else event.x()
        arrow_zone = max(16, int(self.ARROW_ZONE * self._paint_scale))
        if x < arrow_zone:
            self._prev()
        elif x > self.width() - arrow_zone:
            self._next()
        # Clicking the middle does nothing

    def mouseMoveEvent(self, event):
        if not self._enabled or self._count() <= 1:
            old = self._hover_zone
            self._hover_zone = None
            if old != self._hover_zone:
                self.update()
            self.setCursor(Qt.ArrowCursor)
            self.setToolTip("Movement set for this toon")
            return

        x = event.position().x() if hasattr(event, 'position') else event.x()
        old = self._hover_zone
        arrow_zone = max(16, int(self.ARROW_ZONE * self._paint_scale))
        if x < arrow_zone:
            self._hover_zone = "left"
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Previous movement set")
        elif x > self.width() - arrow_zone:
            self._hover_zone = "right"
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Next movement set")
        else:
            self._hover_zone = None
            self.setCursor(Qt.ArrowCursor)
            self.setToolTip("Movement set for this toon")

        if old != self._hover_zone:
            self.update()

    def leaveEvent(self, event):
        if self._hover_zone:
            self._hover_zone = None
            self.update()

    def _count(self):
        if self.keymap_manager:
            return len(self.keymap_manager.get_set_names(self._toon_game or "ttr"))
        return 1

    def _prev(self):
        if not self._enabled or self._count() <= 1:
            return
        self._index = (self._index - 1) % self._count()
        self._refresh_display()
        self.index_changed.emit(self._index)

    def _next(self):
        if not self._enabled or self._count() <= 1:
            return
        self._index = (self._index + 1) % self._count()
        self._refresh_display()
        self.index_changed.emit(self._index)

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, idx: int):
        count = self._count()
        if 0 <= idx < count:
            self._index = idx
        elif idx >= count:
            self._index = 0
        self._refresh_display()
        self._refresh_conflict()

    def currentText(self) -> str:
        if self.keymap_manager:
            names = self.keymap_manager.get_set_names(self._toon_game or "ttr")
            if self._index < len(names):
                return names[self._index]
        return ""

    def count(self) -> int:
        return self._count()

    def findText(self, text: str) -> int:
        if self.keymap_manager:
            names = self.keymap_manager.get_set_names(self._toon_game or "ttr")
            for i, name in enumerate(names):
                if name == text:
                    return i
        return -1

    def setEnabled(self, enabled: bool):
        self._enabled = enabled
        self._refresh_display()

    def rebuild(self):
        count = self._count()
        if self._index >= count:
            self._index = 0
        self._refresh_display()

    def _refresh_display(self):
        names = self.keymap_manager.get_set_names(self._toon_game or "ttr") if self.keymap_manager else ["Default"]
        name = names[self._index] if self._index < len(names) else "Default"
        self._display_text = name
        self.apply_colors()

    def set_toon_game(self, game: str | None):
        """Update which game this toon's set list comes from."""
        if game == self._toon_game:
            return
        self._toon_game = game
        self._rebuild_for_game()

    def _rebuild_for_game(self):
        """Re-fetch the set names from KeymapManager scoped to the current game,
        and clamp the selected index if the list shrank."""
        game = self._toon_game or "ttr"
        names = self.keymap_manager.get_set_names(game) if self.keymap_manager else ["Default"]
        prev = self.currentIndex()
        if prev >= len(names):
            prev = 0
        if self.currentIndex() != prev:
            self.setCurrentIndex(prev)
        else:
            self._refresh_display()
        self.update()  # repaint
        self._refresh_conflict()

    def apply_colors(self, theme_colors=None):
        bg, text = get_set_color(self._index)

        if not self._enabled:
            from utils.theme_manager import is_dark_palette, get_theme_colors
            c = theme_colors or get_theme_colors(is_dark_palette())
            bg = c["btn_bg"]
            text = c["text_disabled"]
            border_color = c["btn_border"]
        else:
            base = QColor(bg)
            border_color = base.lighter(135).name()

        self._bg = bg
        self._text_color = text
        self._border_color = border_color
        self.update()


# ── Main Tab ───────────────────────────────────────────────────────────────


def compute_effective_chat_enabled(
    mode: str,
    raw_chat: list[bool],
    enabled_toons: list[bool],
    assignments: list[int],
) -> list[bool]:
    """Compute per-toon effective chat-broadcast state.

    Expects an already-normalized mode (use normalize_chat_handling_mode
    before calling). The four canonical modes behave as follows:

    - per_toon:       returns raw_chat verbatim, length-normalized to
                      len(enabled_toons); downstream InputService callers
                      never read past the end of raw_chat.
    - all_toons:      every enabled toon broadcasts chat (disabled -> False),
                      regardless of keyset assignment or raw_chat.
    - focused_only:   all False; chat is handled by the game's own focused
                      window, not broadcast by TTMT.
    - keyset_dynamic: (default / fallback) each toon is True iff the toon is
                      enabled AND its assigned keyset index is 0. Assignments
                      shorter than enabled_toons treat missing indices as
                      non-default keyset (chat off).

    Result length always equals len(enabled_toons).

    See: docs/superpowers/specs/2026-06-09-chat-handling-logic-dropdown-design.md
    """
    from utils.settings_keys import (
        CHAT_HANDLING_PER_TOON,
        CHAT_HANDLING_ALL_TOONS,
        CHAT_HANDLING_FOCUSED_ONLY,
    )
    n = len(enabled_toons)
    if mode == CHAT_HANDLING_PER_TOON:
        return [bool(raw_chat[i]) if i < len(raw_chat) else False for i in range(n)]
    if mode == CHAT_HANDLING_ALL_TOONS:
        return [bool(enabled_toons[i]) for i in range(n)]
    if mode == CHAT_HANDLING_FOCUSED_ONLY:
        return [False] * n
    return [
        bool(enabled_toons[i]) and i < len(assignments) and assignments[i] == 0
        for i in range(n)
    ]


# Net-new keep-alive orange (the theme's accent_orange #c47a2a reads too brown
# for this surface). Pairs with a lighter border tint. Used by the pinwheel
# layout's lightning toggle + progress fill.
KA_ORANGE = "#ff9500"
KA_ORANGE_BORDER = "#ffb04d"


def _pin_toggle_qss(accent: str, on: bool) -> str:
    """QSS for a 34x36 pinwheel toggle button. Active fills with the toggle's
    accent; inactive is a recessed dark chip. Icon colour is set separately
    (QSS can't tint a QIcon). Both states brighten on hover."""
    if on:
        hov = lighten_rgb(QColor(accent), 0.15).name()
        return (
            f"QPushButton {{ background: {accent}; border: 1px solid {accent};"
            f" border-radius: 9px; }}"
            f"QPushButton:hover {{ background: {hov}; border: 1px solid {hov}; }}"
        )
    return (
        "QPushButton { background: rgba(0,0,0,0.24);"
        " border: 1px solid rgba(0,0,0,0.30); border-radius: 9px; }"
        "QPushButton:hover { background: rgba(255,255,255,0.10); }"
        "QPushButton:disabled { background: rgba(0,0,0,0.30);"
        " border: 1px solid rgba(0,0,0,0.30); }"
    )


def _pin_ka_off_qss() -> str:
    """QSS for the 28px keep-alive lightning toggle in its off state."""
    return (
        "QPushButton { background: rgba(0,0,0,0.35);"
        " border: 1px solid rgba(255,255,255,0.16); border-radius: 14px; }"
        "QPushButton:hover { background: rgba(255,255,255,0.10);"
        " border: 1px solid rgba(255,255,255,0.28); }"
        "QPushButton:disabled { background: rgba(0,0,0,0.35);"
        " border: 1px solid rgba(255,255,255,0.10); }"
    )


def _pin_ka_on_qss(fill: str, border: str) -> str:
    """QSS for the keep-alive lightning toggle in its on state (orange/red),
    brightening on hover."""
    hov = lighten_rgb(QColor(fill), 0.15).name()
    hov_b = lighten_rgb(QColor(border), 0.15).name()
    return (
        f"QPushButton {{ background: {fill}; border: 1px solid {border};"
        f" border-radius: 14px; }}"
        f"QPushButton:hover {{ background: {hov}; border: 1px solid {hov_b}; }}"
    )


def _ka_fill_border(is_rf: bool, progress: float) -> tuple[str, str]:
    """Keep-alive ON-state (fill, border) hex names, cross-faded lit->dim by
    `progress` in [0,1]. 0 = lit, 1 = full dim_color."""
    lit_fill = QColor("#E05252") if is_rf else QColor(KA_ORANGE)
    lit_border = QColor("#ef8d8d") if is_rf else QColor(KA_ORANGE_BORDER)
    fill = lerp_color(lit_fill, dim_color(lit_fill), progress).name()
    border = lerp_color(lit_border, dim_color(lit_border), progress).name()
    return fill, border


def _pin_cs_chip_qss(border: str) -> str:
    """QSS for the mouse-sync button's dark-chip states (armed/error): a recessed
    chip with a coloured ring, brightening on hover like the off chip."""
    return (
        f"QPushButton {{ background: rgba(0,0,0,0.24);"
        f" border: 1px solid {border}; border-radius: 9px; }}"
        f"QPushButton:hover {{ background: rgba(255,255,255,0.10); }}"
    )


class MultitoonTab(QWidget):
    _toon_names_ready  = Signal(list)
    _toon_styles_ready = Signal(list)
    _toon_colors_ready = Signal(list)
    _toon_laffs_ready  = Signal(list)
    _toon_max_laffs_ready = Signal(list)
    _toon_beans_ready  = Signal(list)
    _toon_data_merge_ready = Signal(list, list, list, list, list, list, list)
    _cc_toon_info_ready = Signal(list, list)  # (window_ids, list[CCToonInfo | None])
    keep_alive_updated = Signal()
    dot_state_changed = Signal(int, str)
    keep_alive_help_requested = Signal()
    keep_alive_inhibit_status = Signal(object)  # InhibitStatus, for warning + indicator
    launch_tab_requested = Signal()

    # Re-entrancy debounce for manual_refresh(): requests within this many
    # seconds of the last accepted refresh are coalesced, so a held/mashed F5 or
    # rapid Refresh clicks cannot stack the heavy InputService restart. A plain
    # monotonic-time comparison, so it can never wedge regardless of fetch
    # lifecycle. Chosen to exceed the ~1200ms delayed toon-data fetch timer.
    _REFRESH_COOLDOWN_S = 1.5

    def __init__(self, logger=None, settings_manager=None, keymap_manager=None, profile_manager=None, window_manager=None):
        super().__init__()
        self.logger = logger
        self.settings_manager = settings_manager
        self.keymap_manager = keymap_manager
        self.profile_manager = profile_manager
        self.window_manager = window_manager
        # Service implicitly on per the Direction D redesign - the new
        # ServiceStatusBar's play/stop button is the only explicit
        # toggle. Idle state (grey bar) is shown when service is on but
        # no toons are enabled.
        self.service_running = True
        self._last_refresh_monotonic = float("-inf")
        self.toon_labels = []       # list of (name_label, status_dot)
        self.laff_labels = []       # list of QLabels showing laff
        self.bean_labels = []       # list of QLabels showing beans
        self.slot_badges = []       # list of QLabel badges
        self.game_badges = []       # list of QLabel game badges
        self.toon_buttons = []
        self.chat_buttons = []
        self.click_sync_buttons = []
        # Click sync visual state (single style-writer resolver; spec:
        # 2026-06-10-click-sync-button-styling-design.md).
        self._click_sync_states = {i: "off" for i in range(4)}
        self._click_sync_icons = {}
        self._click_sync_error_tip = None
        # Per-slot cached "game type supports chat button" intent. Updated by
        # CC/TTR paint paths via _set_chat_button_visible. Read by
        # apply_chat_handling_mode when the global mode flips so visibility
        # respects both the per-slot game intent and the global Chat Handling
        # mode (buttons show only in per_toon; other modes hide regardless).
        self._chat_button_game_wants_visible = [True] * 4
        self.keep_alive_buttons = []
        self.ka_progress_bars = []
        self.help_buttons = []
        self.ka_groups = []
        self.set_selectors = []     # replaces movement_dropdowns
        self.toon_cards = []
        self.profile_pills = []     # list of QPushButton pills
        self._compact_cc_subtitles: list[QLabel] = []
        self.enabled_toons = [False] * 4
        self.chat_enabled  = [True]  * 4
        self.keep_alive_enabled = [False] * 4
        self.rapid_fire_enabled = [False] * 4
        self.toon_names       = [None] * 4
        self._cc_toon_infos   = [None] * 4
        self.toon_styles      = [None] * 4
        self.toon_colors      = [None] * 4
        self.toon_laffs       = [None] * 4
        self.toon_max_laffs   = [None] * 4
        self.toon_beans       = [None] * 4
        self._refresh_gen     = 0
        self._toon_fetch_inflight_keys = set()
        self._active_profile  = -1  # no profile active initially
        self._last_window_ids = []
        self.customizations = ToonCustomizationsManager()

        self._keep_alive_running = False
        self._keep_alive_thread = None
        self._ka_cycle_start = 0.0
        self._ka_cycle_event = threading.Event()
        self._overlay_active = False  # True while the transparent-mode cluster is up
        self._sleep_inhibitor = SleepInhibitor()
        self._inhibit_worker = None
        self._inhibit_gen = 0
        self._retired_workers = []  # still-running workers kept alive to finish

        self.key_event_queue = queue.Queue(maxsize=200)

        self.build_ui()

        self.input_service = InputService(
            window_manager=self.window_manager,
            get_enabled_toons=self.get_enabled_toons,
            get_movement_modes=self.get_movement_modes,
            get_event_queue_func=self.get_key_event_queue,
            get_chat_enabled=self.get_chat_enabled,
            settings_manager=settings_manager,
            get_keymap_assignments=self.get_keymap_assignments,
            keymap_manager=self.keymap_manager,
            get_chat_handling_mode=self.get_chat_handling_mode,
        )
        # Default to TTR for foreground-game cache if no game window has been focused yet.
        self.input_service._last_known_foreground_game = "ttr"
        self.input_service.chat_state_changed.connect(self._on_chat_state_changed)
        self.input_service.input_log.connect(self._on_input_log)
        self.input_service.uipi_blocked_movement_detected.connect(self._on_uipi_blocked)
        self.click_sync_service = None
        self._click_sync_backend = None
        self._build_click_sync()
        self._chat_glow_active = False
        self.window_manager.window_ids_updated.connect(self.update_toon_controls)
        if hasattr(self.window_manager, "cell_assignment_changed"):
            self.window_manager.cell_assignment_changed.connect(
                self._on_cell_assignment_changed
            )
        self._toon_names_ready.connect(self._apply_toon_names)
        self._toon_styles_ready.connect(self._apply_toon_styles)
        self._toon_colors_ready.connect(self._apply_toon_colors)
        self._toon_laffs_ready.connect(self._apply_toon_laffs)
        self._toon_max_laffs_ready.connect(self._apply_toon_max_laffs)
        self._toon_beans_ready.connect(self._apply_toon_beans)
        self._toon_data_merge_ready.connect(self._apply_merged_toon_data)
        self._cc_toon_info_ready.connect(self._apply_cc_toon_info)

        self._toon_capture_sink = None   # set by the coordinator: callable(pid, toon_name, dna)
        # Per-window dedup of the last captured (toon_name, dna) so an unchanged
        # toon skips the synchronous pid_for_window X round-trip + sink call.
        self._last_captured_toon: dict[str, tuple[str, str]] = {}

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(5000)
        self.refresh_timer.timeout.connect(self._auto_refresh)

        self._toon_fetch_timer = QTimer(self)
        self._toon_fetch_timer.setSingleShot(True)
        self._toon_fetch_timer.timeout.connect(self._run_scheduled_toon_fetch)

        # Glow animation timer (shared by keep-alive buttons + service button)
        self._glow_phase = 0.0
        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(50)
        self._glow_timer.timeout.connect(self._tick_glow)

        # Smooth progress bar timer (60fps, independent of glow)
        self._bar_timer = QTimer(self)
        self._bar_timer.setInterval(16)
        self._bar_timer.timeout.connect(self._tick_progress_bars)

        # Listen for keymap changes to refresh dropdowns
        if self.keymap_manager:
            self.keymap_manager.on_change(self._rebuild_set_selectors)
            self.keymap_manager.on_change(self._refresh_all_set_selectors_conflict)

        # Listen for settings changes to reset keep-alive cycle
        if self.settings_manager:
            self.settings_manager.on_change(self._on_setting_changed)

        self.refresh_theme()
        self.apply_all_visual_states()

        # Auto-start the service per the Direction D implicit-on design.
        # Mirror the legacy toggle_service() path so launch behaves the
        # same as Stop+Play: enable detection, then call
        # _start_service_internal which both starts the input service
        # AND auto-enables any toons whose windows are already detected.
        # Without the auto-enable, launch ends up with detected-but-
        # not-enabled toons (stripes muted) while Stop+Play ends up with
        # detected-AND-enabled toons (stripes full) - confusing
        # inconsistency.
        self.input_service.window_manager.enable_detection()
        self._start_service_internal()
        self.update_service_button_style()

    # ── UI Construction ────────────────────────────────────────────────────

    def _build_shared_widgets(self):
        """Construct every per-slot widget once. Both Compact and Full layouts
        consume the resulting dict-of-lists so widget state survives a layout swap."""
        # Service status bar - 3-state (broadcasting/idle/stopped) with
        # inline stop/play and refresh. Replaces the legacy
        # toggle_service_button + StatusBar + section_divider trio.
        from tabs.multitoon._service_status_bar import ServiceStatusBar
        self.service_status_bar = ServiceStatusBar()
        self.service_status_bar.stop_requested.connect(self._on_service_stop_requested)
        self.service_status_bar.play_requested.connect(self._on_service_play_requested)
        self.service_status_bar.refresh_requested.connect(self._on_refresh_requested)

        # Compatibility alias for the WHOLE bar widget - shared between
        # Compact and Full layouts (Full uses it as its status display).
        # Qt reparents the bar as a unit so this is safe.
        self.status_bar = self.service_status_bar

        # Full-UI-only service toggle and refresh. Compact uses the
        # ServiceStatusBar's internal stop/play + refresh instead. These
        # are kept as independent widgets so Full can addWidget them
        # without stealing children from the bar.
        self.toggle_service_button = QPushButton(f"{S(chr(9654), chr(9654))} Start Service")
        self.toggle_service_button.setCheckable(True)
        self.toggle_service_button.clicked.connect(self.toggle_service)
        self.toggle_service_button.setFixedHeight(48)

        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(make_refresh_icon(14))
        self.refresh_button.setFixedSize(26, 26)
        self.refresh_button.clicked.connect(self.manual_refresh)

        # Toon config row widgets
        self.config_label = QLabel("TOON CONFIGURATION")
        for i in range(5):
            pill = QPushButton(str(i + 1))
            pill.setFixedSize(28, 28)
            pill.setToolTip(f"Load Profile {i+1} (Ctrl+{i+1})")
            pill.clicked.connect(lambda checked, idx=i: self.load_profile(idx))
            self.profile_pills.append(pill)

        # Profile save button - chrome only for now (behaviour pending the
        # save-mechanics decision in the spec's "Deferred decisions"
        # section). Sized to match the profile pill height for visual
        # consistency.
        from utils.icon_factory import make_save_icon
        from PySide6.QtCore import QSize
        self.profile_save_button = QPushButton()
        self.profile_save_button.setIcon(make_save_icon(14))
        self.profile_save_button.setIconSize(QSize(14, 14))
        self.profile_save_button.setFixedSize(28, 28)
        self.profile_save_button.setObjectName("profile_save_button")
        self.profile_save_button.setToolTip("Save profile (behavior pending)")
        self.profile_save_button.clicked.connect(self._on_profile_save_clicked)

        # Profile-row label — sits just before the round 1-5 pills so the
        # affordance reads as "profile presets" rather than unattributed
        # numeric chips. Reused across compact and full layouts.
        self.profile_pills_label = QLabel("PROFILE")
        self.profile_pills_label.setObjectName("profile_pills_label")

        # Per-slot widgets
        for i in range(4):
            badge = ToonPortraitWidget(i + 1)
            badge.clicked.connect(lambda idx=i: self._on_portrait_clicked(idx))
            self.slot_badges.append(badge)
            badge.set_customizations_manager(self.customizations)
            badge.set_game(None)
            badge.edit_icon_requested.connect(
                lambda idx=i: self._open_customization_dialog(idx)
            )

            cc_subtitle = QLabel("")
            cc_subtitle.setObjectName("cc_compact_subtitle")
            cc_subtitle.setStyleSheet(
                "color: #9a9aa8; font-size: 14px; font-style: normal; "
                "background: transparent; border: none;"
            )
            cc_subtitle.hide()
            self._compact_cc_subtitles.append(cc_subtitle)

            name_label = ElidingLabel(f"Toon {i + 1}")
            status_dot = PulsingDot(13)
            status_dot.setToolTip("Not Found")
            self.toon_labels.append((name_label, status_dot))

            game_badge = QLabel()
            game_badge.setObjectName("game_badge")
            game_badge.setAlignment(Qt.AlignCenter)
            game_badge.hide()
            self.game_badges.append(game_badge)

            laff_lbl = QPushButton(" ---")
            laff_lbl.setIcon(make_heart_icon(16))
            laff_lbl.setObjectName("laff_lbl")
            laff_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            laff_lbl.setToolTip("Laff")
            # Reserve the stats-row height even while hidden, so the card is a
            # CONSISTENT size whether or not toon data has loaded. Without this the
            # row collapses pre-data and the card grows ~one row taller when stats
            # arrive - which clips a card sized before its data (e.g. entering
            # transparent mode before the API responds).
            _laff_sp = laff_lbl.sizePolicy()
            _laff_sp.setRetainSizeWhenHidden(True)
            laff_lbl.setSizePolicy(_laff_sp)
            laff_lbl.hide()
            self.laff_labels.append(laff_lbl)

            bean_lbl = QPushButton(" ---")
            bean_lbl.setIcon(make_jellybean_icon(16))
            bean_lbl.setObjectName("bean_lbl")
            bean_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            bean_lbl.setToolTip("Bank Jellybeans")
            _bean_sp = bean_lbl.sizePolicy()
            _bean_sp.setRetainSizeWhenHidden(True)
            bean_lbl.setSizePolicy(_bean_sp)
            bean_lbl.hide()
            self.bean_labels.append(bean_lbl)

            btn = ScalePushButton("Enable")
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.setFixedWidth(88)
            btn.setToolTip("Enable input broadcasting for this toon")
            btn.clicked.connect(lambda checked, idx=i: self.toggle_toon(idx))
            self.toon_buttons.append(btn)

            ka_btn = KeepAliveBtn()
            ka_btn.setCheckable(True)
            ka_btn.setChecked(False)
            ka_btn.setFixedHeight(32)
            ka_btn.setFixedWidth(32)
            ka_btn.setIcon(make_lightning_icon(14))
            ka_btn.setToolTip("Toggle keep-alive for this toon")
            ka_btn.clicked.connect(lambda checked, idx=i: self.toggle_keep_alive(idx))
            ka_btn.rapid_fire_toggled.connect(lambda state, idx=i: self.toggle_rapid_fire(idx, state))
            self.keep_alive_buttons.append(ka_btn)

            chat_btn = ScalePushButton()
            chat_btn.setCheckable(True)
            chat_btn.setChecked(True)
            chat_btn.setFixedHeight(32)
            chat_btn.setFixedWidth(32)
            chat_btn.setIcon(make_chat_icon(14))
            chat_btn.setToolTip("Toggle chat broadcasting for this toon")
            chat_btn.clicked.connect(lambda checked, idx=i: self.toggle_chat(idx))
            self.chat_buttons.append(chat_btn)

            cs_btn = ScalePushButton()
            cs_btn.setCheckable(True)
            cs_btn.setChecked(False)
            cs_btn.setFixedHeight(32)
            cs_btn.setFixedWidth(32)
            cs_btn.setIcon(make_click_sync_icon(14))
            cs_btn.setToolTip("Click sync: mirror clicks to this toon")
            cs_btn.clicked.connect(lambda checked, idx=i: self.toggle_click_sync(idx))
            cs_btn.setVisible(False)  # gated by the Settings master switch
            self.click_sync_buttons.append(cs_btn)

            ka_bar = SmoothProgressBar()
            self.ka_progress_bars.append(ka_bar)

            help_btn = KeepAliveHelpButton()
            help_btn.help_requested.connect(self.keep_alive_help_requested.emit)
            self.help_buttons.append(help_btn)

            selector = SetSelectorWidget(self.keymap_manager)
            selector.setFixedHeight(28)
            selector.setToolTip("Movement set for this toon")
            selector.index_changed.connect(lambda _, idx=i: self._autosave_active_profile())
            self.set_selectors.append(selector)

        # Initial classification — `apply_visual_state` will update as windows resolve.
        for sel in self.set_selectors:
            sel.set_toon_game(None)

    def build_ui(self):
        from tabs.multitoon._compact_layout import _CompactLayout
        from tabs.multitoon._full_layout import _FullLayout

        self._build_shared_widgets()

        # Build both layouts. Each runs populate() in its __init__, so whichever
        # is built second steals widget ownership. We then call _compact.populate()
        # one more time so Compact wins for the initial view.
        self._stack = QStackedWidget(self)
        self._compact = _CompactLayout(self)
        self._full = _FullLayout(self)
        self._compact.populate()  # re-claim ownership for the default view
        self._stack.addWidget(self._compact)
        self._stack.addWidget(self._full)
        self._stack.setCurrentWidget(self._compact)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._stack)

        self._mode = "compact"
        self.update_service_button_style()
        self.update_status_label()

        # Apply initial KA widget visibility based on master setting.
        self._init_keep_alive_visibility()

    def set_layout_mode(self, mode: str) -> None:
        # The Multitoon tab uses a single fluid pinwheel layout at every window
        # size, so it ignores the window-size breakpoint that the main window
        # applies to the Launcher and Settings tabs. The pinwheel ("compact")
        # is always active; this is a no-op so a window grown past the
        # breakpoint never swaps the Multitoon tab to the retired full layout.
        return

    def _legacy_set_layout_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        # Cancel any in-flight KA animations BEFORE swapping layouts. The
        # animation's finished handlers may try to setVisible/setGraphicsEffect
        # on widgets that are about to be reparented; stopping early prevents
        # unwanted state from landing on the new layout.
        self._cancel_keep_alive_animations()

        # Leaving Full — stop card-level animations BEFORE flipping the mode flag.
        if self._mode == "full" and hasattr(self, "_full") and self._full is not None:
            self._full.deactivate()
        target = self._full if mode == "full" else self._compact
        self._mode = mode
        target.populate()
        self._stack.setCurrentWidget(target)
        # Compact widgets are kept in sync by apply_visual_state calls on
        # service/window events, so a layout swap doesn't need a full
        # apply_all_visual_states. Only the Full UI cards need syncing —
        # while in Compact mode, set_active and set_status_state on the Full
        # cards were gated out, so they're stale until we sync. apply_theme
        # is the entry point for layout-specific theme styling on Full cards.
        # Pinned by tests/test_light_full_card_theme.py — that test asserts
        # the light-mode card_toon_bg lands on the card after a compact->full
        # swap with theme=light.
        if mode == "full" and self._full is not None:
            self._full.apply_theme(self._c())
            self._sync_full_cards_to_state()
        else:
            # Compact and Full share the same name_label/laff_label/bean_label
            # widgets. Full's apply_theme set Full-scaled stylesheets on them
            # (28px name, 16px stat); Compact's populate only resets layout/
            # QFonts, not stylesheets. Re-issue Compact's stylesheets so the
            # shared widgets render at Compact sizes again.
            self.refresh_theme()
            # populate() reset compact to identity routing; re-apply the current
            # position-based permutation so content lands in the cell matching
            # each window's on-screen quadrant (no-op for contiguous layouts).
            self._compact.apply_cell_permutation(
                getattr(self.window_manager, "slot_cells", [0, 1, 2, 3])
            )

        # Re-apply per-toon visual state on every slot now that the
        # parent chain has changed (compact stack vs full's
        # QGraphicsProxyWidget tree). apply_visual_state is the public
        # orchestrator — it dispatches to _apply_chat_btn_style and
        # _apply_keep_alive_btn_style only when a window is available;
        # it also calls _set_widget_opacity for chat / enable / selector
        # which lets the proxy-detect path in _set_widget_opacity clear
        # any stale QGraphicsOpacityEffect carried over from the prior
        # mode. Do NOT call _apply_chat_btn_style / _apply_keep_alive_
        # btn_style directly here: they unconditionally setEnabled(True)
        # and apply the active-state QSS, which would override the
        # correctly-disabled state apply_visual_state produces in the
        # no-window branch.
        # Resize the shared PulsingDot status indicators to the
        # mode's target size. Compact uses 13 (the historical
        # construction value); full uses 26 to match the enlarged
        # portrait (130/64 * 13 ≈ 26). PulsingDot.set_size handles
        # the QWidget sizing and triggers a repaint.
        dot_size = 26 if mode == "full" else 13
        for i in range(4):
            if i < len(self.toon_labels):
                _, status_dot = self.toon_labels[i]
                status_dot.set_size(dot_size)
        for i in range(4):
            self.apply_visual_state(i)

        # After the swap, reconcile visibility (no animation — the swap
        # itself is an instant snap per the existing layout-swap convention).
        self._reconcile_keep_alive_visibility_instant()

    def prewarm_full_layout(self, size=None, include_active: bool = False) -> None:
        """Pay Full UI's first polish/paint cost while Compact remains visible."""
        wids = self.window_manager.ttr_window_ids if hasattr(self, "window_manager") else []
        warm_key = "active" if wids else "inactive"
        if warm_key == "active" and not include_active:
            return
        warmed = getattr(self, "_full_layout_prewarmed_states", set())
        if warm_key in warmed:
            return
        if not hasattr(self, "_full") or self._full is None:
            return
        if self._mode != "compact":
            return

        self._full_layout_prewarmed_states = warmed | {warm_key}
        current = None
        try:
            from PySide6.QtGui import QPixmap

            current = self._stack.currentWidget()
            c = self._c()
            self._mode = "full"
            warm_size = size if size is not None else self.size()
            # Floor: 1280×744 = the 2x2 card design reference (two 632×360
            # cards + 24 px gap). Prewarm at this size regardless of the
            # current H_FULL trigger so Qt caches polish/paint at the size
            # most users will see once they've sized the window beyond the
            # trigger threshold.
            if warm_size.width() <= 0 or warm_size.height() <= 0:
                warm_size = QSize(1280, 744)
            else:
                warm_size = QSize(max(warm_size.width(), 1280), max(warm_size.height(), 744))
            self._full.resize(warm_size)
            self._full.populate()
            self._full.apply_theme(c)
            self._sync_full_cards_to_state()
            self._full.ensurePolished()
            self._full._position_cards()

            render_size = self._full.size()
            if render_size.width() > 0 and render_size.height() > 0:
                pixmap = QPixmap(render_size)
                pixmap.fill(Qt.transparent)
                self._full.render(pixmap)
        finally:
            # Cancel any in-flight KA animations BEFORE deactivate/populate —
            # animation finish handlers may land on widgets being reparented.
            self._cancel_keep_alive_animations()
            self._full.deactivate()
            self._compact.populate()
            self._stack.setCurrentWidget(current or self._compact)
            self._mode = "compact"
            # Full's apply_theme set name_label/laff/bean stylesheets at Full's
            # scaled font sizes (28px name, 16px stat). Compact's populate only
            # resets layout/sizing — not stylesheets — so without this the
            # polluted styles linger until something else triggers a refresh.
            self.refresh_theme()
            # Reconcile KA widget visibility for the post-prewarm compact state.
            # The Full UI populate may have left widgets in inconsistent state
            # if master toggled mid-prewarm.
            self._reconcile_keep_alive_visibility_instant()

    def _sync_full_cards_to_state(self) -> None:
        """No-op shell. Full-mode cards are structural clones of
        compact's; per-toon state lives on the shared widgets (chat
        buttons, KA buttons, slot badges, etc.) and propagates the
        same way as compact. Kept as a method so prewarm_full_layout
        can call it without conditionals."""
        return

    # ── Set selector rebuild ───────────────────────────────────────────────

    # ── Profile methods ────────────────────────────────────────────────────

    def load_profile(self, index: int):
        """Load a profile by index and mark it active."""
        if not self.profile_manager:
            return
        # Save current profile state before switching away
        self._autosave_active_profile()
        profile = self.profile_manager.get_profile(index)
        self._active_profile = index

        enabled = profile.enabled_toons
        modes = profile.movement_modes

        for i in range(4):
            state = enabled[i] if i < len(enabled) else False
            self.enabled_toons[i] = state
            self.toon_buttons[i].setChecked(state)
            self.chat_enabled[i] = state
            self.chat_buttons[i].setChecked(state)

        for i, selector in enumerate(self.set_selectors):
            mode = modes[i] if i < len(modes) else "Default"
            idx = selector.findText(mode)
            if idx >= 0:
                selector.setCurrentIndex(idx)

        ka_states = profile.keep_alive or [False] * 4
        rf_states = profile.rapid_fire or [False] * 4
        for i in range(4):
            self.keep_alive_enabled[i] = ka_states[i] if i < len(ka_states) else False
            self.rapid_fire_enabled[i] = rf_states[i] if i < len(rf_states) else False
            self.keep_alive_buttons[i].setChecked(self.keep_alive_enabled[i])
            self.keep_alive_buttons[i].is_rapid_fire = self.rapid_fire_enabled[i]
            self._apply_keep_alive_btn_style(i, self._c())

        if any(self.keep_alive_enabled) and self._keep_alive_globally_enabled():
            self._start_keep_alive()
        else:
            self._stop_keep_alive()

        self.apply_all_visual_states()
        self.update_status_label()
        self._update_pill_styles()
        self.log(f"[Profile] Loaded '{self.profile_manager.get_name(index)}'")

    def _autosave_active_profile(self):
        """Persist current state to the active profile if one is selected."""
        if self._active_profile < 0 or not self.profile_manager:
            return
        self.profile_manager.save_profile(
            self._active_profile,
            list(self.enabled_toons),
            self.get_movement_modes(),
            keep_alive=list(self.keep_alive_enabled),
            rapid_fire=list(self.rapid_fire_enabled),
        )

    def refresh_profile_pills(self):
        """Re-read profile names from manager and update pill labels."""
        if not self.profile_manager:
            return
        names = self.profile_manager.get_all_names()
        for i, pill in enumerate(self.profile_pills):
            pill.setText(names[i] if i < len(names) else f"Profile {i+1}")
            pill.setToolTip(f"Load {pill.text()} (Ctrl+{i+1})")
        self._update_pill_styles()

    def _update_pill_styles(self):
        if not hasattr(self, 'profile_pills'):
            return
        c = self._c()
        pill_colors = ["#4A8FE7", "#E05252", "#E8A838", "#56c856", "#C87EE8"]
        for i, pill in enumerate(self.profile_pills):
            active = i == self._active_profile
            color = pill_colors[i] if i < len(pill_colors) else c['accent_blue_btn']
            
            if active:
                base_color = QColor(color)
                border_color = base_color.lighter(120).name()
                hover_color = base_color.lighter(110).name()
                pill.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {color};
                        color: white;
                        border: 2px solid {border_color};
                        border-radius: 14px;
                        font-size: 11px;
                        font-weight: bold;
                        padding: 0px;
                        margin: 0px;
                        text-align: center;
                    }}
                    QPushButton:hover {{
                        background-color: {hover_color};
                    }}
                """)
            else:
                pill.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c['btn_bg']};
                        color: {c['text_secondary']};
                        border: 1px solid {c['border_muted']};
                        border-radius: 14px;
                        font-size: 11px;
                        padding: 0px;
                        margin: 0px;
                        text-align: center;
                    }}
                    QPushButton:hover {{
                        background-color: {c['toon_btn_inactive_hover']};
                        color: {c['text_primary']};
                        border: 1px solid {color};
                    }}
                """)

    def _on_profile_save_clicked(self) -> None:
        """Stub - profile save behaviour is deferred (see spec
        2026-05-24-multitoon-tab-compact-redesign-design.md "Deferred
        decisions"). Logs and no-ops for now."""
        if self.logger:
            self.logger.log("[multitoon] profile save clicked (no-op stub)")

    def _rebuild_set_selectors(self):
        """Refresh selectors when keymap sets change."""
        if not self.keymap_manager:
            return
        for selector in self.set_selectors:
            selector.rebuild()

    def _refresh_all_set_selectors_conflict(self):
        for sel in getattr(self, "set_selectors", []):
            sel._refresh_conflict()

    # ── Theme helpers ──────────────────────────────────────────────────────

    def _c(self):
        return get_theme_colors(resolve_theme(self.settings_manager) == "dark")

    def _slot_colors(self, c):
        return [c['slot_1'], c['slot_2'], c['slot_3'], c['slot_4']]

    def refresh_theme(self):
        c = self._c()
        is_dark = resolve_theme(self.settings_manager) == "dark"
        self._click_sync_icons = {}  # palette changed: rebuild tinted icons

        self.config_label.setStyleSheet(
            f"font-size: 10px; font-weight: 600; color: {c['text_muted']}; "
            f"background: transparent; border: none; letter-spacing: 0.8px; margin-top: 4px;"
        )
        if hasattr(self, "profile_pills_label"):
            self.profile_pills_label.setStyleSheet(
                f"font-size: 10px; font-weight: 600; "
                f"color: {c['text_muted']}; letter-spacing: 0.8px;"
            )
        # CC subtitle (Compact-only) tracks the theme's muted text color.
        for sub in getattr(self, "_compact_cc_subtitles", []):
            sub.setStyleSheet(
                f"color: {c['text_muted']}; font-size: 10px; "
                f"font-style: italic; background: transparent; border: none;"
            )
        self._update_pill_styles()

        # ServiceStatusBar manages its own per-state QSS + dot palette;
        # we just hand it the current theme.
        self.status_bar.apply_theme(c)
        self.update_service_button_style()

        # Pinwheel cells are transparent: their visible chrome (the concave
        # gradient body + accent border + glow) is painted by the layout, and
        # the name/stats fonts + colours are owned by set_card_brand. Keep the
        # cell frames clear so the painted background shows through.
        for card in self.toon_cards:
            obj = card.objectName() or "QFrame"
            card.setStyleSheet(f"#{obj} {{ background: transparent; border: none; }}")

        # Progress bar track color
        for ka_bar in self.ka_progress_bars:
            ka_bar.set_bg_color("#0d0d0d")

        for help_btn in self.help_buttons:
            help_btn.refresh_theme(c)

        self.apply_all_visual_states()

        # Re-assert per-slot card brand so body-derived border colors
        # survive the theme-wide pass above. Pattern mirrors the existing
        # rebrand loop at the apply_all_visual_states call site.
        if self._mode == "compact":
            for i in range(len(self.toon_cards)):
                if i >= len(self.slot_badges):
                    continue
                game = self.slot_badges[i].game
                enabled = bool(
                    i < len(self.enabled_toons)
                    and self.enabled_toons[i]
                    and self.service_running
                )
                self._set_card_brand_for_slot(i, game, enabled=enabled)

        # Apply theme to the *active* layout only. Compact's per-card colors
        # ran above (the toon_cards loop). Full has its own apply_theme entry
        # point that re-applies card frames, status indicators, game pills,
        # and Full-specific name-label styling. We skip _full.apply_theme()
        # while Compact is showing so its styling doesn't bleed into hidden
        # widgets that Compact expects to look different.
        if self._mode == "full" and hasattr(self, "_full") and self._full is not None:
            self._full.apply_theme(c)

        # Click sync buttons: restyle with the new palette (cache was
        # cleared at the top of this method, so icons rebuild tinted).
        for i in range(len(self.click_sync_buttons)):
            self._apply_click_sync_btn_style(i, c)

        self.update_status_label()

    # ── Visual state per toon ──────────────────────────────────────────────

    def apply_visual_state(self, index):
        c = self._c()
        btn      = self.toon_buttons[index]
        selector = self.set_selectors[index]
        wids = self.window_manager.ttr_window_ids if hasattr(self, 'input_service') else []
        window_available = index < len(wids)

        active = window_available and self.enabled_toons[index] and self.service_running

        # Resolve the slot's game and scope the keyset selector to it.
        if window_available:
            game_tag = GameRegistry.instance().get_game_for_window(str(wids[index]))
            if game_tag not in ("cc", "ttr"):
                game_tag = None
            if index < len(self.set_selectors):
                self.set_selectors[index].set_toon_game(game_tag)
        else:
            game_tag = None
            self.game_badges[index].hide()

        # Header session-status signal. The pinwheel card's own status dot is
        # owned by the layout (green when the toon is broadcasting, hidden
        # otherwise); this signal feeds the window-chrome session indicator.
        if active:
            state_str = "active"
        elif window_available and self.keep_alive_enabled[index]:
            state_str = "keep_alive"
        elif window_available:
            state_str = "disabled"
        else:
            state_str = "off"
        self.dot_state_changed.emit(index, state_str)

        # ── Per-control pinwheel styling. Each helper is the single
        # style-writer for its control; the active layout's whole-card dim
        # treatment desaturates them in place when the card is off/stopped. ──
        from utils.icon_factory import make_nav_power
        btn.setText("")
        btn.setEnabled(window_available and self.service_running)
        ink = QColor("#ffffff") if active else QColor(255, 255, 255, 209)
        btn.setIcon(make_nav_power(17, ink))
        btn.setStyleSheet(_pin_toggle_qss(c['accent_green'], active))

        self._apply_chat_btn_style(index, c)
        self._apply_keep_alive_btn_style(index, c)
        self._apply_click_sync_btn_style(index, c)
        selector.setEnabled(window_available and self.service_running)

        # Hand the whole-card render (chrome, portrait, dim, status dot) to the
        # active layout.
        self._set_card_brand_for_slot(
            index, game_tag,
            enabled=self.enabled_toons[index] and self.service_running,
        )

    def _apply_chat_btn_style(self, index, c):
        chat_btn = self.chat_buttons[index]
        wids = self.window_manager.ttr_window_ids if hasattr(self, 'input_service') else []
        window_available = index < len(wids)
        # Chat is only meaningful when the toon itself is broadcasting.
        usable = window_available and self.service_running and self.enabled_toons[index]
        chat_btn.setText("")
        chat_btn.setEnabled(usable)
        chat_btn.setIcon(make_chat_icon(17))
        chat_btn.setStyleSheet(
            _pin_toggle_qss(c['accent_blue_btn'], usable and self.chat_enabled[index])
        )

    @Slot(bool)
    def _on_chat_state_changed(self, active):
        """Called from InputService when global chat state changes."""
        self._chat_glow_active = active
        if not active:
            # Remove glow effects and restore proper visual state
            for i in range(4):
                if i < len(self.chat_buttons):
                    self.chat_buttons[i].setGraphicsEffect(None)
            for i in range(4):
                self.apply_visual_state(i)
        self._update_glow_timer()

    @Slot(str)
    def _on_input_log(self, msg):
        self.log(msg)

    def _on_uipi_blocked(self, details: dict) -> None:
        """Show the elevation modal (once per session unless dismissed) and, on
        the user's request, relaunch elevated. Triggered when background-toon
        input is provably being dropped by Windows UIPI."""
        from utils.settings_keys import UIPI_ELEVATION_PROMPT_DISMISSED
        sm = self.input_service.settings_manager
        if sm is not None and sm.get(UIPI_ELEVATION_PROMPT_DISMISSED, False):
            return
        from utils.widgets.uipi_elevation_dialog import UipiElevationDialog
        targets = details.get("targets") or [details]
        toons = [f"Toon {t.get('toon_index', -1) + 1}"
                 for t in targets if t.get("toon_index", -1) >= 0]
        dlg = UipiElevationDialog(affected_toons=toons, parent=self.window())
        self._uipi_dialog = dlg
        dlg.restart_as_admin.connect(self._do_elevated_restart)
        if sm is not None:
            dlg.dont_ask_again.connect(
                lambda: sm.set(UIPI_ELEVATION_PROMPT_DISMISSED, True))
        dlg.exec()

    def _do_elevated_restart(self) -> None:
        """Relaunch TTMT elevated. On UAC cancel (relaunch returns False) keep the
        app running and re-arm the prompt so the user can try again."""
        from utils import win32_elevation
        sm = self.input_service.settings_manager
        # Flush settings to disk before spawning the elevated child. SettingsManager
        # persists via save(); set() already saves synchronously, so this is belt
        # and suspenders against any buffered state.
        flush = getattr(sm, "save", None) if sm is not None else None
        ok = win32_elevation.relaunch_elevated(
            flush_settings=flush,
            on_success_shutdown=self._shutdown_for_relaunch,
        )
        if not ok:
            try:
                self.input_service.reset_uipi_latch()
            except Exception:
                pass

    def _shutdown_for_relaunch(self) -> None:
        try:
            self.input_service.shutdown()
            if self.click_sync_service is not None:
                self.click_sync_service.shutdown()
            if self._click_sync_backend is not None:
                self._click_sync_backend.disconnect()
        finally:
            from PySide6.QtWidgets import QApplication
            QApplication.quit()

    def _set_widget_opacity(self, w, opacity: float):
        """Apply a constant opacity to a widget via QGraphicsOpacityEffect.
        opacity >= 1.0 removes any existing effect so the widget paints
        at native opacity (and avoids the small repaint cost of a no-op
        effect). Under the offscreen Qt platform plugin (test suite) the
        effect crashes intermittently in PySide6 6.11, so we skip it
        there - matches the guard at _full_layout.py:825.

        Also skipped when the widget is hosted inside a
        QGraphicsProxyWidget (full mode's scale layer): the combination
        of QGraphicsOpacityEffect + QGraphicsProxyWidget breaks the
        button paint chain in PySide6 6.11 - widgets become entirely
        invisible. Any stale effect carried over from a prior compact
        populate is cleared so the widget paints at full opacity.

        Used for the "available but quiet" / "disabled but present"
        affordance on the per-toon control row (KA button in idle,
        Enable/Chat/Selector when disabled).
        """
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() == "offscreen":
            return

        # Walk up the parent chain looking for a widget that is the main
        # widget of a QGraphicsProxyWidget. If found, we're inside full
        # mode's scale layer - skip the effect path.
        walker = w
        while walker is not None:
            if walker.graphicsProxyWidget() is not None:
                if w.graphicsEffect() is not None:
                    w.setGraphicsEffect(None)
                return
            walker = walker.parentWidget()

        from PySide6.QtWidgets import QGraphicsOpacityEffect
        if opacity >= 1.0:
            if w.graphicsEffect() is not None:
                w.setGraphicsEffect(None)
            return
        effect = w.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(opacity)
        else:
            effect = QGraphicsOpacityEffect(w)
            effect.setOpacity(opacity)
            w.setGraphicsEffect(effect)

    def _apply_keep_alive_btn_style(self, index, c):
        ka_btn = self.keep_alive_buttons[index]
        bar = self.ka_progress_bars[index] if index < len(self.ka_progress_bars) else None
        wids = self.window_manager.ttr_window_ids if hasattr(self, 'input_service') else []
        window_available = index < len(wids)
        usable = window_available and self.service_running
        if bar:
            bar.set_bg_color("#0d0d0d")
        if not self._keep_alive_globally_enabled():
            ka_btn.setEnabled(False)
            ka_btn.setToolTip(
                "Keep-Alive is disabled. Enable it in Settings → Keep-Alive."
            )
            ka_btn.setIcon(make_lightning_icon(13, QColor(255, 255, 255, 90)))
            ka_btn.setStyleSheet(_pin_ka_off_qss())
            if bar:
                bar.set_fill_color(KA_ORANGE)
                bar.set_progress(0.0)
            return
        ka_btn.setEnabled(usable)
        ka_btn.setToolTip("Toggle keep-alive for this toon")
        if self.keep_alive_enabled[index] and usable:
            from utils.effects_flags import effects_disabled
            card_active = (
                window_available and self.enabled_toons[index] and self.service_running
            )
            settled = 0.0 if (card_active or effects_disabled()) else 1.0
            compact = getattr(self, "_compact", None)
            progress = compact.cell_dim_progress(index) if compact is not None else settled
            self._apply_keep_alive_dim_progress(index, progress)
        else:
            ka_btn.setIcon(make_lightning_icon(13, QColor(255, 255, 255, 128)))
            ka_btn.setStyleSheet(_pin_ka_off_qss())
            # Fill width is 0 when keep-alive is off.
            if bar:
                bar.set_fill_color(KA_ORANGE)
                bar.set_progress(0.0)

    def _apply_keep_alive_dim_progress(self, index, progress: float) -> None:
        """Re-render the keep-alive ON-state at dim `progress`. No-op when the
        button is in its neutral off-state (off-state carries no colour to fade)."""
        wids = self.window_manager.ttr_window_ids if hasattr(self, 'input_service') else []
        window_available = index < len(wids)
        usable = window_available and self.service_running
        if not (self._keep_alive_globally_enabled() and self.keep_alive_enabled[index] and usable):
            return
        ka_btn = self.keep_alive_buttons[index]
        bar = self.ka_progress_bars[index] if index < len(self.ka_progress_bars) else None
        is_rf = getattr(self, 'rapid_fire_enabled', [False]*4)[index]
        fill, border = _ka_fill_border(is_rf, progress)
        ink_a = round(255 + (170 - 255) * max(0.0, min(1.0, progress)))   # 255 -> 170
        ka_btn.setIcon(make_lightning_icon(13, QColor(255, 255, 255, ink_a)))
        ka_btn.setStyleSheet(_pin_ka_on_qss(fill, border))
        if bar:
            bar.set_fill_color(fill)

    # ── Glow animations ────────────────────────────────────────────────────

    def _tick_glow(self):
        self._glow_phase += 0.05

        delay = self._get_keep_alive_delay()
        elapsed = time.monotonic() - self._ka_cycle_start if self._ka_cycle_start else 0
        normal_progress = min(1.0, elapsed / delay) if delay > 0 else 0.0
        # Rapid-fire ring cycles once per second using modulo
        rf_progress = (elapsed % 1.0) if elapsed > 0 else 0.0

        # Only touch buttons whose state is actually being animated. Hitting
        # disabled ones every tick re-fires update()/paintEvent for no visual
        # change — which used to make ~80 redundant paint requests/sec while
        # the service was on and stutter window drags. Disabled buttons are
        # cleared once at toggle-off time and again when the timer stops.
        for i in range(4):
            if self.keep_alive_enabled[i]:
                is_rf = getattr(self, 'rapid_fire_enabled', [False] * 4)[i]
                self.keep_alive_buttons[i].set_progress(rf_progress if is_rf else normal_progress)

        # Chat button glow pulse when chat broadcast is active
        if self._chat_glow_active:
            pulse = (math.sin(self._glow_phase * 2.0) + 1.0) / 2.0  # 0..1
            blur = 8 + pulse * 14  # 8..22
            alpha = int(140 + pulse * 115)  # 140..255
            c = self._c()
            # Diagonal gradient: base #0077ff ↔ bright #0384fc
            # Shift the gradient stop position to animate the bright spot
            stop = 0.3 + pulse * 0.4  # bright spot travels 30%..70%
            wids = self.window_manager.ttr_window_ids
            for i in range(4):
                has_window = i < len(wids)
                if i < len(self.chat_buttons) and self.chat_enabled[i] and has_window:
                    btn = self.chat_buttons[i]
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background: qlineargradient(
                                x1:0, y1:0, x2:1, y2:1,
                                stop:0 #0077ff,
                                stop:{stop:.2f} #0384fc,
                                stop:1 #0077ff
                            );
                            color: white;
                            border: 1px solid {c['accent_blue_btn']};
                            border-radius: 9px;
                        }}
                    """)
                    glow = QGraphicsDropShadowEffect(btn)
                    glow.setOffset(0, 0)
                    glow.setBlurRadius(blur)
                    glow.setColor(QColor(0, 119, 255, alpha))
                    btn.setGraphicsEffect(glow)


    def _update_glow_timer(self):
        # service_running alone does NOT need the glow timer — it has no
        # animated visual tied to it. Including it here had the timer firing
        # 20 Hz the entire time the service was on, scheduling paintEvents on
        # all 4 keep-alive buttons even though nothing visual was changing.
        #
        # Visibility-gate too: these repaint timers only change pixels on the
        # visible Multitoon page. Off-page or minimized, stop them. The
        # keep-alive cycle anchor (_ka_cycle_start) is untouched, so rings/bars
        # resume on their true monotonic schedule (phase preserved).
        from tabs.multitoon._timer_gating import timers_should_run
        win = self.window()
        needs_glow, needs_bars = timers_should_run(
            is_current_page=self.isVisible(),       # False for a non-current stacked page
            window_visible=self.isVisible(),
            window_minimized=bool(win and win.isMinimized()),
            keep_alive_active=any(self.keep_alive_enabled),
            chat_glow_active=self._chat_glow_active,
            overlay_active=self._overlay_active,
        )

        if needs_glow and not self._glow_timer.isActive():
            self._glow_phase = 0.0
            self._glow_timer.start()
        elif not needs_glow and self._glow_timer.isActive():
            self._glow_timer.stop()
            for i in range(4):
                self.keep_alive_buttons[i].setGraphicsEffect(None)
                self.keep_alive_buttons[i].set_progress(0.0)

        if needs_bars and not self._bar_timer.isActive():
            self._bar_timer.start()
        elif not needs_bars and self._bar_timer.isActive():
            self._bar_timer.stop()
            for i in range(4):
                if i < len(self.ka_progress_bars):
                    self.ka_progress_bars[i].set_progress(0.0)

    def set_overlay_active(self, active: bool) -> None:
        """Called by the overlay controller on enter (True) / leave (False).

        Flips the overlay flag so the repaint timers stay alive while the main
        window is hidden (the cluster is visible in its own surfaces), and on
        enter reconciles the borrowed keep-alive bars' paint state (clears any
        stale graphics effect + restores visibility per the master setting) so
        the bar paints in the overlay. Phase is preserved by the untouched
        monotonic _ka_cycle_start anchor, so the bar resumes mid-cycle on either
        side of the switch.
        """
        self._overlay_active = bool(active)
        if active:
            # Make sure the bars carry no leftover opacity effect from a fade
            # animation and are visible per the master flag, so they paint in the
            # borrowed/proxied overlay card.
            self._reconcile_keep_alive_visibility_instant()
            self._trace_ka_overlay("enter")
        self._update_glow_timer()

    def _trace_ka_overlay(self, tag: str) -> None:
        """Diagnostic (no-op unless TTMT_KA_TRACE is set): log each keep-alive
        bar's live paint state when the overlay goes active, so the borrowed-bar
        visibility cause can be confirmed without self-injecting into the app."""
        import os
        if not os.environ.get("TTMT_KA_TRACE"):
            return
        from PySide6.QtCore import QPoint
        active = self._bar_timer.isActive() if hasattr(self, "_bar_timer") else None
        print(f"[KA_TRACE:{tag}] overlay_active={self._overlay_active} "
              f"bar_timer_active={active} master={self._keep_alive_globally_enabled()} "
              f"ka_enabled={list(self.keep_alive_enabled)}")
        for i, bar in enumerate(self.ka_progress_bars):
            try:
                top = bar.mapTo(bar.window(), QPoint(0, 0))
                print(f"  bar[{i}] hidden={bar.isHidden()} visible={bar.isVisible()} "
                      f"size={bar.size().width()}x{bar.size().height()} "
                      f"effect={bar.graphicsEffect()} parent={type(bar.parent()).__name__} "
                      f"topInWindow=({top.x()},{top.y()}) progress={getattr(bar, '_progress', None)}")
            except Exception as e:
                print(f"  bar[{i}] trace error: {e}")

    def _tick_progress_bars(self):
        delay = self._get_keep_alive_delay()
        elapsed = time.monotonic() - self._ka_cycle_start if self._ka_cycle_start else 0
        normal_progress = min(1.0, elapsed / delay) if delay > 0 else 0.0
        rf_progress = (elapsed % 1.0) if elapsed > 0 else 0.0

        for i in range(4):
            if i < len(self.ka_progress_bars):
                bar = self.ka_progress_bars[i]
                if self.keep_alive_enabled[i]:
                    is_rf = getattr(self, 'rapid_fire_enabled', [False] * 4)[i]
                    bar.set_progress(rf_progress if is_rf else normal_progress)
                else:
                    bar.set_progress(0.0)

    # ── Service button style ───────────────────────────────────────────────

    def update_service_button_style(self):
        """Compatibility wrapper. update_status_label is the source of
        truth for the bar; this delegates so existing callers keep
        working."""
        if self.service_running:
            self.toggle_service_button.setText(f"{S(chr(9632), chr(9632))} Stop Service")
            self.toggle_service_button.setToolTip("Stop the multitoon input service")
        else:
            self.toggle_service_button.setText(f"{S(chr(9654), chr(9654))} Start Service")
            self.toggle_service_button.setToolTip("Start the multitoon input service")
        self.update_status_label()

    def apply_all_visual_states(self):
        for i in range(4):
            self.apply_visual_state(i)

    # ── Status label + segment bar ─────────────────────────────────────────

    def update_status_label(self):
        """Source of truth for the ServiceStatusBar - drives bar state
        (broadcasting / idle / stopped), the status text, and the per-slot
        dot states (active / found / off) in one pass."""
        # Per-slot dot states (legacy behaviour kept verbatim).
        wids = self.window_manager.ttr_window_ids if hasattr(self, 'input_service') else []
        segments = []
        for i in range(4):
            window_available = i < len(wids)
            if window_available and self.enabled_toons[i] and self.service_running:
                segments.append(2)   # active
            elif window_available:
                segments.append(1)   # found
            else:
                segments.append(0)   # off
        self.status_bar.set_dot_states(segments)

        # Bar state + text. Same 3-state machine the Direction D mockup
        # documents: Stopped (user pressed stop), Broadcasting (service
        # on AND at least one toon enabled), Idle (service on, no toons
        # enabled).
        if not self.service_running:
            self.status_bar.set_state("stopped")
            self.status_bar.set_status_text(
                "Stopped · click play to resume broadcasting"
            )
            return

        enabled_count = sum(1 for v in self.enabled_toons if v)
        if enabled_count == 0:
            self.status_bar.set_state("idle")
            self.status_bar.set_status_text(
                "Idle · enable a toon below to start broadcasting"
            )
        else:
            self.status_bar.set_state("broadcasting")
            self.status_bar.set_status_text(
                f"Broadcasting · {enabled_count} of 4 toons"
            )

    # ── Name fetching ──────────────────────────────────────────────────────

    def schedule_toon_data_fetch(self, delay_ms: int = 1200):
        if not self.window_manager.ttr_window_ids:
            return
        self._toon_fetch_timer.start(max(0, delay_ms))

    def _run_scheduled_toon_fetch(self):
        self._fetch_names_if_enabled(len(self.window_manager.ttr_window_ids))

    def _fetch_names_if_enabled(self, num_slots: int):
        wids = list(self.window_manager.ttr_window_ids) if hasattr(self, 'window_manager') and self.window_manager else []
        ttr_enabled = bool(self.settings_manager and self.settings_manager.get("enable_companion_app", True))
        cc_enabled = bool(self.settings_manager and self.settings_manager.get("enable_cc_companion_app", True))
        if not wids or not (ttr_enabled or cc_enabled):
            return

        request_key = (tuple(wids), ttr_enabled, cc_enabled)
        if request_key in self._toon_fetch_inflight_keys:
            return

        self._toon_fetch_inflight_keys.add(request_key)
        self._refresh_gen += 1
        gen = self._refresh_gen

        def _run_fetch():
            try:
                registry = GameRegistry.instance()
                ttr_wids = [wid for wid in wids if registry.get_game_for_window(wid) == "ttr"]
                cc_wids = [wid for wid in wids if registry.get_game_for_window(wid) == "cc"]

                if ttr_wids and ttr_enabled:
                    names, styles, colors, laffs, max_laffs, beans = get_toon_names_by_slot(len(ttr_wids), ttr_wids)
                    if gen == self._refresh_gen:
                        self._toon_data_merge_ready.emit(list(ttr_wids), list(names), list(styles), list(colors), list(laffs), list(max_laffs), list(beans))

                if cc_wids and cc_enabled:
                    def _cc_data_callback(infos):
                        if gen == self._refresh_gen:
                            self._cc_toon_info_ready.emit(list(cc_wids), list(infos))
                    cc_api.get_toon_data_threaded(len(cc_wids), cc_wids, _cc_data_callback)
            finally:
                self._toon_fetch_inflight_keys.discard(request_key)

        threading.Thread(target=_run_fetch, daemon=True).start()

    def _set_card_brand_for_slot(
        self, index: int, game: str | None, enabled: bool = False
    ) -> None:
        """Render slot `index` via the active pinwheel layout's set_card_brand
        (card chrome, controls, portrait, dim/glow). Also teaches the badge
        what game it represents so it can look up its customization entry on
        next paint.

        Only the pinwheel layout (`_compact`) is driven: it is the single
        Multitoon layout now, and it shares the per-slot widgets, so updating
        the retired `_full` layout would restyle those shared widgets with the
        old look right after the pinwheel set them.
        """
        if index < len(self.slot_badges):
            self.slot_badges[index].set_game(game)
        layout = getattr(self, "_compact", None)
        set_brand = getattr(layout, "set_card_brand", None) if layout else None
        if callable(set_brand):
            set_brand(index, game, enabled=enabled)

    def _open_customization_dialog(self, slot: int) -> None:
        """Open the customization overlay for the given slot.

        The overlay lives on the main window; we delegate here so
        the tab itself doesn't need to know about overlay
        construction or lifecycle."""
        if slot < 0 or slot >= len(self.slot_badges):
            return
        badge = self.slot_badges[slot]
        if not badge.toon_name or badge.game not in ("cc", "ttr"):
            return
        win = self.window()
        if win is None or not hasattr(win, "open_customization"):
            return
        win.open_customization(slot)

    def _on_customization_saved(self, slot: int, game: str) -> None:
        """Re-apply chrome and repaint after a successful Save."""
        self._apply_chip_for_slot(slot, game)
        self._set_card_brand_for_slot(
            slot, game,
            enabled=bool(self.enabled_toons[slot]),
        )
        # Propagate pose change to the badge so it refetches if needed.
        if game == "ttr" and slot < len(self.slot_badges):
            from utils.toon_customization_resolve import resolve_pose
            toon_name = self.toon_names[slot] if slot < len(self.toon_names) else None
            entry = (
                self.customizations.get(game, toon_name) if toon_name else {}
            )
            new_pose = resolve_pose(entry, "portrait")
            self.slot_badges[slot].set_pose(new_pose)
        if slot < len(self.slot_badges):
            self.slot_badges[slot].update()
        self.apply_visual_state(slot)

    def _apply_chip_for_slot(self, index: int, game_tag: str | None) -> None:
        """Apply the CC/TTR chip stylesheet, consulting accent override.

        The pinwheel layout does not surface a per-card game chip, so the
        chip stays hidden; the game identity drives the card's accent instead.
        """
        if index >= len(self.game_badges):
            return
        self.game_badges[index].hide()

    def _refresh_is_coalesced(self, now: float) -> bool:
        """True if a refresh requested at monotonic time `now` falls within the
        cooldown of the last accepted refresh (caller should skip it). On a miss,
        records `now` as the new cooldown origin and returns False (accept)."""
        if now - self._last_refresh_monotonic < self._REFRESH_COOLDOWN_S:
            return True
        self._last_refresh_monotonic = now
        return False

    def manual_refresh(self):
        if self._refresh_is_coalesced(time.monotonic()):
            self.log("[Service] Refresh coalesced (within cooldown).")
            return
        self.log("[Service] Manual refresh triggered.")
        invalidate_port_to_wid_cache()
        clear_stale_names([])
        self.toon_names = [None] * 4
        self.toon_styles = [None] * 4
        self.toon_colors = [None] * 4
        self.toon_laffs = [None] * 4
        self.toon_max_laffs = [None] * 4
        self.toon_beans = [None] * 4
        for i in range(4):
            if i < len(self.slot_badges):
                self.slot_badges[i].set_dna(None)
                self.slot_badges[i].set_toon_name(None)
                self.slot_badges[i].set_cc_auto_species(None)
                self.slot_badges[i].set_cc_mode(None, None, None, None)
        self._last_window_ids = []
        self._refresh_toon_name_labels()
        self._refresh_toon_stats_labels()
        
        while not self.key_event_queue.empty():
            try:
                self.key_event_queue.get_nowait()
            except Exception:
                pass
                
        if self.service_running:
            self.input_service.stop()
            self.window_manager.clear_window_ids()
            # No main-thread assign_windows(); poll loop reassigns within ~2s.
            self.input_service.start()
            self.schedule_toon_data_fetch(1200)
        else:
            self.window_manager.disable_detection()
            self.update_toon_controls([])

    def _auto_refresh(self):
        # Don't call assign_windows() here — it runs xdotool subprocesses
        # synchronously on the main thread, which blocks the UI for up to a
        # few seconds on Wayland under load. The window_manager's poll thread
        # already runs assign_windows() every 2s in its own thread, so the
        # window list stays fresh without blocking compact↔full swaps.
        self._fetch_names_if_enabled(len(self.window_manager.ttr_window_ids))

    # ── Service lifecycle ──────────────────────────────────────────────────

    def _on_service_stop_requested(self) -> None:
        """Wired to ServiceStatusBar.stop_requested. Idempotent stop."""
        if self.service_running:
            self.toggle_service()

    def _on_service_play_requested(self) -> None:
        """Wired to ServiceStatusBar.play_requested. Idempotent start."""
        if not self.service_running:
            self.toggle_service()

    def _on_refresh_requested(self) -> None:
        """Wired to ServiceStatusBar.refresh_requested. Same as the old
        refresh_button click handler."""
        self.manual_refresh()

    def toggle_service(self):
        self.service_running = not self.service_running
        if self.service_running:
            # No assign_windows() here — it's a no-op (detection_enabled is
            # still False), and even when it isn't, the call must not run on
            # the main thread. Poll loop handles assignment within ~2s.
            self.input_service.window_manager.enable_detection()
            self._start_service_internal()
        else:
            self.input_service.stop()
            self.refresh_timer.stop()
            self._toon_fetch_timer.stop()
            self._refresh_gen += 1
            self.input_service.window_manager.disable_detection()
            self.disable_all_toon_controls()
            self.log("[Service] Multitoon service stopped.")
        self.update_service_button_style()
        self._update_glow_timer()

    def _start_service_internal(self):
        self.input_service.start()
        self.log("[Service] Multitoon service started.")
        wids = self.window_manager.ttr_window_ids
        for i in range(4):
            if i < len(wids):
                self.enabled_toons[i] = True
                self.chat_enabled[i]  = True
                self.toon_buttons[i].setChecked(True)
                self.chat_buttons[i].setChecked(True)
                self.apply_visual_state(i)
        count = len(wids)
        if count:
            self.log(f"[Input] {count} toon window{'s' if count != 1 else ''} detected — input + chat enabled")
        self.update_status_label()
        self.refresh_timer.start()
        self.schedule_toon_data_fetch(1200)

    def start_service(self):
        if not self.service_running:
            self.toggle_service()

    def stop_service(self):
        if self.service_running:
            self.toggle_service()

    def set_service_active(self, active: bool):
        if self.service_running != active:
            self.toggle_service()

    def disable_all_toon_controls(self):
        """Service stopped: dim every card in place but KEEP each toon's
        identity (name, portrait, stats) so the cards stay mounted exactly
        where they are. Cards only empty out when the game window actually
        closes (handled in update_toon_controls). This differs from the
        legacy stack, which blanked every card on stop.
        """
        self._stop_keep_alive()
        for i in range(4):
            self.toon_buttons[i].setChecked(False)
            self.chat_buttons[i].setChecked(True)
            self.keep_alive_buttons[i].setChecked(False)
            self.keep_alive_buttons[i].is_rapid_fire = False
            self.enabled_toons[i] = False
            self.chat_enabled[i]  = True
            self.keep_alive_enabled[i] = False
            self.rapid_fire_enabled[i] = False
            # Identity (toon_names / styles / colors and the badge's DNA / CC
            # paint) is intentionally preserved so the dimmed card keeps its
            # portrait, name and stats.
            self.apply_visual_state(i)
        self._update_glow_timer()
        self._refresh_toon_name_labels()
        self.update_status_label()

    def _on_portrait_clicked(self, index: int):
        if index < len(self.window_manager.ttr_window_ids):
            wid = self.window_manager.ttr_window_ids[index]
            if wid:
                self.input_service.send_keep_alive_to_window(wid, "f1", modifiers=["shift"])
                self.log(f"[EasterEgg] Sent shift+f1 to Toon {index + 1} (WID {wid})")

    # ── Toon toggles ───────────────────────────────────────────────────────

    def toggle_toon(self, index):
        self.enabled_toons[index] = not self.enabled_toons[index]
        self.toon_buttons[index].setChecked(self.enabled_toons[index])
        if self.enabled_toons[index]:
            self.chat_enabled[index] = True
            self.chat_buttons[index].setChecked(True)
        else:
            self.chat_enabled[index] = False
            self.chat_buttons[index].setChecked(False)
        state = "enabled" if self.enabled_toons[index] else "disabled"
        name = self.toon_names[index] or f"Toon {index + 1}"
        self.log(f"[Input] {name} (slot {index + 1}): input {state}")
        self.apply_visual_state(index)
        self.update_status_label()
        self._autosave_active_profile()

    def toggle_chat(self, index):
        self.chat_enabled[index] = not self.chat_enabled[index]
        self.chat_buttons[index].setChecked(self.chat_enabled[index])
        state = "enabled" if self.chat_enabled[index] else "disabled"
        name = self.toon_names[index] or f"Toon {index + 1}"
        self.log(f"[Input] {name} (slot {index + 1}): chat {state}")
        self.apply_visual_state(index)

    def _build_click_sync(self) -> None:
        # Set before the resolver closures below are built: they read this
        # attribute at call time, and capture can start before the
        # controller is constructed at the end of this method.
        self.ghost_cursor_controller = None

        # Click sync (mouse mirroring) runs on Linux/X11, Windows, and macOS. On any
        # OTHER platform leave click_sync_service / _click_sync_backend as None (set in
        # __init__) so the feature is simply absent, and -- critically -- never import a
        # platform backend here (e.g. utils.xlib_backend imports python-xlib, absent on
        # macOS) which would crash the app at startup. Downstream (shutdown, the per-toon
        # toggle, state styling) already guards on None. Each platform's backend is
        # imported lazily inside its own branch below.
        import sys
        if sys.platform not in ("win32", "linux", "darwin"):
            return

        from services.click_sync_service import ClickSyncService

        def _cs_slot_wid(slot, _wm=self.window_manager):
            ids = _wm.get_window_ids()
            if slot < len(ids) and _wm.window_games.get(ids[slot]) == "ttr":
                return ids[slot]
            return None

        _cs_delivery_ready = None   # darwin sets this to backend.mouse_delivery_ready

        if sys.platform == "win32":
            from utils import win32_discovery as _disc
            from utils.win32_backend import Win32Backend
            from utils.win32_mouse_capture import Win32MouseCapture

            # Threading note (Windows): capture events arrive INSIDE the
            # WH_MOUSE_LL hook callback, so time spent handling them —
            # including waiting on the service lock — delays ALL system
            # mouse input, and a callback exceeding the OS hook timeout
            # (~300ms) gets the hook silently removed. Work under the
            # service lock must stay trivially fast.

            def _cs_source_resolver(root_x, root_y, member_wids):
                # Tri-state hit test (wid | "" | None). Member wids ARE
                # toplevel hwnds, so a direct comparison replaces the X11
                # ancestor walk. Clean misses and foreign toplevels are
                # ignored; rect-containment ONLY on lookup failure (same
                # policy as the X11 resolver below).
                frame = _disc.toplevel_at_point(root_x, root_y)
                # Ghost overlays need no guard here: WindowFromPoint skips
                # WS_EX_TRANSPARENT layered windows (what Qt's
                # WindowTransparentForInput sets).
                if frame:
                    return frame if frame in member_wids else None
                if frame == "":
                    # Clean miss. Near-unreachable on Windows: over a bare
                    # desktop WindowFromPoint returns the Progman/WorkerW
                    # window (a foreign toplevel hit above), not NULL —
                    # kept for tri-state contract parity with X11.
                    return None
                for wid in member_wids:
                    g = self.window_manager.get_window_geometry(wid)
                    if (g and g[0] <= root_x < g[0] + g[2]
                            and g[1] <= root_y < g[1] + g[3]):
                        return wid
                return None

            def _cs_capture_factory(on_event):
                # on_died closes over its own instance so the service can
                # identity-check stale generations.
                holder = []
                cap = Win32MouseCapture(
                    on_event,
                    on_died=lambda: self.click_sync_service.notify_capture_died(
                        holder[0]))
                holder.append(cap)
                return cap

            # PostMessage is connection-less: a dedicated instance is free,
            # and symmetric with the Linux dedicated-Display rule below.
            self._click_sync_backend = Win32Backend()
            _fresh_geom = _disc.get_window_geometry
        elif sys.platform == "linux":
            from utils import x11_discovery as _x11d

            def _cs_source_resolver(root_x, root_y, member_wids):
                # Stacking-aware: the frame under the point must be a member's
                # toplevel ancestor.
                # Tri-state hit-test: wid string = a toplevel contains the
                # point; "" = clean miss (bare root/desktop); None = lookup
                # FAILURE (no display / X error).
                frame = _x11d.toplevel_at_point(root_x, root_y)
                gc = self.ghost_cursor_controller
                if frame and gc is not None and frame in gc.overlay_wids():
                    # One of our own ghost overlays under the point (edge
                    # spill / stacked member windows). It only ever sits on
                    # top of a member window, so resolve via the rect-
                    # containment fallback below, never classify it as a
                    # foreign toplevel. (Belt-and-suspenders: the overlay's
                    # empty input shape already hides it from
                    # translate_coords on Xorg/XWayland.)
                    frame = None
                lookup_failed = frame is None
                if frame:
                    for wid in member_wids:
                        anc = _x11d.toplevel_ancestor(wid)
                        if anc is None:
                            # Transient X error on this member's ancestor walk;
                            # remember so the fallback below can cover for it.
                            lookup_failed = True
                        elif anc == frame:
                            return wid
                    if not lookup_failed:
                        # The point cleanly resolved to a non-member toplevel
                        # (e.g. a foreign window overlapping a TTR window). Per
                        # spec, that gesture must be ignored, never rect-matched
                        # to the member window underneath.
                        return None
                elif frame == "":
                    # Clean miss: the point is over the bare root, no toplevel
                    # there at all. Ignore the gesture; never rect-match.
                    return None
                # Rect-containment fallback: only for stacking-resolution
                # FAILURES (toplevel_at_point or an ancestor lookup hit a
                # transient X error), never for a clean miss or a clean
                # foreign-window hit.
                for wid in member_wids:
                    g = self.window_manager.get_window_geometry(wid)
                    if g and g[0] <= root_x < g[0] + g[2] and g[1] <= root_y < g[1] + g[3]:
                        return wid
                return None

            def _cs_capture_factory(on_event):
                from utils.xrecord_capture import XRecordCapture
                # on_died closes over its own instance so the service can
                # identity-check stale generations.
                holder = []
                cap = XRecordCapture(
                    on_event,
                    on_died=lambda: self.click_sync_service.notify_capture_died(
                        holder[0]))
                holder.append(cap)
                return cap

            # Dedicated injection connection. Do NOT share input_service._xlib:
            # that Display belongs to the InputService worker thread, and click
            # sync injects from the XRecord capture thread and the hover-flush
            # timer threads (Xlib Displays must not be used CONCURRENTLY across
            # threads; click sync's own calls are serialized under the service
            # lock, so its one dedicated Display is safe).
            from utils.xlib_backend import XlibBackend
            self._click_sync_backend = XlibBackend()
            _fresh_geom = _x11d.get_window_geometry
        elif sys.platform == "darwin":
            from utils import macos_discovery as _macd
            from utils.macos_backend import MacOSBackend
            from utils.macos_mouse_capture import MacOSMouseCapture
            from utils.macos_mouse_delivery import EchoLedger

            # ONE shared EchoLedger: the delivery engine records every posted event into
            # it; the capture's EchoGuard matches against it (marker-stripped echo defense).
            _cs_echo_ledger = EchoLedger()

            def _cs_source_resolver(root_x, root_y, member_wids):
                # Safe active-window resolver (spec §3.4): the frontmost game window
                # must be a member AND contain the point. The key-flip never changes
                # system-front, so the active window is a reliable source.
                return _macd.active_source_window(root_x, root_y, member_wids)

            def _cs_capture_factory(on_event):
                holder = []
                cap = MacOSMouseCapture(
                    on_event, ledger=_cs_echo_ledger,
                    on_died=lambda: self.click_sync_service.notify_capture_died(
                        holder[0]))
                holder.append(cap)
                return cap

            self._click_sync_backend = MacOSBackend()
            self._click_sync_backend.set_echo_ledger(_cs_echo_ledger)   # same instance into both
            _fresh_geom = _macd.get_window_geometry_fresh
            _cs_delivery_ready = self._click_sync_backend.mouse_delivery_ready

        try:
            self._click_sync_backend.connect()   # no-op on Win32Backend
        except Exception as e:
            print(f"[MultitoonTab] click sync backend connect failed: {e}")

        # The real WindowManager (services/window_manager.py) provides
        # get_window_geometry + window_geometry_updated; offscreen tab tests
        # pass duck-typed fakes that may omit them, so degrade gracefully
        # (no geometry -> slots resolve unusable, capture never starts).
        _geom = getattr(self.window_manager, "get_window_geometry", None)
        if _geom is None:
            print("[MultitoonTab] click sync: window manager lacks "
                  "get_window_geometry; geometry lookups disabled")
        # parent=self: the service's resolver closures capture the tab, so
        # tab <-> service form a reference cycle between two QObjects. Qt
        # parenting destroys the service's C++ object with the widget tree
        # instead of leaving it to Python's GC, whose arbitrary destruction
        # order segfaults Shiboken at interpreter teardown (Python 3.14 +
        # PySide6 GC race).
        self.click_sync_service = ClickSyncService(
            slot_window_resolver=_cs_slot_wid,
            geometry_provider=_geom if _geom is not None else (lambda _wid: None),
            source_resolver=_cs_source_resolver,
            backend=self._click_sync_backend,
            capture_factory=_cs_capture_factory,
            parent=self,
            # Gesture snapshots need LIVE geometry: the WM cache can be ~2s
            # stale after a window move, which would mismap the injection.
            # The capture thread gets its own per-thread Display.
            fresh_geometry_provider=_fresh_geom,
            delivery_ready=_cs_delivery_ready,
        )
        self.click_sync_service.slot_states_changed.connect(
            self._on_click_sync_states)
        self.click_sync_service.service_error.connect(
            self._on_click_sync_service_error)
        self.window_manager.window_ids_updated.connect(
            lambda _ids: self.click_sync_service.recompute())
        # Resizes don't change the window list; the geometry signal drives
        # the live aspect re-check (mismatch pause + auto-recovery).
        if hasattr(self.window_manager, "window_geometry_updated"):
            self.window_manager.window_geometry_updated.connect(
                self.click_sync_service.recompute)
        else:
            print("[MultitoonTab] click sync: window manager lacks "
                  "window_geometry_updated; live geometry re-check disabled")
        if self.settings_manager is not None:
            self.click_sync_service.set_enabled(
                bool(self.settings_manager.get(CLICK_SYNC_ENABLED, False)))
            self.settings_manager.on_change(self._on_click_sync_setting_changed)
        # Ghost cursors: per-toon glove overlays on synced windows (spec
        # 2026-06-11-click-sync-ghost-cursors-design.md). parent=self for the
        # same Qt-parenting teardown reason as the service above. On darwin the
        # overlays float via a native NSWindow recipe (utils.macos_overlay,
        # spike-proven 2026-06-15); the resolver-safety overlay_wids() guard is
        # unused on darwin (the active-window source resolver never hit-tests
        # toplevels), so no extra wiring is needed there.
        from tabs.multitoon._ghost_cursors import GhostCursorController

        def _cs_slot_rect(slot, _wid=_cs_slot_wid,
                          _g=_geom if _geom is not None else (lambda _w: None)):
            # NATIVE game-window rect for the slot; the confined ghost
            # renderer clips the glove to it (cache-backed, GUI-thread safe).
            wid = _wid(slot)
            return _g(wid) if wid else None

        self.ghost_cursor_controller = GhostCursorController(
            self.click_sync_service, self.settings_manager, parent=self,
            slot_window_resolver=_cs_slot_wid,
            slot_rect_resolver=_cs_slot_rect)
        # The focused window never shows a ghost (spec
        # 2026-06-12-ghost-cursor-focus-suppress-design.md). Same duck-typed
        # guard as window_geometry_updated above: offscreen fakes without the
        # signal degrade to no focus suppression.
        if hasattr(self.window_manager, "active_window_changed"):
            self.window_manager.active_window_changed.connect(
                self.ghost_cursor_controller.set_focused_window)
        else:
            print("[MultitoonTab] ghost cursors: window manager lacks "
                  "active_window_changed; focus suppression disabled")
        if hasattr(self.window_manager, "get_active_window"):
            self.ghost_cursor_controller.set_focused_window(
                self.window_manager.get_active_window() or "")
        self._apply_click_sync_visibility()

    def toggle_click_sync(self, index: int) -> None:
        if self.click_sync_service is None:
            return
        member = self.click_sync_service.toggle_slot(index)
        self.click_sync_buttons[index].setChecked(member)

    def _click_sync_visual_state(self, index: int) -> str:
        state = self._click_sync_states.get(index, "off")
        return state if state in ("off", "armed", "active", "error") else "off"

    def _rebuild_click_sync_icons(self, c) -> None:
        """Per-palette icon cache. Rebuilt on theme refresh so icons tinted
        with the previous palette never survive a theme switch."""
        self._click_sync_icons = {
            "off": make_click_sync_icon(14, c["text_muted"]),
            "armed": make_click_sync_icon(14, c["accent_pink_border"]),
            "active": make_click_sync_icon(14, c["text_on_accent"]),
            "error": make_click_sync_warning_icon(14, c["text_on_accent"]),
            "disabled": make_click_sync_icon(14, c["text_disabled"]),
        }

    def _apply_click_sync_btn_style(self, index: int, c) -> None:
        """SINGLE style writer for the click sync button (spec:
        2026-06-10-click-sync-button-styling-design.md): stylesheet, icon,
        checked flag, and tooltip all come from here."""
        if index >= len(self.click_sync_buttons):
            return
        btn = self.click_sync_buttons[index]
        state = self._click_sync_visual_state(index)
        if not self._click_sync_icons:
            self._rebuild_click_sync_icons(c)
        # A slot with no TTR window renders disabled (chat-button disabled
        # look) UNLESS it is still a member. Windowless members are evicted
        # service-side (spec 2026-06-12-click-sync-evict-windowless), so
        # this guard only covers the instant between the window vanishing
        # and the eviction snapshot landing; the checked flag below tracks
        # the snapshot, so service-side eviction unchecks the button here.
        ids = self.window_manager.get_window_ids()
        has_ttr = (index < len(ids)
                   and self.window_manager.window_games.get(ids[index]) == "ttr")
        member = state != "off"
        if not has_ttr and not member:
            btn.setEnabled(False)
            btn.setChecked(False)
            btn.setIcon(self._click_sync_icons["disabled"])
            btn.setStyleSheet(_pin_toggle_qss(c['accent_pink'], False))
            btn.setToolTip("Click sync: no toon detected in this slot")
            return
        btn.setEnabled(True)
        btn.setIcon(self._click_sync_icons[state])
        btn.setChecked(state != "off")
        if state == "active":
            btn.setStyleSheet(_pin_toggle_qss(c['accent_pink'], True))
        elif state == "armed":
            # Dark chip with a pink ring: armed but not yet mirroring.
            btn.setStyleSheet(_pin_cs_chip_qss(c['accent_pink_border']))
        elif state == "error":
            btn.setStyleSheet(_pin_cs_chip_qss(c['accent_red_border']))
        else:  # off (also the unknown-state fallback)
            btn.setStyleSheet(_pin_toggle_qss(c['accent_pink'], False))
        tips = {
            "off": "Click sync: mirror clicks to this toon",
            "armed": "Click sync: waiting for a second toon",
            "active": "Click sync: active",
            "error": "Click sync: paused (window missing or proportions differ)",
        }
        if state == "error" and self._click_sync_error_tip:
            btn.setToolTip(self._click_sync_error_tip)
        else:
            btn.setToolTip(tips[state])

    def _on_click_sync_states(self, states: dict) -> None:
        # Complete four-slot snapshot from the service: REPLACE the cache,
        # never merge. A fresh snapshot supersedes any service-error
        # tooltip override.
        self._click_sync_states = dict(states)
        self._click_sync_error_tip = None
        c = self._c()
        for i in range(len(self.click_sync_buttons)):
            self._apply_click_sync_btn_style(i, c)

    def _on_click_sync_service_error(self, message: str) -> None:
        """A capture failure needs different user action than a window
        mismatch. The service emits error STATES first, then this signal;
        the override re-styles slots whose cached state is error and stays
        until the next state snapshot clears it."""
        self._click_sync_error_tip = (
            f"Click sync: stopped ({message}). Toggle a toon button to retry."
        )
        c = self._c()
        for i in range(len(self.click_sync_buttons)):
            if self._click_sync_visual_state(i) == "error":
                self._apply_click_sync_btn_style(i, c)
        print(f"[MultitoonTab] click sync error: {message}")

    def _apply_click_sync_visibility(self) -> None:
        """Master switch ON: the button is ALWAYS present in the row, like
        the keep-alive button; slots without a TTR window render disabled
        via the style resolver instead of disappearing. Called on setting
        change and from update_toon_controls (so per-slot enabledness
        tracks windows coming and going)."""
        master = (
            self.settings_manager is not None
            and bool(self.settings_manager.get(CLICK_SYNC_ENABLED, False))
        )
        for btn in self.click_sync_buttons:
            btn.setVisible(master)
        c = self._c()
        for i in range(len(self.click_sync_buttons)):
            self._apply_click_sync_btn_style(i, c)
        self._repin_collapsed_ka_widths()

    def _repin_collapsed_ka_widths(self) -> None:
        """Re-pin each ka_group's collapsed fixed width after a click-sync
        visibility flip.

        When keep-alive is master-collapsed, the layouts' collapse animation
        pins ka_group via setFixedWidth(_collapsed_ka_group_width(i)). A
        click-sync visibility change alters that target width, so a stale
        pin clips the row (button just shown) or leaves a gap (just hidden)
        until the next KA animation. Only width-pinned groups are touched:
        before any collapse animation has run ka_group carries no fixed
        width and the stretch-0 layout reflows on its own."""
        if self._keep_alive_globally_enabled():
            return
        QWIDGETSIZE_MAX_VAL = 16777215
        for layout in (getattr(self, "_compact", None), getattr(self, "_full", None)):
            if layout is None:
                continue
            # _FullLayout wraps the slot-owning content widget; _CompactLayout
            # owns its slots (and _collapsed_ka_group_width) directly.
            content = getattr(layout, "_content", layout)
            for i, slot in enumerate(content._card_slots):
                ka_group = slot["ka_group"]
                if ka_group.maximumWidth() == QWIDGETSIZE_MAX_VAL:
                    continue  # never pinned; follows the layout naturally
                ka_group.setFixedWidth(content._collapsed_ka_group_width(i))

    def _on_click_sync_setting_changed(self, key, value) -> None:
        if key != CLICK_SYNC_ENABLED or self.click_sync_service is None:
            return
        self.click_sync_service.set_enabled(bool(value))
        self._apply_click_sync_visibility()

    def toggle_rapid_fire(self, index, state):
        if not self._keep_alive_globally_enabled():
            # Symmetric to toggle_keep_alive's gate — guards against
            # programmatic callers from leaving rapid_fire_enabled[i] in a
            # state inconsistent with keep_alive_enabled[i] when the master
            # flag is off.
            return
        self.rapid_fire_enabled[index] = state
        self._apply_keep_alive_btn_style(index, self._c())
        if state and not self.keep_alive_enabled[index]:
            self.toggle_keep_alive(index)
        if self._keep_alive_running:
            self._ka_cycle_event.set()

    def toggle_keep_alive(self, index):
        if not self._keep_alive_globally_enabled():
            # Master flag is off — suppress toggle. The button should already
            # be visually disabled; this guards against programmatic callers
            # like load_profile or hotkey-driven paths.
            return
        self.keep_alive_enabled[index] = not self.keep_alive_enabled[index]
        self.keep_alive_buttons[index].setChecked(self.keep_alive_enabled[index])

        # Turning off: always clear rapid fire so the next click-on starts fresh
        if not self.keep_alive_enabled[index]:
            self.rapid_fire_enabled[index] = False
            self.keep_alive_buttons[index].is_rapid_fire = False
            # _tick_glow no longer touches disabled buttons each frame; clear
            # the just-disabled button's progress ring + glow effect here so
            # it doesn't stay frozen at the last value.
            self.keep_alive_buttons[index].setGraphicsEffect(None)
            self.keep_alive_buttons[index].set_progress(0.0)
        else:
            self._reset_ka_cycle()

        self._apply_keep_alive_btn_style(index, self._c())
        self.update_service_button_style()

        if any(self.keep_alive_enabled):
            # Ensure the keep-alive loop is running
            self._start_keep_alive()
        else:
            self._stop_keep_alive()
        self._update_glow_timer()
        self.apply_visual_state(index)

    def toggle_keep_alive_all(self):
        """Hotkey action: if ANY slot's keep-alive is on, turn those off;
        otherwise turn all four on. Delegates per-slot to toggle_keep_alive
        (master-flag guard, rapid-fire reset, loop start/stop, styling all
        live there). Enabling an empty slot is inert by design - the
        keep-alive loop is window-gated."""
        if not self._keep_alive_globally_enabled():
            return
        on = [i for i in range(4) if self.keep_alive_enabled[i]]
        for i in (on if on else range(4)):
            self.toggle_keep_alive(i)

    def set_toon_enabled(self, index, enabled: bool):
        self.enabled_toons[index] = enabled
        self.toon_buttons[index].setChecked(enabled)
        self.apply_visual_state(index)
        self.update_status_label()

    # ── Window update handler ──────────────────────────────────────────────

    def _on_cell_assignment_changed(self, slot_cells):
        """Re-route compact card content when the per-slot 2x2 cell permutation
        changes (e.g. two stacked windows move between columns without the window
        list changing). Skipped in Full mode, where the full layout - not compact -
        owns the shared per-slot widgets; the compact layout re-applies the current
        permutation when it next becomes active (see the layout swap)."""
        if getattr(self, "_mode", "compact") == "full":
            return
        compact = getattr(self, "_compact", None)
        if compact is not None:
            compact.apply_cell_permutation(slot_cells)

    def update_toon_controls(self, window_ids):
        ids_changed = window_ids != self._last_window_ids

        if ids_changed:
            if self._last_window_ids:
                old_enabled = list(self.enabled_toons)
                old_chat    = list(self.chat_enabled)
                old_ka      = list(self.keep_alive_enabled)
                old_rf      = list(self.rapid_fire_enabled)
                old_sels    = [s.currentIndex() for s in self.set_selectors]
                
                old_names   = list(self.toon_names)
                old_styles  = list(self.toon_styles)
                old_colors  = list(self.toon_colors)
                old_laffs   = list(self.toon_laffs)
                old_maxlaffs= list(self.toon_max_laffs)
                old_beans   = list(self.toon_beans)

                for new_idx, wid in enumerate(window_ids):
                    if new_idx >= 4: break
                    if wid in self._last_window_ids:
                        old_idx = self._last_window_ids.index(wid)
                        self.enabled_toons[new_idx]      = old_enabled[old_idx]
                        self.chat_enabled[new_idx]        = old_chat[old_idx]
                        self.keep_alive_enabled[new_idx]  = old_ka[old_idx]
                        self.rapid_fire_enabled[new_idx]  = old_rf[old_idx]
                        self.keep_alive_buttons[new_idx].is_rapid_fire = old_rf[old_idx]
                        self.set_selectors[new_idx].setCurrentIndex(old_sels[old_idx])
                        
                        self.toon_names[new_idx] = old_names[old_idx]
                        self.toon_styles[new_idx] = old_styles[old_idx]
                        self.toon_colors[new_idx] = old_colors[old_idx]
                        self.toon_laffs[new_idx] = old_laffs[old_idx]
                        self.toon_max_laffs[new_idx] = old_maxlaffs[old_idx]
                        self.toon_beans[new_idx] = old_beans[old_idx]
                        
                        if new_idx < len(self.slot_badges):
                            self.slot_badges[new_idx].set_dna(old_styles[old_idx])

                for i in range(4):
                    self.toon_buttons[i].setChecked(self.enabled_toons[i])
                    self.chat_buttons[i].setChecked(self.chat_enabled[i])
                    self.keep_alive_buttons[i].setChecked(self.keep_alive_enabled[i])

            self._last_window_ids = list(window_ids)
            invalidate_port_to_wid_cache()
            clear_stale_names(window_ids)
            # Do not completely blow away toon_names, they are now correctly shifted above.
            self._refresh_toon_name_labels()

        for i in range(4):
            if i >= len(window_ids):
                self.enabled_toons[i] = False
                self.chat_enabled[i]  = True
                self.toon_buttons[i].setChecked(False)
                self.chat_buttons[i].setChecked(True)
                
                # Clear all cached data for this slot
                self.toon_names[i] = None
                self.toon_styles[i] = None
                if i < len(self.slot_badges):
                    self.slot_badges[i].set_dna(None)
                    self.slot_badges[i].set_toon_name(None)
                    self.slot_badges[i].set_cc_auto_species(None)
                    self.slot_badges[i].set_cc_mode(None, None, None, None)
                self.toon_colors[i] = None
                self.toon_laffs[i] = None
                self.toon_max_laffs[i] = None
                self.toon_beans[i] = None
                
                if getattr(self, 'rapid_fire_enabled', None) is not None:
                    self.rapid_fire_enabled[i] = False
                if self.keep_alive_enabled[i]:
                    self.toggle_keep_alive(i)
            elif self.service_running and not self.enabled_toons[i]:
                self.enabled_toons[i] = True
                self.toon_buttons[i].setChecked(True)
            self.apply_visual_state(i)
        self.update_status_label()
        self.schedule_toon_data_fetch(1200)
        self._update_glow_timer()
        # Refresh name labels AFTER the for-loop above clears toon_names
        # for slots whose windows disappeared. The earlier refresh inside
        # `if ids_changed:` ran before those clears, so without this call
        # closed-game slots keep showing the old toon name.
        self._refresh_toon_name_labels()
        self._refresh_toon_stats_labels()
        if not any(self.keep_alive_enabled):
            self._stop_keep_alive()
        self._apply_click_sync_visibility()

    # ── Name handling ──────────────────────────────────────────────────────

    def set_toon_capture_sink(self, sink) -> None:
        """Wire LaunchTab.capture_toon so resolved toon names update recent_toons."""
        self._toon_capture_sink = sink

    def _capture_account_toon(self, wid, toon_name: str, dna: str) -> None:
        if not self._toon_capture_sink or not toon_name:
            return
        from utils.toon_capture_bridge import toon_changed
        from utils.game_registry import GameRegistry
        key = str(wid)
        dna = dna or ""
        if not toon_changed(self._last_captured_toon, key, toon_name, dna):
            return  # unchanged since last refresh -> skip X round-trip + sink
        pid = GameRegistry.pid_for_window(key)   # HOST pid (Flatpak-safe), matches launch
        if pid is not None:
            self._toon_capture_sink(pid, toon_name, dna)
            self._last_captured_toon[key] = (toon_name, dna)

    @Slot(list, list, list, list, list, list, list)
    def _apply_merged_toon_data(self, target_wids, names, styles, colors, laffs, max_laffs, beans):
        wids = list(self.window_manager.ttr_window_ids) if hasattr(self, 'window_manager') and self.window_manager else []
        for source_idx, wid in enumerate(target_wids):
            if wid in wids:
                global_idx = wids.index(wid)
                if global_idx < 4:
                    if source_idx < len(names):
                        self.toon_names[global_idx] = names[source_idx]
                        self._capture_account_toon(
                            wid, names[source_idx],
                            styles[source_idx] if source_idx < len(styles) else "",
                        )
                        self.toon_styles[global_idx] = styles[source_idx]
                        self.toon_colors[global_idx] = colors[source_idx]
                        self.toon_laffs[global_idx] = laffs[source_idx]
                        self.toon_max_laffs[global_idx] = max_laffs[source_idx]
                        self.toon_beans[global_idx] = beans[source_idx]
                        
                        if global_idx < len(self.slot_badges):
                            self.slot_badges[global_idx].set_dna(styles[source_idx] if styles and source_idx < len(styles) else None)
                            self.slot_badges[global_idx].set_toon_name(
                                names[source_idx] if source_idx < len(names) else None
                            )
                        # CC -> TTR transition: a previous CC paint may have hidden the chat
                        # button. TTR slot supports chat; visibility is then masked by the
                        # global Chat Handling mode (non per_toon modes hide regardless).
                        self._set_chat_button_visible(global_idx, True)
        self._refresh_toon_name_labels()
        self._refresh_toon_stats_labels()
        # Defer chrome refresh to the next event-loop tick so any in-progress
        # paint/style cascade triggered by the name change finishes first.
        QTimer.singleShot(0, self._refresh_chrome_after_name_change)

    @Slot(list, list)
    def _apply_cc_toon_info(self, target_wids, infos):
        """Fan out CCToonInfo per slot into name, portrait, chip row,
        compact subtitle."""
        wids = list(self.window_manager.ttr_window_ids) if hasattr(self, 'window_manager') and self.window_manager else []
        for source_idx, wid in enumerate(target_wids):
            if wid not in wids:
                continue
            global_idx = wids.index(wid)
            if global_idx >= 4:
                continue
            info = infos[source_idx] if source_idx < len(infos) else None
            self._cc_toon_infos[global_idx] = info

            if info is None or info.name is None:
                # Empty state: clear name, hide laff/bean (CC slots have no
                # laff/bean stats), hide chips, plain badge.
                # Note: if a slot later switches from CC back to TTR, the TTR
                # data path (_apply_merged_toon_data -> _refresh_toon_stats_labels)
                # will re-show the laff/bean labels on the next poll cycle.
                self.toon_names[global_idx] = None
                if global_idx < len(self.laff_labels):
                    self.laff_labels[global_idx].hide()
                if global_idx < len(self.bean_labels):
                    self.bean_labels[global_idx].hide()
                self._set_chat_button_visible(global_idx, False)
                if global_idx < len(self.slot_badges):
                    self.slot_badges[global_idx].set_toon_name(None)
                    self.slot_badges[global_idx].set_cc_auto_species(None)
                    self.slot_badges[global_idx].set_cc_mode(None, None, None, None)
                self.set_compact_cc_subtitle(global_idx, None, None)
                continue

            # Apply name
            self.toon_names[global_idx] = info.name
            # CC has no TTR-style DNA string; record the name with an empty dna.
            self._capture_account_toon(wid, info.name, "")

            # Hide TTR-only widgets for CC slots: CC log data doesn't expose
            # laff/bean stats, and the chat button is not yet integrated for CC.
            if global_idx < len(self.laff_labels):
                self.laff_labels[global_idx].hide()
            if global_idx < len(self.bean_labels):
                self.bean_labels[global_idx].hide()
            self._set_chat_button_visible(global_idx, False)

            # Apply portrait (CC paint mode in both layouts since the
            # widget is shared between them). If colors missing, fall
            # back to plain mode so a previously-set CC paint doesn't
            # linger.
            if global_idx < len(self.slot_badges):
                badge = self.slot_badges[global_idx]
                if info.dna_colors:
                    badge.set_toon_name(info.name)
                    badge.set_cc_auto_species(info.species_name)
                    _arms, gloves, _legs, head, accent = info.dna_colors
                    badge.set_cc_mode(
                        skin_rgb=head, accent_rgb=accent, gloves_rgb=gloves,
                        emoji=info.species_emoji or "❓",
                    )
                else:
                    badge.set_toon_name(None)
                    badge.set_cc_auto_species(None)
                    badge.set_cc_mode(None, None, None, None)

            # Compact subtitle (shared widget; full mode reuses
            # _compact_cc_subtitles[i] now that full is a structural
            # clone of compact).
            self.set_compact_cc_subtitle(
                global_idx, info.playground, info.zone_name,
            )

        self._refresh_toon_name_labels()

    def _on_toon_names_received(self, names, styles, colors, laffs, max_laffs, beans):
        self._toon_names_ready.emit(list(names))
        self._toon_styles_ready.emit(list(styles))
        self._toon_colors_ready.emit(list(colors))
        self._toon_laffs_ready.emit(list(laffs))
        self._toon_max_laffs_ready.emit(list(max_laffs))
        self._toon_beans_ready.emit(list(beans))

    @Slot(list)
    def _apply_toon_names(self, names: list):
        for i, name in enumerate(names):
            if i < len(self.toon_names):
                self.toon_names[i] = name
            if i < len(self.slot_badges):
                self.slot_badges[i].set_toon_name(name)
        self._refresh_toon_name_labels()
        # Defer chrome refresh to the next event-loop tick so any in-progress
        # paint/style cascade triggered by the name change finishes first.
        # The synchronous variant of this call (commit baae072) raced with
        # Qt's paint pipeline and caused a SIGSEGV use-after-free.
        QTimer.singleShot(0, self._refresh_chrome_after_name_change)

    def _refresh_chrome_after_name_change(self) -> None:
        """Re-run chip + card-brand for each slot whose badge has a game,
        so customizations keyed by toon name get picked up once the names
        have been populated.

        Uses ``slot_badges[i].game`` as the source of truth rather than
        ``apply_visual_state``, so we don't clobber brand state when the
        window isn't yet associated with this slot. The enabled rank is
        inferred from the stripe's current colour saturation so we
        preserve whatever state the prior brand pass left in place
        (full brand vs muted brand)."""
        for i in range(len(self.toon_names)):
            if i >= len(self.slot_badges):
                continue
            game = self.slot_badges[i].game
            if game not in ("cc", "ttr"):
                continue
            enabled = bool(
                i < len(self.enabled_toons)
                and self.enabled_toons[i]
                and self.service_running
            )
            self._apply_chip_for_slot(i, game)
            self._set_card_brand_for_slot(i, game, enabled=enabled)
            self.slot_badges[i].update()

    @Slot(list)
    def _apply_toon_styles(self, styles: list):
        for i, style in enumerate(styles):
            if style != self.toon_styles[i]:
                self.toon_styles[i] = style
                if i < len(self.slot_badges):
                    self.slot_badges[i].set_dna(style)
                    self.apply_visual_state(i)

    @Slot(list)
    def _apply_toon_colors(self, colors: list):
        for i, color in enumerate(colors):
            if color != self.toon_colors[i]:
                self.toon_colors[i] = color
                self.apply_visual_state(i)

    @Slot(list)
    def _apply_toon_laffs(self, laffs: list):
        for i, laff in enumerate(laffs):
            self.toon_laffs[i] = laff
        self._refresh_toon_stats_labels()

    @Slot(list)
    def _apply_toon_max_laffs(self, max_laffs: list):
        for i, max_laff in enumerate(max_laffs):
            self.toon_max_laffs[i] = max_laff
        self._refresh_toon_stats_labels()

    @Slot(list)
    def _apply_toon_beans(self, beans: list):
        for i, bean in enumerate(beans):
            self.toon_beans[i] = bean
        self._refresh_toon_stats_labels()

    @Slot()
    def _refresh_toon_stats_labels(self):
        for i in range(len(self.laff_labels)):
            laff_lbl = self.laff_labels[i]
            bean_lbl = self.bean_labels[i]

            # Only show if we have data for the toon
            window_available = i < len(self._last_window_ids)
            has_data =  self.toon_names[i] is not None

            if window_available and has_data:
                # Update Laff
                claff = self.toon_laffs[i]
                mlaff = self.toon_max_laffs[i]
                if claff is not None and mlaff is not None:
                    laff_lbl.setIcon(make_heart_icon(16))
                    laff_lbl.setText(f" {claff}/{mlaff}")
                    laff_lbl.show()
                else:
                    laff_lbl.hide()
                
                # Update Beans
                cbeans = self.toon_beans[i]
                if cbeans is not None:
                    bean_lbl.setIcon(make_jellybean_icon(16))
                    bean_lbl.setText(f" {cbeans:,}")
                    bean_lbl.show()
                else:
                    bean_lbl.hide()
            else:
                laff_lbl.hide()
                bean_lbl.hide()

    @Slot()
    def _refresh_toon_name_labels(self):
        # Update ONLY the label text. The name font (size/weight) and colour are
        # owned by the active pinwheel layout: compact _populate_cell sets
        # setFont(23, Bold) and set_card_brand writes the colour; full
        # _populate_card sets a matching setFont + stylesheet. This method used to
        # re-apply a stale `font-size: 21px` stylesheet on every refresh, which
        # fought the layout-owned 23 px font — the name flipped 23->21->23 each
        # 5 s cycle (visible judder) and the 3 px sizeHint delta nudged the
        # bottom-row portraits whenever the 2x2 grid had little vertical slack.
        # setText is a no-op when the text is unchanged, so genuine name updates
        # still propagate without disturbing the layout-owned styling.
        for i, (name_label, _) in enumerate(self.toon_labels):
            display = self.toon_names[i] if self.toon_names[i] else f"Toon {i + 1}"
            name_label.setText(display)

    def set_compact_cc_subtitle(self, slot: int, playground, zone_name):
        """Update the Compact UI subtitle for a CC slot. Hides if both
        playground and zone are None."""
        if slot >= len(self._compact_cc_subtitles):
            return
        sub = self._compact_cc_subtitles[slot]
        if not playground:
            sub.setText("")
            sub.hide()
            return
        if zone_name:
            sub.setText(f"\U0001f4cd {playground} \xb7 {zone_name}")
        else:
            sub.setText(f"\U0001f4cd {playground}")
        sub.show()

    # ── Accessors ──────────────────────────────────────────────────────────

    def get_enabled_toons(self):
        return self.enabled_toons

    def get_chat_handling_mode(self) -> str:
        """Return the global chat handling mode as a canonical value
        (focused_only / all_toons / keyset_dynamic / per_toon), normalizing
        legacy simple/advanced and unknown values. Defaults to
        CHAT_HANDLING_MODE_DEFAULT when no settings_manager is wired."""
        from utils.settings_keys import (
            CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_DEFAULT,
            normalize_chat_handling_mode,
        )
        if self.settings_manager is None:
            return CHAT_HANDLING_MODE_DEFAULT
        return normalize_chat_handling_mode(
            self.settings_manager.get(CHAT_HANDLING_MODE, CHAT_HANDLING_MODE_DEFAULT)
        )

    def get_chat_enabled(self):
        """Return the effective per-toon chat-broadcast state for the current
        canonical mode (per_toon=raw list; all_toons=every enabled toon;
        focused_only=none; keyset_dynamic=default-keyset toons), computed by
        compute_effective_chat_enabled.

        Called per keystroke by InputService; cost is O(n) over the
        4-toon list. See compute_effective_chat_enabled for the rule.
        """
        return compute_effective_chat_enabled(
            mode=self.get_chat_handling_mode(),
            raw_chat=self.chat_enabled,
            enabled_toons=self.enabled_toons,
            assignments=self.get_keymap_assignments(),
        )

    def _set_chat_button_visible(self, idx: int, want_visible: bool) -> None:
        """Set per-slot chat-button visibility intent and apply the AND of
        that intent with the global Chat Handling mode.

        Call sites: TTR paint passes True (TTR slot supports chat); CC paint
        passes False (chat button not integrated for CC). The cached intent
        is what apply_chat_handling_mode reads when the global mode flips,
        so a transition away from Per-Toon (manual) mode does not re-show a
        CC slot's button.
        """
        if idx >= len(self.chat_buttons):
            return
        self._chat_button_game_wants_visible[idx] = want_visible
        from utils.settings_keys import CHAT_HANDLING_PER_TOON
        is_per_toon = self.get_chat_handling_mode() == CHAT_HANDLING_PER_TOON
        self.chat_buttons[idx].setVisible(want_visible and is_per_toon)

    def apply_chat_handling_mode(self, mode: str) -> None:
        """Refresh chat-button visibility on every slot to honor the global
        chat handling mode.

        Chat buttons are only shown in Per-Toon (manual) mode (normalizes to
        'per_toon'). Visibility per slot is (mode == per_toon) AND the
        cached per-slot game-type intent in
        self._chat_button_game_wants_visible (set by CC and TTR paint paths
        via _set_chat_button_visible). The button's underlying chat_enabled
        state is preserved across mode flips.

        Idempotent. Called once at startup with the persisted mode and on
        every chat_handling_mode_changed signal from SettingsTab.
        """
        from utils.settings_keys import (
            CHAT_HANDLING_PER_TOON, normalize_chat_handling_mode,
        )
        is_per_toon = normalize_chat_handling_mode(mode) == CHAT_HANDLING_PER_TOON
        for i, btn in enumerate(self.chat_buttons):
            want = (
                self._chat_button_game_wants_visible[i]
                if i < len(self._chat_button_game_wants_visible)
                else True
            )
            btn.setVisible(want and is_per_toon)

    def get_keymap_assignments(self):
        """Return per-toon set indices from the set selector dropdowns."""
        return [self.set_selectors[i].currentIndex() for i in range(4)]

    def get_movement_modes(self):
        """Legacy accessor — returns stub for backward compat."""
        if self.keymap_manager:
            # Return names for preset save/load compatibility
            return [self.set_selectors[i].currentText() for i in range(4)]
        return [self.set_selectors[i].currentText() for i in range(4)]

    def get_key_event_queue(self):
        return self.key_event_queue

    # ── Keep-alive loop ────────────────────────────────────────────────────

    def _reset_ka_cycle(self):
        """Reset the keep-alive cycle timer — progress bars restart from zero."""
        self._ka_cycle_start = time.monotonic()
        self._ka_cycle_event.set()  # wake up the sleep loop so it restarts

    def _on_setting_changed(self, key, value):
        """Called when any setting changes — reset keep-alive cycle if relevant."""
        if key in ("keep_alive_delay", "keep_alive_action"):
            if any(self.keep_alive_enabled):
                self._reset_ka_cycle()
        elif key == "keep_alive_enabled":
            if value:
                # Master flipped on. Refresh per-toon visuals (existing styling
                # path runs apply_visual_state to update enabled/tooltip state)
                # and start the thread if any per-toon flags are set.
                for i in range(4):
                    self.apply_visual_state(i)
                if any(self.keep_alive_enabled):
                    self._start_keep_alive()
            else:
                self._suspend_keep_alive()

            # Reconcile widget visibility. If the user is on the multitoon tab,
            # do it now; otherwise defer until showEvent. The orchestrator
            # is no-op when widgets already match the setting.
            if self.isVisible():
                self._maybe_animate_keep_alive_visibility()

    # ── Sleep inhibitor ───────────────────────────────────────────────────

    def _acquire_sleep_inhibitor(self):
        """Acquire the OS sleep/idle inhibitor off the GUI thread; surface the
        verified status to the UI when it completes.

        acquire() can block up to ~1.5s (it shells out to systemd-inhibit and
        polls), so it runs on a worker thread. A generation guard ensures a
        late result from a worker that was superseded by release/re-acquire can
        never flip the UI back."""
        from services._inhibit_worker import InhibitAcquireWorker
        # Never overwrite the ref to a still-running worker: dropping the last
        # Python ref to a live QThread crashes with "Destroyed while thread is
        # still running". In the normal flow the prior worker was already joined
        # by _release_sleep_inhibitor; this guards a direct re-acquire.
        prev = getattr(self, "_inhibit_worker", None)
        if prev is not None and prev.isRunning():
            prev.wait(5000)
            if prev.isRunning():
                # Pathologically slow acquire still running after the wait:
                # keep a reference so the QThread is never destroyed mid-run.
                # It self-finishes within acquire()'s internal timeouts; prune
                # finished retirees so the list cannot grow unbounded.
                retired = [w for w in getattr(self, "_retired_workers", [])
                           if w.isRunning()]
                retired.append(prev)
                self._retired_workers = retired
        self._inhibit_gen += 1
        gen = self._inhibit_gen
        # No Qt parent: we hold a Python ref via self._inhibit_worker and join
        # it in _release_sleep_inhibitor, so it cannot be GC'd or leak.
        worker = InhibitAcquireWorker(self._sleep_inhibitor)
        worker.status_ready.connect(lambda status, g=gen: self._on_inhibit_status(g, status))
        self._inhibit_worker = worker  # keep a ref so it is not GC'd
        worker.start()

    def _on_inhibit_status(self, gen, status):
        if gen != self._inhibit_gen:
            return  # stale result from a worker superseded by release/re-acquire
        if status.sleep_blocked:
            self.log(f"[KeepAlive] Sleep inhibitor verified ({status.method}).")
        else:
            self.log("[KeepAlive] Could not verify sleep inhibitor; "
                     "the machine may sleep.")
        self.keep_alive_inhibit_status.emit(status)

    def _release_sleep_inhibitor(self):
        """Release the inhibitor, allowing sleep/idle again. Invalidates any
        in-flight worker and joins it so no late result can flip the UI."""
        self._inhibit_gen += 1  # invalidate any in-flight worker result
        w = getattr(self, "_inhibit_worker", None)
        if w is not None and w.isRunning():
            w.wait(2000)  # give a fast acquire a chance to finish first
        # Release UNCONDITIONALLY (not gated on is_active()): if acquire() is on
        # a slow fallback path and outran the wait, it may not have set
        # sleep_blocked yet but will still acquire a holder. SleepInhibitor's
        # reentrant lock makes this release block until that in-flight acquire
        # completes, so the holder is released, never leaked. release() is a
        # safe no-op when nothing is held, and also frees a screensaver-only
        # cookie (which is_active() would not see).
        # Tradeoff: if acquire() is mid-flight on a slow fallback path (only on
        # non-systemd / slow-D-Bus systems), this release blocks on the lock
        # until it finishes. We accept that rare stop-time stall in exchange for
        # a guaranteed-no-leak release rather than a more error-prone deferred
        # scheme.
        self._sleep_inhibitor.release()
        self.log("[KeepAlive] Sleep inhibitor released.")
        if w is not None and not w.isRunning():
            self._inhibit_worker = None  # only drop the ref once run() has returned

    def _start_keep_alive(self):
        if not self._keep_alive_running:
            self._keep_alive_running = True
            self._ka_cycle_start = time.monotonic()
            self._ka_cycle_event.clear()
            self._acquire_sleep_inhibitor()
            self._keep_alive_thread = threading.Thread(
                target=self._run_keep_alive_loop, daemon=True
            )
            self._keep_alive_thread.start()

    def _stop_keep_alive(self):
        self._keep_alive_running = False
        self._ka_cycle_start = 0.0
        self._ka_cycle_event.set()  # wake thread so it exits
        if self._keep_alive_thread is not None and self._keep_alive_thread.is_alive():
            self._keep_alive_thread.join(timeout=2.0)
        self._release_sleep_inhibitor()
        for i in range(4):
            self.keep_alive_buttons[i].set_progress(0.0)
            if i < len(self.ka_progress_bars):
                self.ka_progress_bars[i].set_progress(0.0)

    def _suspend_keep_alive(self):
        """Stop KA execution and clear button visuals while preserving per-toon
        flags. Called when the master toggle flips off — per-toon setup is the
        user's, the master flag is just whether the feature class is enabled."""
        self._stop_keep_alive()
        for i in range(4):
            if i < len(self.keep_alive_buttons):
                btn = self.keep_alive_buttons[i]
                btn.setGraphicsEffect(None)
                btn.set_progress(0.0)
        self._update_glow_timer()
        for i in range(4):
            self.apply_visual_state(i)

    def _get_keep_alive_delay(self) -> float:
        if not self.settings_manager:
            return 60
        delay_str = self.settings_manager.get("keep_alive_delay", "30 sec")
        return {
            "Rapid Fire": 0.25, "1 sec": 1, "5 sec": 5, "10 sec": 10, "30 sec": 30,
            "1 min": 60, "3 min": 180, "5 min": 300, "10 min": 600
        }.get(delay_str, 60)

    def _keep_alive_globally_enabled(self) -> bool:
        """Return True iff the user has opted in to Keep-Alive via Settings.
        Gates per-toon button availability, toggle_keep_alive, and the
        keep-alive thread loop."""
        return bool(
            self.settings_manager
            and self.settings_manager.get("keep_alive_enabled", False)
        )

    def _init_keep_alive_visibility(self) -> None:
        """One-shot initial-paint helper: set per-toon KA widget visibility
        and the compact ka_group stretch factor to match the current master
        flag. Called once at the end of build_ui. Subsequent visibility
        changes are owned by the animation completion handlers."""
        target_visible = self._keep_alive_globally_enabled()
        for i in range(4):
            if i < len(self.keep_alive_buttons):
                self.keep_alive_buttons[i].setVisible(target_visible)
            if i < len(self.ka_progress_bars):
                self.ka_progress_bars[i].setVisible(target_visible)
            if i < len(self.help_buttons):
                # Help button is the inverse of the KA button — surfaces only
                # when the user could opt in.
                self.help_buttons[i].setVisible(not target_visible)
        # Compact: flip ka_group's stretch factor in its middle layout.
        if hasattr(self, "_compact"):
            self._compact._set_keep_alive_collapsed(not target_visible)
        if hasattr(self, "_full") and self._full is not None:
            self._full._set_keep_alive_collapsed(not target_visible)

    def showEvent(self, event):
        """When the multitoon tab becomes visible, reconcile per-toon KA widget
        visibility with the master setting if they disagree. This is the
        deferred-animation trigger point."""
        super().showEvent(event)
        self._maybe_animate_keep_alive_visibility()
        self._update_glow_timer()  # resume repaint timers when back on-page

    def hideEvent(self, event):
        """Stop the glow/bar repaint timers when this tab leaves the screen
        (page switch). Phase is preserved via the monotonic cycle anchor."""
        super().hideEvent(event)
        self._update_glow_timer()

    def _maybe_animate_keep_alive_visibility(self) -> None:
        """Compare each per-toon KA widget's hide-state to the master setting.
        If any widget disagrees, trigger the orchestrator. No-op if all match."""
        target_visible = self._keep_alive_globally_enabled()
        # Compare against the first slot's ka_btn — the per-slot widgets are
        # all updated together, so checking one is sufficient.
        if not self.keep_alive_buttons:
            return
        currently_visible = not self.keep_alive_buttons[0].isHidden()
        if currently_visible == target_visible:
            return
        self._animate_keep_alive_visibility(target_visible)

    def _animate_keep_alive_visibility(self, target_visible: bool) -> None:
        """Orchestrator: dispatch the visibility change to the active layout's
        animation method. The inactive layout's widgets are set instantly
        (no animation), so state stays consistent across layout swaps.

        Help buttons snap-flip (no fade) at the start of the animation so the
        user sees a single clean swap: KA fades in as the help button vanishes,
        and vice versa."""
        for i in range(4):
            if i < len(getattr(self, "help_buttons", [])):
                self.help_buttons[i].setVisible(not target_visible)
        if self._mode == "full" and hasattr(self, "_full") and self._full is not None:
            self._full._animate_keep_alive_visibility(target_visible)
        elif hasattr(self, "_compact"):
            self._compact._animate_keep_alive_visibility(target_visible)
        else:
            for i in range(4):
                if i < len(self.keep_alive_buttons):
                    self.keep_alive_buttons[i].setVisible(target_visible)
                if i < len(self.ka_progress_bars):
                    self.ka_progress_bars[i].setVisible(target_visible)

    def _cancel_keep_alive_animations(self) -> None:
        """Stop any in-flight KA animations on both layouts. Called before
        layout swap so animation finish handlers don't fire on widgets being
        reparented."""
        for layout in (getattr(self, "_compact", None), getattr(self, "_full", None)):
            if layout is None:
                continue
            anims = getattr(layout, "_ka_anims", None)
            if not anims:
                continue
            for anim in anims:
                anim.stop()
            layout._ka_anims = []

    def _reconcile_keep_alive_visibility_instant(self) -> None:
        """Set per-toon KA widget visibility to match the master setting,
        instantly (no animation). Called after a layout swap or any other
        path where animation isn't appropriate."""
        target_visible = self._keep_alive_globally_enabled()
        for i in range(4):
            if i < len(self.keep_alive_buttons):
                # Clear any leftover graphics effect from a stopped animation.
                self.keep_alive_buttons[i].setGraphicsEffect(None)
                self.keep_alive_buttons[i].setVisible(target_visible)
            if i < len(self.ka_progress_bars):
                self.ka_progress_bars[i].setGraphicsEffect(None)
                self.ka_progress_bars[i].setVisible(target_visible)
            if i < len(getattr(self, "help_buttons", [])):
                # Help button visibility is the inverse of the KA button. No
                # graphics effect to clear; the help button never participates
                # in the KA animation path.
                self.help_buttons[i].setVisible(not target_visible)
        if hasattr(self, "_compact"):
            self._compact._set_keep_alive_collapsed(not target_visible)
        if hasattr(self, "_full") and self._full is not None:
            self._full._set_keep_alive_collapsed(not target_visible)

    def _run_keep_alive_loop(self):
        try:
            last_normal_fire = 0.0
            last_rapid_fire = 0.0
            while self._keep_alive_running:
                # Run the loop every 1 second max if there is a rapid fire, else delay
                if any(getattr(self, 'rapid_fire_enabled', [False]*4)):
                    timeout_val = 1.0
                else:
                    timeout_val = self._get_keep_alive_delay()
                
                self._ka_cycle_event.wait(timeout=timeout_val)
                if self._ka_cycle_event.is_set():
                    self._ka_cycle_event.clear()
                    if not self._keep_alive_running:
                        break
                        
                if not self._keep_alive_running:
                    break

                # Master flag re-check: if the user opted out while we were
                # sleeping, skip this cycle. _suspend_keep_alive will stop
                # the thread soon after; this is defense in depth so at most
                # one in-flight burst can leak.
                if not self._keep_alive_globally_enabled():
                    continue

                now = time.monotonic()
                normal_delay = self._get_keep_alive_delay()
                
                fire_toons = []
                if now - last_rapid_fire >= 1.0:
                    rapid_toons = [i for i, state in enumerate(getattr(self, 'rapid_fire_enabled', [False]*4)) if state and self.keep_alive_enabled[i]]
                    fire_toons.extend(rapid_toons)
                    if rapid_toons:
                        last_rapid_fire = now
                        
                if now - last_normal_fire >= normal_delay or last_normal_fire == 0.0:
                    normal_toons = [i for i, state in enumerate(self.keep_alive_enabled) if state and not getattr(self, 'rapid_fire_enabled', [False]*4)[i]]
                    fire_toons.extend(normal_toons)
                    if normal_toons:
                        last_normal_fire = now
                        self._ka_cycle_start = now
                
                fire_toons = list(set(fire_toons))
                if not fire_toons:
                    continue

                action = self.settings_manager.get("keep_alive_action", "jump") if self.settings_manager else "jump"
                fired = _dispatch_keep_alive_cycle(
                    action=action,
                    fire_toons=fire_toons,
                    window_manager=self.window_manager,
                    keymap_manager=self.keymap_manager,
                    input_service=self.input_service,
                )

                action_labels = {"jump": "Jump", "book": "Book", "up": "Move Forward"}
                label = action_labels.get(action, action)
                if fired > 0:
                    self.log(f"[KeepAlive] Sent '{label}' to {fired} toon(s)")
                elif fire_toons:
                    self.log(f"[KeepAlive] no toons matched action '{action}' this cycle")
        except Exception as e:
            self.log(f"[KeepAlive] Error: {e}")

    def log(self, msg):
        if self.logger:
            self.logger.append_log(msg)
        else:
            print(msg)

    def shutdown(self):
        self._stop_keep_alive()
        self.refresh_timer.stop()
        self._toon_fetch_timer.stop()
        self._glow_timer.stop()
        self._bar_timer.stop()
        # Rendition fetches now go through the shared RenditionPoseFetcher
        # singleton; per-badge cancel() is no longer needed (stale results
        # are filtered by (dna, pose) match on the GUI thread).
        self.input_service.shutdown()
        if self.click_sync_service is not None:
            self.click_sync_service.shutdown()
        if self._click_sync_backend is not None:
            self._click_sync_backend.disconnect()


def _dispatch_keep_alive_cycle(action, fire_toons, window_manager, keymap_manager,
                                input_service):
    """Dispatch one keep-alive cycle to the requested toon slots.

    Returns the number of toons that actually received a keypress (after
    per-toon game / binding resolution). A return of 0 with a non-empty
    fire_toons list means every candidate was skipped.

    The key sent is ALWAYS the game client's own binding, mirroring the
    router's outbound rule (_send_logical_action_km): CC movement uses the
    WASD-lock canonical, everything else uses set 0 (the config-driven
    Default that tracks the client's settings file). A toon's assigned SET
    must never leak here - sets are an input-translation layer for what the
    USER presses, not what the client understands. Resolving through the
    set sent raw Alt_R (an Arrows-set jump rebind) to a TTR client whose
    real jump is space, which the client read as its side-agnostic 'alt'
    stickerBook binding: the book toggled open every keep-alive cycle.
    """
    from utils import cc_isolation

    logical = "forward" if action == "up" else action
    cc_canonical = cc_isolation.canonical_to_ttmt_keysyms(
        cc_isolation.DEFAULT_CANONICAL
    )
    window_ids = window_manager.get_window_ids()
    # Chat gate: keep-alive must never type its key into an open chat box
    # (the focused toon's during a capture, or a bg box TTMT mirrored open).
    # Fail-open via getattr so bare test stubs without the method keep the
    # historical behavior.
    chat_skip = getattr(input_service, "keep_alive_skip_window", None)
    fired = 0
    for i in fire_toons:
        if i >= len(window_ids):
            continue
        wid = window_ids[i]
        if chat_skip is not None:
            try:
                if chat_skip(wid):
                    continue
            except Exception:
                pass
        try:
            game = GameRegistry.instance().get_game_for_window(str(wid))
        except Exception:
            game = None
        if game not in ("ttr", "cc"):
            continue
        if not logical_actions.supports(game, logical):
            continue
        key = cc_canonical.get(logical) if game == "cc" else None
        if not key:
            key = keymap_manager.get_key_for_action(game, 0, logical)
        if not key:
            continue
        input_service.send_keep_alive_to_window(wid, key)
        fired += 1
    return fired

