"""The Roll Call design's numbers, in logical px, and its colours.

The stage is theme-independent: none of this changes in light theme.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPointF
from PySide6.QtGui import QColor


def rgba(r: int, g: int, b: int, a: float = 1.0) -> QColor:
    return QColor(r, g, b, round(max(0.0, min(1.0, a)) * 255))


def white(a: float) -> QColor:
    return rgba(255, 255, 255, a)


# ── Colours ────────────────────────────────────────────────────────────────
STAGE_BLUE = QColor("#1d4a7a")
STAGE_SHADE = (13, 27, 48)                 # the left-to-right gradient's colour
STAGE_GLOW = (140, 190, 255)               # the radial highlight's colour

GOLD = QColor("#d4a017")
GOLD_B = QColor("#e8c14d")
GOLD_INK = QColor("#231a04")
BLUE = QColor("#0077ff")
BLUE_B = QColor("#3399ff")
GREEN = QColor("#3da343")
GREEN_B = QColor("#56d66a")
RED = QColor("#b34848")
RED_B = QColor("#d95757")
RED_HOVER = QColor("#cc5e5e")
ERROR_TEXT = QColor("#ffb4b4")
PURPLE_B = QColor("#a87cf0")
TEAL_B = QColor("#4dd2c3")
KEEP_ALIVE = QColor("#ff9500")
KEEP_ALIVE_B = QColor("#ffb04d")
WARN_BG = QColor("#3a2f1a")
WARN_BORDER = QColor("#ffaa00")
WARN_TEXT = QColor("#ffcc99")
WARN_BTN_TEXT = QColor("#ffd9a3")
CARD_BG = QColor("#252525")
CARD_BORDER = QColor("#363636")
CARD_DIVIDER = QColor("#2e2e2e")
BTN_BG = QColor("#333333")
BTN_BORDER = QColor("#444444")
BTN_HOVER = QColor("#3e3e3e")
TEXT_SECONDARY = QColor("#bbbbbb")
TEXT_MUTED = QColor("#888888")
TRAFFIC_MIN = QColor("#febc2e")
TRAFFIC_CLOSE = QColor("#ff5f56")
TRAFFIC_MIN_GLYPH = QColor("#7a4e00")
TRAFFIC_CLOSE_GLYPH = QColor("#7a1410")
FLOOR_BG = rgba(8, 16, 30, 0.74)
PANEL_BG = rgba(17, 17, 17, 0.92)

HIGHLIGHT_COLORS = (GOLD_B, PURPLE_B, TEAL_B)

# ── Motion ─────────────────────────────────────────────────────────────────


def bezier(x1: float, y1: float, x2: float, y2: float) -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0))
    return curve


EASE_SETTLE = bezier(0.22, 1.0, 0.36, 1.0)       # things that settle
EASE_ARRIVE = bezier(0.22, 1.2, 0.36, 1.0)       # toons and sheets: small overshoot
EASE_HOP = bezier(0.3, 1.4, 0.5, 1.0)
EASE_KNOB = bezier(0.22, 1.4, 0.36, 1.0)

COPY_ENTER_MS = 420
TICK_ENTER_MS = 320
RISE_PX = 7
TOON_FADE_MS = 260
TOON_MOVE_MS = 460
TOON_DROP_PX = 34
TOON_SMALL_SCALE = 0.84
HOP_MS = 620
HOP_PX = 24
HOP_STAGGER_MS = 90
SOLO_RISE_MS = 520
PANEL_MS = 440
SHEET_MOVE_MS = 460
SHEET_FADE_MS = 220
SCRIM_MS = 260
PRESS_MS = 140
KNOB_MS = 220

SLOT_TILTS = (-2.0, 1.5, -1.0, 2.0)

# ── Geometry ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Variant:
    """One window size's layout."""

    name: str
    width: int                # 0: follows the host (the sheet)
    height: int
    radius: int
    border_alpha: float
    mark: tuple[int, int, int] | None      # wordmark left, top, height
    lights: bool
    copy_left: int
    copy_top: int
    copy_bottom: int
    copy_width: int
    crew_x: int               # where the crew area starts (ignored by the sheet)
    floor_h: int
    headline_px: int
    headline_md_px: int
    actions_gap_top: int
    gold_h: int
    gold_px: int
    gold_pad: int
    ghost_px: int
    ghost_pad: int
    toon_pose: str            # "wave" | "bust"
    toon_size: int
    toon_first_dx: int
    toon_pitch: int
    toon_bottom: int
    placeholders: bool        # dashed empty slots (large window only)


LARGE = Variant(
    name="large", width=780, height=480, radius=16, border_alpha=0.14,
    mark=(30, 22, 32), lights=True,
    copy_left=34, copy_top=30, copy_bottom=64, copy_width=300, crew_x=300,
    floor_h=64, headline_px=36, headline_md_px=30, actions_gap_top=18,
    gold_h=44, gold_px=14, gold_pad=20, ghost_px=13, ghost_pad=14,
    toon_pose="wave", toon_size=236, toon_first_dx=-6, toon_pitch=82,
    toon_bottom=52, placeholders=True,
)

SMALL = Variant(
    name="small", width=580, height=300, radius=16, border_alpha=0.14,
    mark=(22, 16, 24), lights=False,
    copy_left=24, copy_top=36, copy_bottom=52, copy_width=240, crew_x=262,
    floor_h=52, headline_px=25, headline_md_px=25, actions_gap_top=14,
    gold_h=36, gold_px=12, gold_pad=13, ghost_px=12, ghost_pad=13,
    toon_pose="bust", toon_size=156, toon_first_dx=-2, toon_pitch=54,
    toon_bottom=52, placeholders=False,
)

SHEET = Variant(
    name="sheet", width=0, height=310, radius=12, border_alpha=0.16,
    mark=None, lights=False,
    copy_left=22, copy_top=0, copy_bottom=52, copy_width=278, crew_x=0,
    floor_h=52, headline_px=26, headline_md_px=26, actions_gap_top=18,
    gold_h=40, gold_px=13, gold_pad=16, ghost_px=13, ghost_pad=16,
    toon_pose="bust", toon_size=178, toon_first_dx=0, toon_pitch=62,
    toon_bottom=52, placeholders=False,
)

SHEET_INSET = 14          # from the window's left and right edges, and below the scrim's top
SOLO_SIZE = 236           # the What's new toon
SOLO_RIGHT = -6

PANEL_W = 440
LIGHT_DOT = 16
LIGHT_HIT = 22
LIGHT_GAP = 8
LIGHT_INSET = 12

FOCUS_PAD = 4             # room every control keeps around itself for its focus ring
