# Multitoon Full UI & Window-Maximize Layout Design

A dual-layout system for the Multitoon tab plus a project-wide refresh of the dark and light color palettes, fixing how the app behaves when the user maximizes the window.

## Problem

When the user maximizes the window (or drags it wider than ~900 px), the Multitoon tab's outer card stretches to fill the full viewport width. Toon cards inflate horizontally while their height stays fixed, so the active card becomes a long, sparse strip with the portrait pinned to the left and a vast empty band running across to the controls. It looks bad and wastes the extra screen real estate.

The Launch tab already handles wide windows correctly: account cards are clamped to 480 px and centered (`setMaximumWidth(480)` + `Qt.AlignHCenter`). The Multitoon tab has no such clamp, and adding one would just leave the same compact UI floating in a sea of background — which the user explicitly does not want for the tab where most of the time is spent.

The user also wants two adjacent palette changes folded into the same spec:
1. The current Catppuccin/indigo dark palette is replaced with a charcoal + saturated true-color palette.
2. A refined light palette (cool slate scale) so light mode reads as deliberately designed rather than an inverted dark theme.

## Goals

- The Multitoon tab uses one of two distinct layouts, **Compact** or **Full**, chosen by window size.
- Compact is the layout currently shipping (unchanged structurally). Between the minimum window width and the Full breakpoint, cards resize naturally; they do not visually deform.
- Full is a new 2×2 grid of taller toon cards designed for windows ≥ 1280×800. It is bespoke — not a reflowed Compact layout.
- The transition between layouts has hysteresis so a user dragging the window border across the breakpoint does not see flicker.
- The Launch, Keymap, Settings, Invasions, Debug, and Credits tabs use the existing clamp-and-center pattern when the window is wider than their natural content.
- Dark mode uses the new charcoal palette; light mode uses the new cool-slate palette. Both replace the current `get_theme_colors()` returns wholesale.
- The new layout and palettes ship together in a single release.

## Non-goals

- Bespoke Full UIs for tabs other than Multitoon. Launch tab will get one in a future spec; this spec only adds clamp-and-center for the other tabs.
- A user-facing toggle for layout mode. Layout follows window size, period.
- Per-card layout switching. Both layouts always show four toon slots; the Full UI does not collapse to fewer cards on smaller screens.
- Re-theming the splash, login dialog, or installer chrome. Out of scope.
- Animating individual toon cards as they appear, beyond the layout-swap fade.

## Scope summary

- **`utils/theme_manager.py`**: new color values returned from `get_theme_colors()` for both `is_dark=True` and `is_dark=False`. Token names stay the same.
- **`main.py`**: detect window-size threshold, call into the Multitoon tab's `set_layout_mode()`, and broadcast the same to other tabs that just need a max-width applied.
- **`tabs/multitoon_tab.py`**: refactor to support two layouts. `MultitoonTab` becomes a `QStackedWidget` of `_CompactLayout` and `_FullLayout`. Both reuse the same widget instances (portraits, set selectors, etc.) so state survives a layout swap.
- **Other tabs**: a small clamp on the outermost content frame, centered horizontally, for any tab that does not already have one.

## Architecture

### Layout selection

`MultiToonTool` (the `QMainWindow` subclass in `main.py`) gains a `_layout_mode` attribute (`"compact"` or `"full"`) and overrides `resizeEvent`. After every resize:

```
size = self.size()
target = "full" if (size.width() >= W_FULL and size.height() >= H_FULL) else "compact"
if target == self._layout_mode:
    return
# hysteresis: only swap if we're past the deadband
if target == "full" and (size.width() < W_FULL + DEADBAND_W or size.height() < H_FULL + DEADBAND_H):
    return
if target == "compact" and (size.width() > W_FULL - DEADBAND_W and size.height() > H_FULL - DEADBAND_H):
    return
self._set_layout_mode(target)
```

Constants:

- `W_FULL = 1280`, `H_FULL = 800` — the breakpoint.
- `DEADBAND_W = 80`, `DEADBAND_H = 60` — half-widths of the deadband. Practical effect on width: swap to Full needs ≥ 1360, swap back to Compact needs ≤ 1200. Same logic on height: ≥ 860 to enter Full, ≤ 740 to leave it. (Height triggers are independent of width — drop either dimension below its lower bound and we go back to Compact.)

`_set_layout_mode(target)` runs the cross-fade transition described in the **Cross-fade animation** section below; the actual call to `tab.set_layout_mode(target)` happens at the fade's midpoint, not before it.

If `prefers-reduced-motion` is detected (Qt does not expose this directly; we treat the existing `settings_manager` value `disable_animations` as the proxy), the swap is instant.

### MultitoonTab layout swap

`MultitoonTab.__init__` builds shared widgets first (one `ToonPortraitWidget`, one `SetSelectorWidget`, one enable button, etc., per slot). It then constructs both `_CompactLayout` and `_FullLayout`, parenting the shared widgets into whichever layout is currently active and reparenting on swap.

```python
class MultitoonTab(QWidget):
    def __init__(self, ...):
        ...
        self._build_shared_widgets()  # 4 portraits, 4 selectors, 4 enable btns, etc.
        self._stack = QStackedWidget(self)
        self._compact = _CompactLayout(self)
        self._full = _FullLayout(self)
        self._stack.addWidget(self._compact)
        self._stack.addWidget(self._full)
        self._compact.populate(self.shared_widgets)
        self._stack.setCurrentWidget(self._compact)

    def set_layout_mode(self, mode: str):
        if mode == self._mode:
            return
        target = self._full if mode == "full" else self._compact
        # reparent shared widgets to target before showing it
        target.populate(self.shared_widgets)
        self._stack.setCurrentWidget(target)
        self._mode = mode
```

`shared_widgets` is a list of four dicts (one per slot), each holding references to that slot's portrait, name label, laff label, beans label, enable button, chat button, keep-alive button, keep-alive bar, and set selector. Both layouts know how to consume one such dict.

This keeps state (selected set, active enable, in-flight portrait fetch, `KeepAliveBtn` charge state) attached to widgets that survive the swap.

### Compact layout

`_CompactLayout` is the existing layout, lifted out of `MultitoonTab.__init__` essentially verbatim, plus one change: the outer card gets `setMaximumWidth(720)` and `Qt.AlignHCenter`. This keeps it compact on a wide window when the breakpoint hasn't been hit yet (e.g. user is at 1100 px wide, below the 1280 trigger but well past the 720 natural width). 720 px matches what the layout looks like at the default 560×650 window size with a bit of headroom. Below 720 px, the Multitoon outer card hits the column width and shrinks naturally with the window; above 720 px (up to the 1280 trigger), it stays at 720 and the extra width becomes margin.

### Full layout

`_FullLayout` is a top-down vertical layout with two stacked sections.

**Section 1 — service bar.** A single rounded card spanning the column width, padded 18×24 px:

- Left: the existing toggle service button, restyled to 18 px font, 14×28 padding, `bg_input` background. Reads "▶ Start Service" / "⏸ Stop Service".
- Right: profile pill row (5 pills, 34×34 px circles, font 13 px, weight 600) and a refresh button (32×32 circle).
- Bottom strip: 4 status dots (8×8 px, accent-green when active, `border_muted` when inactive) and "N toons running" text in `text_secondary`, 12 px.

**Section 2 — 2×2 toon card grid.** Each cell is a `_FullToonCard`, `min-height: 200px`, padded 18 px.

`_FullToonCard` for an **active** slot uses a 2-column grid:

```
[ portrait 104×104 ]  [ name 22 px / 600 weight ]                [ TTR pill, abs top-right ]
                      [ stat: LAFF: 120/140  ]
                      [ stat: JB: 4,237 ]
[ controls row spanning both columns ]
```

- Portrait is `ToonPortraitWidget` rendered at 104 px (existing widget supports configurable size).
- Discord-style status indicator: a `QLabel` ring of 32 px, `bg_card` color, positioned absolutely at portrait's bottom-right (`-2, -2`). On top of it, a 24 px filled circle in the active accent (green for active, muted gray for inactive). Z-order: portrait → ring → dot. Implemented via `QPainter` `paintEvent` on a custom small widget so the ring and dot composite correctly without bleed.
- Name label uses `ElidingLabel`, padding-right 60 px so it doesn't run under the TTR pill.
- Stats use tabular figures so the digits don't shift width as values update. PySide6 path: `QFont.setFeature("tnum", 1)` (PySide6 ≥ 6.5 exposes this; the project's `requirements.txt` already pins a newer version). If that call ever fails on an older Qt build, fall back to `setStyleHint(QFont.TypeWriter, QFont.PreferDefault)` for the stats labels only — visually acceptable.
- Game pill: 10 px font, 700 weight, top-right absolute. `TTR` = violet pill, `CC` = blue pill (accent_blue_btn).
- Controls row: a `QHBoxLayout` of fixed-32 px-tall items in this order:
  1. Enable button (variable width, ~80 px, padded 0×14, "Enabled" / "Enable", green when active).
  2. Chat button (32×32 square).
  3. Keep-alive button (32×32 square, same colors as today).
  4. Keep-alive progress bar (90×8 px track, fills with accent-orange).
  5. `addStretch()` spacer.
  6. Set selector (variable width, padded 0×14, accent_blue_btn).

For an **inactive** slot, `_FullToonCard` shows:

```
[ "Toon N" label, 14 px / 600 weight, top-left ]
[ centered empty area: 32 px circle icon at 0.5 opacity, then "No game detected" 12 px text ]
```

### Cross-fade animation

The `_set_layout_mode` cross-fade reuses the same animation infrastructure as `nav_select` (lines ~337-358 in `main.py`). It runs as fade-out → swap → fade-in, sequentially:

- Phase 1 (0–80 ms): fade `MultitoonTab` from opacity 1.0 → 0.0 with `QEasingCurve.OutCubic`.
- Mid-point (80 ms): call `tab.set_layout_mode(target)`, which calls `populate(shared_widgets)` on the target layout and then `_stack.setCurrentWidget(target)`.
- Phase 2 (80–160 ms): fade back from 0.0 → 1.0 with `QEasingCurve.OutCubic`.

Total duration 160 ms. If `disable_animations` is set, both phases are skipped and the swap is instant.

### Other tabs at large sizes

Tabs that currently stretch (Keymap, Settings, Invasions, Debug, Credits) get a clamp on their topmost content frame:

```python
content.setMaximumWidth(720)
parent_layout.addWidget(content, alignment=Qt.AlignHCenter)
```

The Launch tab already does this at 480 px and is left untouched.

## Theme palette

`get_theme_colors()` is rewritten end-to-end. Token names and structure stay the same so callers don't change.

The palette follows the **Material 3 primary / on-primary pattern**: text-bearing accent surfaces (Enable button, Set selector, Stop Service, game pills, slot badges) pair with a single `text_on_accent` token that clears WCAG AA. Decorative accents (status dots, success-strip borders, segment fills) keep the more saturated values because they only need to satisfy the 3:1 UI-component minimum.

Why two roles per accent: light and dark mode have inverted constraints. In light mode, an accent surface is darker than the page bg, so it pairs naturally with white text — the accent itself just needs to be dark enough (~5:1) for that text. In dark mode, the accent surface needs to be brighter than the dark page bg, which makes white text fail; the standard fix (Material 3, Apple HIG, iOS) is to flip to dark text on a brighter surface. The `text_on_accent` token encodes "whatever color the bright text should be on every accent in this theme."

### Dark (charcoal + saturated true colors)

```
bg_app:        #1a1a1f          # was #1a1a1a
bg_card:       #2a2a30          # was #252525
bg_card_inner: #2f2f36
bg_input:      #1e1e23
sidebar_bg:    #131316
border_card:   #35353c          # was #363636
border_muted:  #2c2c33

text_primary:   #e8e8ed         # was #ffffff (less harsh on charcoal)
text_secondary: #c8c8d0
text_muted:     #888890
text_disabled:  #5c5c64

# Text-bearing accent surfaces — pair with text_on_accent below.
text_on_accent:      #0f172a    # slate-900, AA on every accent below
accent_green:        #4ade80    # green-400, ~9.7:1 vs text_on_accent (AAA)
accent_blue_btn:     #60a5fa    # blue-400,  ~6.7:1 vs text_on_accent (AA, near-AAA)
accent_red:          #f87171    # red-400,   ~6.3:1 vs text_on_accent (AA)

# Icon-only / non-text-bearing accent — 3:1 UI minimum applies.
accent_orange:       #c66d2e    # used by KA button (icon only)

slot_1: #5b9bf5  (unchanged)
slot_2: #4ade80  (unchanged)
slot_3: #f59e42  (unchanged)
slot_4: #b07cf5  (unchanged — slot badges use existing dark-on-light pattern; not changed in this branch)

# Decorative tokens — no text on them, kept saturated for visual punch.
status_dot_active:   #3aaa5e   # green
status_dot_idle:     #45454c
segment_active:      #3aaa5e

# Game pills — text-bearing, pair with text_on_accent.
game_pill_ttr:       #a78bfa    # violet-400, ~6.2:1 vs text_on_accent
game_pill_cc:        #60a5fa    # matches accent_blue_btn
```

### Light (cool slate)

```
bg_app:        #f8fafc          # was #f0f0f0 (slate-50, cool)
bg_card:       #ffffff
bg_card_inner: #f1f5f9
bg_input:      #ffffff
sidebar_bg:    #e8ecf1          # cooler than #e2e2e2
border_card:   #e2e8f0          # slate-200, was #d4d4d4
border_muted:  #e8ecf1

text_primary:   #0f172a         # slate-900, 17.6:1 on white (AAA)
text_secondary: #334155         # slate-700, 10.7:1 on white (AAA)
text_muted:     #475569         # slate-600, 7.2:1 (AAA)
text_disabled:  #64748b         # slate-500, 4.6:1 (AA)

# Text-bearing accent surfaces — pair with text_on_accent below.
text_on_accent:      #ffffff    # white, AA on every accent below
accent_green:        #15803d    # green-700, 5.0:1 vs white (AA)
accent_blue_btn:     #2563eb    # blue-600,  5.7:1 vs white
accent_orange:       #c2410c    # orange-700, 5.0:1 vs white
accent_red:          #b91c1c    # red-700,   6.2:1 vs white

slot_1: #2563eb     # blue-600,   5.7:1 vs white — text-bearing
slot_2: #15803d     # green-700,  5.0:1 vs white — text-bearing (matches accent_green)
slot_3: #c2410c     # orange-700, 5.0:1 vs white
slot_4: #7c3aed     # violet-600, 5.4:1 vs white

# Decorative tokens — no text on them, vibrant green-600 for visual punch.
status_dot_active:   #16a34a
status_dot_idle:     #cbd5e1     # slate-300
segment_active:      #16a34a

# Game pills — text-bearing, pair with text_on_accent.
game_pill_ttr:       #7c3aed     # violet-600, 5.4:1 vs white
game_pill_cc:        #2563eb     # matches accent_blue_btn
```

Card shadow: existing `apply_card_shadow()` helper continues to apply; in light mode it now uses `rgba(15, 23, 42, 0.06)` (slate-900 at low alpha) instead of `rgba(0,0,0,0.10)` for a less muddy shadow.

### Contrast verification

All text-bearing accents in **light mode** clear WCAG AA (≥4.5:1) against `text_on_accent = #ffffff`:
- `accent_green #15803d` — 5.0:1 ✓
- `accent_blue_btn #2563eb` — 5.7:1 ✓
- `accent_orange #c2410c` — 5.0:1 ✓
- `accent_red #b91c1c` — 6.2:1 ✓
- `game_pill_ttr #7c3aed` — 5.4:1 ✓
- All four slot badges — see inline notes above

All text-bearing accents in **dark mode** clear WCAG AA against `text_on_accent = #0f172a`:
- `accent_green #4ade80` — ~9.7:1 ✓ (AAA)
- `accent_blue_btn #60a5fa` — ~6.7:1 ✓
- `accent_red #f87171` — ~6.3:1 ✓
- `game_pill_ttr #a78bfa` — ~6.2:1 ✓

Dark-mode `accent_orange #c66d2e` is used only on the KA icon-only button (UI component, 3:1 minimum) and meets that bar against the white icon.

Decorative accents (status dots, segment_active, slot badge fills in dark mode) sit on the card background and are governed by 3:1 UI-component contrast, not 4.5:1 text contrast, since no text or icon sits on top of them.

## Component details

### Status dot widget

A small custom `QWidget`, `_StatusIndicator`, 32×32 px:

```python
class _StatusIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self._active = False
        self._ring_color = QColor("#2a2a30")  # set by apply_theme
        self._dot_color = QColor("#3aaa5e")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Ring (card-bg color), 32 px, fills entire widget
        p.setBrush(self._ring_color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, 32, 32)
        # Dot, 24 px, centered (4 px ring on each side)
        p.setBrush(self._dot_color if self._active else QColor("#45454c"))
        p.drawEllipse(4, 4, 24, 24)
```

The widget is positioned absolutely at the portrait's bottom-right, offset (-2, -2). The ring color is set from the parent card's `bg_card` token so the ring blends into the card and creates the "cutout" illusion when overlapping the portrait edge. Theme changes update both colors via `apply_theme(c, is_dark)` on the indicator.

When status is "running", the dot pulses: `QPropertyAnimation` on a custom `glow_intensity` property, 1500 ms loop, ease-in-out, drawing a `box-shadow`-equivalent (extra outer circle at low alpha) in `paintEvent`. Disabled when `disable_animations` is set.

### Game pill

A `QLabel` styled via stylesheet:

```css
padding: 3px 10px;
border-radius: 10px;
font-size: 10px;
font-weight: 700;
letter-spacing: 0.5px;
background: <game_pill_ttr or game_pill_cc>;
color: white;
```

Text is "TTR" or "CC". Positioned absolutely at the card's top-right (14, 14).

### Controls row uniform height

All four interactive items in the controls row are sized by a single helper:

```python
def _make_ctrl_32(widget: QWidget) -> None:
    widget.setFixedHeight(32)
    widget.setStyleSheet(widget.styleSheet() + "border-radius: 6px;")
```

Applied to: enable button, chat button, keep-alive button, set selector. The KA progress bar is 8 px tall (intentionally a different element type — a track, not a control).

## Error handling

- If `_FullLayout.populate(shared_widgets)` is called before all four slots have widgets (race during init), it builds empty placeholder cells for missing slots. No crash.
- If a `set_layout_mode` swap fires during an in-flight portrait fetch, the fetch completes and lands on the same `ToonPortraitWidget` instance because widgets are shared.
- `resizeEvent` swallows exceptions in `_set_layout_mode` (logged to `self.logger` if available) so a layout bug never propagates into Qt's resize machinery.

## Testing

- **Unit**: a small test file `tests/test_layout_breakpoint.py` instantiates `MultiToonTool`, calls `resize(QSize(...))` at sizes spanning the deadband, and asserts `_layout_mode` transitions correctly. Mocks `_set_layout_mode` so we don't need a real layout swap during the test.
- **Visual smoke**: manual checklist in `RELEASE_NOTES.md` for the version that ships this:
  - Open at default size → Compact UI.
  - Maximize → Full UI swaps in.
  - Drag border between 1200 and 1360 px → no flicker.
  - Toggle theme → both layouts re-color cleanly.
  - With `disable_animations=true` → instant swap, no fade.
  - Each tab at maximize: Multitoon = Full; others = clamped-and-centered.
- **Theme**: open the existing settings tab at maximize in both themes; confirm color tokens look correct against the new palette (no leftover Catppuccin lavender).

## Implementation considerations

- `MultitoonTab` is the largest tab file (~1500 lines). The layout split lets us extract `_CompactLayout` and `_FullLayout` into either nested classes within `multitoon_tab.py` or — preferred — separate files `tabs/multitoon/_compact.py` and `tabs/multitoon/_full.py`. Same module, easier to hold in context. The shared-widget builder stays in `multitoon_tab.py`.
- The Launch tab pattern of `setMaximumWidth + Qt.AlignHCenter` is the primitive used for both Compact's clamp and the other tabs' clamps. Worth extracting `utils/layout.py:clamp_centered(widget, max_width)` to make this single-line at every call site.
- `apply_theme(c, is_dark)` already exists on most widgets. The new tokens (`status_dot_active`, `game_pill_ttr`, etc.) are additive — existing widgets ignore them.
- The 720 px Compact clamp value is calibrated to the default 560×650 window plus headroom. If the default window grows in the future, revisit.

## Open questions

None at spec time. Any open questions surface during implementation and get logged into the plan.
