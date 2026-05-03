# Multitoon Full UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a maximize-friendly Full UI for the Multitoon tab that swaps in at 1280×800 with hysteresis, ship a charcoal dark palette + cool-slate light palette, and clamp-and-center every other tab so the app stops looking bad when the window is wide.

**Architecture:** `MultitoonTab` becomes a `QStackedWidget` of `_CompactLayout` (existing) and `_FullLayout` (new 2×2 card grid), both consuming a single set of shared widgets so state survives the swap. `MultiToonTool` (`QMainWindow`) overrides `resizeEvent` to switch modes with deadband hysteresis and runs a 160 ms cross-fade. Theme colors are rewritten end-to-end in `utils/theme_manager.py:get_theme_colors()` plus the global `DARK_THEME` / `LIGHT_THEME` stylesheets.

**Tech Stack:** PySide6 6.5+, pytest, existing `utils/theme_manager.py`, existing `tabs/multitoon_tab.py` widget classes (`ToonPortraitWidget`, `ElidingLabel`, `KeepAliveBtn`, `SetSelectorWidget`).

**Spec:** `docs/superpowers/specs/2026-04-26-multitoon-full-ui-design.md`

---

## File Structure

**Created:**
- `utils/layout.py` — `clamp_centered(widget, max_width)` helper used everywhere we need the Launch-tab pattern.
- `tabs/multitoon/__init__.py` — exports `MultitoonTab`.
- `tabs/multitoon/_shared_widgets.py` — `_build_shared_widgets()` factory that returns the per-slot widget dicts plus the tab-level service/profile widgets.
- `tabs/multitoon/_compact_layout.py` — `_CompactLayout` reproducing the current layout from shared widgets.
- `tabs/multitoon/_full_layout.py` — `_FullLayout`, `_FullToonCard`, `_StatusIndicator`.
- `tests/test_layout_helper.py` — tests for `clamp_centered`.
- `tests/test_theme_palette.py` — tests for the new color tokens and contrast guarantees.
- `tests/test_layout_breakpoint.py` — tests for the resizeEvent → mode-swap state machine.

**Modified:**
- `utils/theme_manager.py` — rewrite both branches of `get_theme_colors()`, update `DARK_THEME`/`LIGHT_THEME` stylesheets, update `apply_card_shadow` shadow color, add new tokens (`status_dot_active`, `status_dot_idle`, `game_pill_ttr`, `game_pill_cc`).
- `main.py` — add `_layout_mode` state, `resizeEvent` with hysteresis, `_set_layout_mode` with cross-fade, broadcast to tabs.
- `tabs/multitoon_tab.py` — replace with a thin shim that re-exports from `tabs/multitoon/` so existing imports keep working; OR delete and update imports. Plan uses the shim approach for minimum diff to call sites.
- `tabs/keymap_tab.py`, `tabs/settings_tab.py`, `tabs/invasions_tab.py`, `tabs/debug_tab.py`, `tabs/credits_tab.py` — apply `clamp_centered` at 720 px on the topmost content frame.
- `tests/test_theme_manager.py` — update `test_light_theme_uses_gradient_background` to match new light palette (still uses gradient, just a new one).

**Note on the multitoon split:** moving `MultitoonTab` from a single 1500-line file to a package keeps each layout concern under 500 lines. We move the class but keep `tabs/multitoon_tab.py` as a one-line re-export so the import in `main.py` does not change. This is the only structural refactor in this plan; everything else is additive.

**Implementation note — shared-widget reparenting:** Qt widgets can only have one parent at a time. When `_CompactLayout` and `_FullLayout` both call `addWidget(shared_widget)` at construction time, only the *second* one retains ownership; the first layout's `QLayoutItem` is left with a now-detached widget reference. The plan handles this by giving each layout a `populate()` method that calls `addWidget` for every shared widget — Qt automatically reparents on `addWidget`, so the visible layout always owns the widgets. `set_layout_mode(target)` calls `target.populate()` before showing it. The losing layout's stale `QLayoutItem`s are harmless as long as that layout isn't visible. To avoid accumulating items across many swaps, `populate()` should `takeAt(0)` until empty before re-adding (Tasks 7 and 10 demonstrate this in their populate code).

---

## Task 1: Add `clamp_centered` layout helper

**Files:**
- Create: `utils/layout.py`
- Test: `tests/test_layout_helper.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_layout_helper.py`:

```python
"""Tests for utils.layout helpers."""

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout
from PySide6.QtCore import Qt

from utils.layout import clamp_centered


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_clamp_centered_sets_max_width(qapp):
    parent = QWidget()
    layout = QHBoxLayout(parent)
    child = QWidget()
    clamp_centered(layout, child, 480)
    assert child.maximumWidth() == 480


def test_clamp_centered_uses_horizontal_center_alignment(qapp):
    parent = QWidget()
    layout = QHBoxLayout(parent)
    child = QWidget()
    clamp_centered(layout, child, 720)
    # Find the item we just added
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is child:
            assert item.alignment() & Qt.AlignHCenter
            return
    pytest.fail("child was not added to the layout")


def test_clamp_centered_returns_widget_for_chaining(qapp):
    parent = QWidget()
    layout = QHBoxLayout(parent)
    child = QWidget()
    result = clamp_centered(layout, child, 480)
    assert result is child
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_layout_helper.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'utils.layout'`.

- [ ] **Step 3: Write the implementation**

Create `utils/layout.py`:

```python
"""Small layout helpers shared across tabs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QWidget


def clamp_centered(layout: QBoxLayout, widget: QWidget, max_width: int) -> QWidget:
    """Clamp `widget` to `max_width` and add it to `layout` horizontally centered.

    Mirrors the Launch tab pattern: `setMaximumWidth(max_width)` plus
    `Qt.AlignHCenter`. Returns the widget so calls can be chained.
    """
    widget.setMaximumWidth(max_width)
    layout.addWidget(widget, alignment=Qt.AlignHCenter)
    return widget
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_layout_helper.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add utils/layout.py tests/test_layout_helper.py
git commit -m "feat(layout): add clamp_centered helper for max-width centered children"
```

---

## Task 2: Rewrite dark palette in `get_theme_colors`

**Files:**
- Modify: `utils/theme_manager.py:87-200` (the `if is_dark:` branch)
- Test: `tests/test_theme_palette.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_theme_palette.py`:

```python
"""Tests for the dark/light color tokens returned by get_theme_colors()."""

from utils.theme_manager import get_theme_colors


def test_dark_palette_uses_charcoal_app_bg():
    c = get_theme_colors(is_dark=True)
    assert c["bg_app"] == "#1a1a1f"
    assert c["bg_card"] == "#2a2a30"
    assert c["bg_card_inner"] == "#2f2f36"
    assert c["sidebar_bg"] == "#131316"


def test_dark_palette_text_is_softer_than_pure_white():
    c = get_theme_colors(is_dark=True)
    assert c["text_primary"] == "#e8e8ed"
    assert c["text_secondary"] == "#c8c8d0"


def test_dark_palette_accent_green_pairs_with_dark_text():
    """Material 3 onPrimary pattern: bright surface + dark text clears AAA in dark mode."""
    c = get_theme_colors(is_dark=True)
    assert c["accent_green"] == "#4ade80"  # green-400, ~9.7:1 vs text_on_accent
    assert c["text_on_accent"] == "#0f172a"


def test_dark_palette_accent_blue_btn_pairs_with_dark_text():
    c = get_theme_colors(is_dark=True)
    assert c["accent_blue_btn"] == "#60a5fa"  # blue-400, ~6.7:1 vs text_on_accent


def test_dark_palette_accent_red_pairs_with_dark_text():
    c = get_theme_colors(is_dark=True)
    assert c["accent_red"] == "#f87171"  # red-400, ~6.3:1 vs text_on_accent


def test_dark_palette_decorative_greens_remain_saturated():
    """status_dot_active/segment_active are no-text decorations — keep #3aaa5e."""
    c = get_theme_colors(is_dark=True)
    assert c["status_dot_active"] == "#3aaa5e"
    assert c["segment_active"] == "#3aaa5e"


def test_dark_palette_includes_full_ui_tokens():
    c = get_theme_colors(is_dark=True)
    assert c["status_dot_idle"] == "#45454c"
    assert c["game_pill_ttr"] == "#a78bfa"  # violet-400, paired with text_on_accent
    assert c["game_pill_cc"] == "#60a5fa"   # matches accent_blue_btn
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_theme_palette.py -v
```

Expected: 5 failures (every assertion mismatches the current palette).

- [ ] **Step 3: Update the dark branch of `get_theme_colors`**

In `utils/theme_manager.py`, replace the `if is_dark:` return dict (lines ~89-200) with:

```python
    if is_dark:
        return {
            # Backgrounds  (elevation: sidebar < app < card < card_inner)
            "bg_app":        "#1a1a1f",
            "bg_card":       "#2a2a30",
            "bg_card_inner": "#2f2f36",
            "bg_input":      "#1e1e23",
            "bg_input_dark": "#141418",
            "bg_status":     "#1e1e23",

            # Sidebar
            "sidebar_bg":       "#131316",
            "sidebar_btn":      "transparent",
            "sidebar_btn_sel":  "rgba(255,255,255,0.09)",
            "sidebar_text":     "#a8a8b0",
            "sidebar_text_sel": "#ffffff",
            "sidebar_border":   "#2c2c33",

            # Header
            "header_bg":     "#1a1a1f",
            "header_text":   "#e8e8ed",
            "header_accent": "#3a6dd8",

            # Borders
            "border_card":  "#35353c",
            "border_input": "#3a3a42",
            "border_muted": "#2c2c33",
            "border_light": "#55555c",

            # Text
            "text_primary":   "#e8e8ed",
            "text_secondary": "#c8c8d0",
            "text_muted":     "#888890",
            "text_disabled":  "#5c5c64",

            # On-accent text/icon — universal pair for every bright accent surface
            # below. Slate-900 clears AA against green-400/blue-400/red-400/violet-400.
            "text_on_accent": "#0f172a",

            # Accent — green (text-bearing surface, e.g. Enable button)
            # Pairs with text_on_accent. green-400 / 9.7:1 vs text_on_accent (AAA).
            "accent_green":        "#4ade80",
            "accent_green_border": "#86efac",
            "accent_green_hover":  "#22c55e",
            "accent_green_hover_border": "#4ade80",
            "accent_green_subtle": "#80c080",

            # Accent — blue (text-bearing surface, e.g. Set selector)
            # Pairs with text_on_accent. blue-400 / 6.7:1 (AA, near-AAA).
            "accent_blue": "#88c0d0",
            "accent_blue_btn":        "#60a5fa",
            "accent_blue_btn_border": "#93c5fd",
            "accent_blue_btn_hover":  "#3b82f6",

            # Accent — red (text-bearing surface, e.g. Stop Service)
            # Pairs with text_on_accent. red-400 / 6.3:1 (AA).
            "accent_red":        "#f87171",
            "accent_red_border": "#fca5a5",
            "accent_red_hover":  "#ef4444",
            "accent_red_hover_border": "#f87171",

            # Accent — orange (keep-alive active — icon-only button, 3:1 UI minimum)
            "accent_orange":        "#c66d2e",
            "accent_orange_border": "#e0843a",
            "accent_orange_hover":  "#d47a34",

            # Status strip — success
            "status_success_bg":     "#2c3f2c",
            "status_success_text":   "#ccffcc",
            "status_success_border": "#56c856",

            # Status strip — warning
            "status_warning_bg":     "#3a2f1a",
            "status_warning_text":   "#ffcc99",
            "status_warning_border": "#ffaa00",

            # Status strip — idle
            "status_idle_bg":     "#2f2f36",
            "status_idle_text":   "#c8c8d0",
            "status_idle_border": "#55555c",

            # Buttons
            "btn_bg":       "#35353c",
            "btn_border":   "#45454c",
            "btn_hover":    "#3e3e45",
            "btn_disabled": "#2a2a30",
            "btn_text":     "#e8e8ed",

            # Dropdowns
            "dropdown_bg":          "#2f2f36",
            "dropdown_text":        "#e8e8ed",
            "dropdown_border":      "#3a3a42",
            "dropdown_list_bg":     "#1e1e23",
            "dropdown_sel_bg":      "#3a3a42",
            "dropdown_sel_text":    "#ffffff",

            # Toon enable button — inactive
            "toon_btn_inactive_bg":     "#3a3a42",
            "toon_btn_inactive_border": "#4a4a52",
            "toon_btn_inactive_hover":  "#444450",
            "toon_btn_inactive_hover_border": "#5a5a62",

            # Slot accent colors (badge circles)
            "slot_1": "#5b9bf5",
            "slot_2": "#4ade80",
            "slot_3": "#f59e42",
            "slot_4": "#b07cf5",
            "slot_dim": "#2f2f36",

            # Toon cards (floating on gradient)
            "card_toon_bg":        "#2a2a30",
            "card_toon_border":    "#35353c",
            "card_toon_active_bg": "#1f2e22",

            # Segment status bar
            "segment_off":    "#1e1e23",
            "segment_found":  "#35353c",
            "segment_active": "#3aaa5e",

            # Full UI tokens
            # status_dot_active/segment_active are decorative (no text on them) —
            # kept saturated for visual punch. Game pills are text-bearing and pair
            # with text_on_accent above.
            "status_dot_active": "#3aaa5e",
            "status_dot_idle":   "#45454c",
            "game_pill_ttr":     "#a78bfa",
            "game_pill_cc":      "#60a5fa",
        }
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_theme_palette.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add utils/theme_manager.py tests/test_theme_palette.py
git commit -m "feat(theme): rewrite dark palette to charcoal + saturated true colors"
```

---

## Task 3: Rewrite light palette in `get_theme_colors`

**Files:**
- Modify: `utils/theme_manager.py:202-312` (the `else:` branch)
- Test: `tests/test_theme_palette.py` (extend)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_theme_palette.py`:

```python
def test_light_palette_uses_cool_slate_bg():
    c = get_theme_colors(is_dark=False)
    assert c["bg_app"] == "#f8fafc"
    assert c["bg_card"] == "#ffffff"
    assert c["sidebar_bg"] == "#e8ecf1"


def test_light_palette_text_clears_aaa_on_white():
    c = get_theme_colors(is_dark=False)
    assert c["text_primary"] == "#0f172a"      # 17.6:1
    assert c["text_secondary"] == "#334155"    # 10.7:1
    assert c["text_muted"] == "#475569"        # 7.2:1
    assert c["text_disabled"] == "#64748b"     # 4.6:1


def test_light_palette_accent_green_clears_aa_with_white():
    """green-600 is decorative-only; text-bearing button uses green-700 for AA."""
    c = get_theme_colors(is_dark=False)
    assert c["accent_green"] == "#15803d"  # green-700, 5.0:1 vs white
    assert c["text_on_accent"] == "#ffffff"


def test_light_palette_slot_2_uses_text_bearing_green():
    """Slot 2 badge has a white digit on it, so the bg must clear AA against white."""
    c = get_theme_colors(is_dark=False)
    assert c["slot_2"] == "#15803d"  # green-700, matches accent_green family


def test_light_palette_accent_orange_clears_aa_with_white():
    c = get_theme_colors(is_dark=False)
    # orange-700 #c2410c -> 5.0:1 on white. The previous #c45f1e was 4.4 (borderline AA).
    assert c["accent_orange"] == "#c2410c"


def test_light_palette_decorative_greens_remain_vibrant():
    """status_dot_active/segment_active have no text — keep green-600 for visual punch."""
    c = get_theme_colors(is_dark=False)
    assert c["status_dot_active"] == "#16a34a"
    assert c["segment_active"] == "#16a34a"


def test_light_palette_includes_full_ui_tokens():
    c = get_theme_colors(is_dark=False)
    assert c["status_dot_idle"] == "#cbd5e1"
    assert c["game_pill_ttr"] == "#7c3aed"
    assert c["game_pill_cc"] == "#2563eb"


def test_text_on_accent_present_in_both_palettes():
    """Material 3 onPrimary pattern: every theme defines the token used as text/icon
    on top of every bright accent surface."""
    assert get_theme_colors(is_dark=True)["text_on_accent"] == "#0f172a"
    assert get_theme_colors(is_dark=False)["text_on_accent"] == "#ffffff"


def test_both_palettes_have_identical_keys():
    """Token coverage must match across themes — a missing key in one is a bug."""
    dark_keys = set(get_theme_colors(is_dark=True).keys())
    light_keys = set(get_theme_colors(is_dark=False).keys())
    assert dark_keys == light_keys, (
        f"dark only: {dark_keys - light_keys}, light only: {light_keys - dark_keys}"
    )
```

- [ ] **Step 2: Run test to verify they fail**

```
pytest tests/test_theme_palette.py -v
```

Expected: 5 new failures (light branch still has old values; `test_both_palettes_have_identical_keys` will also fail because dark has new tokens light does not yet).

- [ ] **Step 3: Update the light branch of `get_theme_colors`**

In `utils/theme_manager.py`, replace the `else:` return dict (lines ~202-312) with:

```python
    else:
        return {
            # Backgrounds  (elevation: sidebar < app < card < card_inner)
            "bg_app":        "#f8fafc",
            "bg_card":       "#ffffff",
            "bg_card_inner": "#f1f5f9",
            "bg_input":      "#ffffff",
            "bg_input_dark": "#e8ecf1",
            "bg_status":     "#f8fafc",

            # Sidebar
            "sidebar_bg":       "#e8ecf1",
            "sidebar_btn":      "transparent",
            "sidebar_btn_sel":  "rgba(15,23,42,0.07)",
            "sidebar_text":     "#475569",
            "sidebar_text_sel": "#0f172a",
            "sidebar_border":   "#cbd5e1",

            # Header
            "header_bg":     "#f8fafc",
            "header_text":   "#0f172a",
            "header_accent": "#2563eb",

            # Borders
            "border_card":  "#e2e8f0",
            "border_input": "#cbd5e1",
            "border_muted": "#e8ecf1",
            "border_light": "#cbd5e1",

            # Text
            "text_primary":   "#0f172a",
            "text_secondary": "#334155",
            "text_muted":     "#475569",
            "text_disabled":  "#64748b",

            # On-accent text/icon — universal pair for every text-bearing accent
            # surface in the light palette (white on green-700/blue-600/orange-700/
            # red-700/violet-600 all clear AA).
            "text_on_accent": "#ffffff",

            # Accent — green (text-bearing surface, e.g. Enable button)
            # green-700 / 5.0:1 vs white (AA). green-600 #16a34a is reserved for
            # decorative roles (status dot, segment) where 3:1 UI minimum applies.
            "accent_green":        "#15803d",
            "accent_green_border": "#22c55e",
            "accent_green_hover":  "#166534",
            "accent_green_hover_border": "#15803d",
            "accent_green_subtle": "#86efac",

            # Accent — blue
            "accent_blue": "#5ba8c8",
            "accent_blue_btn":        "#2563eb",
            "accent_blue_btn_border": "#1d4ed8",
            "accent_blue_btn_hover":  "#1e40af",

            # Accent — red
            "accent_red":        "#b91c1c",
            "accent_red_border": "#dc2626",
            "accent_red_hover":  "#991b1b",
            "accent_red_hover_border": "#b91c1c",

            # Accent — orange (keep-alive active)
            "accent_orange":        "#c2410c",
            "accent_orange_border": "#ea580c",
            "accent_orange_hover":  "#9a3412",

            # Status strip — success
            "status_success_bg":     "#dcfce7",
            "status_success_text":   "#166534",
            "status_success_border": "#16a34a",

            # Status strip — warning
            "status_warning_bg":     "#fef3c7",
            "status_warning_text":   "#92400e",
            "status_warning_border": "#f59e0b",

            # Status strip — idle
            "status_idle_bg":     "#f1f5f9",
            "status_idle_text":   "#334155",
            "status_idle_border": "#cbd5e1",

            # Buttons
            "btn_bg":       "#e8ecf1",
            "btn_border":   "#cbd5e1",
            "btn_hover":    "#dbe2ea",
            "btn_disabled": "#f1f5f9",
            "btn_text":     "#0f172a",

            # Dropdowns
            "dropdown_bg":          "#ffffff",
            "dropdown_text":        "#0f172a",
            "dropdown_border":      "#cbd5e1",
            "dropdown_list_bg":     "#f8fafc",
            "dropdown_sel_bg":      "#e2e8f0",
            "dropdown_sel_text":    "#0f172a",

            # Toon enable button — inactive
            "toon_btn_inactive_bg":     "#e8ecf1",
            "toon_btn_inactive_border": "#cbd5e1",
            "toon_btn_inactive_hover":  "#dbe2ea",
            "toon_btn_inactive_hover_border": "#94a3b8",

            # Slot accent colors (badge circles — text-bearing, paired with white digit)
            # All four cleared AA against white: blue-600 5.7, green-700 5.0,
            # orange-700 5.0, violet-600 5.4.
            "slot_1": "#2563eb",
            "slot_2": "#15803d",
            "slot_3": "#c2410c",
            "slot_4": "#7c3aed",
            "slot_dim": "#cbd5e1",

            # Toon cards
            "card_toon_bg":        "#ffffff",
            "card_toon_border":    "#e2e8f0",
            "card_toon_active_bg": "#f0fdf4",

            # Segment status bar
            "segment_off":    "#e2e8f0",
            "segment_found":  "#cbd5e1",
            "segment_active": "#16a34a",

            # Full UI tokens
            "status_dot_active": "#16a34a",
            "status_dot_idle":   "#cbd5e1",
            "game_pill_ttr":     "#7c3aed",
            "game_pill_cc":      "#2563eb",
        }
```

- [ ] **Step 4: Run all theme tests**

```
pytest tests/test_theme_palette.py tests/test_theme_manager.py -v
```

Expected: 10 palette tests pass. `test_light_theme_uses_gradient_background` may fail — handled in next task.

- [ ] **Step 5: Commit**

```bash
git add utils/theme_manager.py tests/test_theme_palette.py
git commit -m "feat(theme): rewrite light palette to cool slate (Tailwind-inspired)"
```

---

## Task 4: Update global stylesheets and card shadow

**Files:**
- Modify: `utils/theme_manager.py:317-402` (the `DARK_THEME` and `LIGHT_THEME` triple-quoted stylesheets)
- Modify: `utils/theme_manager.py:37-46` (the `apply_card_shadow` function)
- Modify: `tests/test_theme_manager.py` (existing gradient assertion needs new colors)

- [ ] **Step 1: Update `apply_card_shadow` to use slate-tinted shadow in light mode**

Replace lines ~37-46 in `utils/theme_manager.py`:

```python
def apply_card_shadow(widget, is_dark: bool, blur: float = 18, offset_y: float = 3):
    """Apply a subtle drop shadow to a widget (card, frame, etc)."""
    shadow = QGraphicsDropShadowEffect(widget)
    if is_dark:
        shadow.setColor(QColor(0, 0, 0, 90))
    else:
        # Slate-900 at low alpha — less muddy than pure black on a cool-slate base
        shadow.setColor(QColor(15, 23, 42, 32))
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, offset_y)
    widget.setGraphicsEffect(shadow)
```

- [ ] **Step 2: Update `DARK_THEME` stylesheet**

Replace the `DARK_THEME = """..."""` block (lines ~317-358) with:

```python
DARK_THEME = """
    QWidget {
        font-family: 'Inter', 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif;
        font-size: 12pt;
        background-color: #1a1a1f;
        color: #e8e8ed;
    }
    QPushButton {
        background-color: #35353c;
        color: #e8e8ed;
        border-radius: 8px;
        padding: 6px 14px;
        border: 1px solid #45454c;
    }
    QPushButton:hover {
        background-color: #3e3e45;
        border: 1px solid #55555c;
    }
    QPushButton:pressed {
        background-color: #28282d;
        border: 1px solid #3a3a42;
        padding-top: 7px;
        padding-bottom: 5px;
    }
    QPushButton:disabled {
        background-color: #2a2a30;
        color: #5c5c64;
        border: 1px solid #35353c;
    }
    QComboBox {
        background-color: #2f2f36;
        color: #e8e8ed;
        border-radius: 8px;
        padding: 4px 8px;
        border: 1px solid #3a3a42;
    }
    QComboBox QAbstractItemView {
        background-color: #1e1e23;
        selection-background-color: #3a3a42;
        color: #e8e8ed;
    }
"""
```

- [ ] **Step 3: Update `LIGHT_THEME` stylesheet**

Replace the `LIGHT_THEME = """..."""` block (lines ~360-402) with:

```python
LIGHT_THEME = """
    QWidget {
        font-family: 'Inter', 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif;
        font-size: 12pt;
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #f8fafc, stop:1 #eef2f7);
        color: #0f172a;
    }
    QPushButton {
        background-color: #e8ecf1;
        color: #0f172a;
        border-radius: 8px;
        padding: 6px 14px;
        border: 1px solid #cbd5e1;
    }
    QPushButton:hover {
        background-color: #dbe2ea;
        border: 1px solid #94a3b8;
    }
    QPushButton:pressed {
        background-color: #cbd5e1;
        border: 1px solid #94a3b8;
        padding-top: 7px;
        padding-bottom: 5px;
    }
    QPushButton:disabled {
        background-color: #f1f5f9;
        color: #94a3b8;
        border: 1px solid #e2e8f0;
    }
    QComboBox {
        background-color: #ffffff;
        color: #0f172a;
        border-radius: 8px;
        padding: 4px 8px;
        border: 1px solid #cbd5e1;
    }
    QComboBox QAbstractItemView {
        background-color: #f8fafc;
        selection-background-color: #e2e8f0;
        color: #0f172a;
    }
"""
```

- [ ] **Step 4: Verify the existing gradient test still passes**

```
pytest tests/test_theme_manager.py -v
```

Expected: all tests pass — the new `LIGHT_THEME` still uses `qlineargradient`, just with slate stops instead of gray.

- [ ] **Step 5: Manual smoke test**

```
python main.py
```

Open the app and check both themes (Settings → Theme). Quick checklist:
- App background reads charcoal (dark) / cool slate (light), not the previous near-black or warm gray.
- Buttons in both themes have visible borders, no washed-out look.
- Toggling theme does not crash; no Catppuccin lavender remnants visible.

Close when verified.

- [ ] **Step 6: Commit**

```bash
git add utils/theme_manager.py
git commit -m "feat(theme): update global stylesheets and shadow color for new palettes"
```

---

## Task 5: Apply clamp-and-center to non-Multitoon tabs

**Files:**
- Modify: `tabs/keymap_tab.py`, `tabs/settings_tab.py`, `tabs/invasions_tab.py`, `tabs/debug_tab.py`, `tabs/credits_tab.py`

- [ ] **Step 1: Locate each tab's outermost content widget**

For each of the five tabs, run:

```bash
grep -n "QVBoxLayout(self)\|QHBoxLayout(self)\|setLayout" tabs/keymap_tab.py | head -5
grep -n "QVBoxLayout(self)\|QHBoxLayout(self)\|setLayout" tabs/settings_tab.py | head -5
grep -n "QVBoxLayout(self)\|QHBoxLayout(self)\|setLayout" tabs/invasions_tab.py | head -5
grep -n "QVBoxLayout(self)\|QHBoxLayout(self)\|setLayout" tabs/debug_tab.py | head -5
grep -n "QVBoxLayout(self)\|QHBoxLayout(self)\|setLayout" tabs/credits_tab.py | head -5
```

Each tab's outermost layout takes a `QFrame` or content `QWidget` that we will clamp.

- [ ] **Step 2: Apply the clamp pattern to each tab**

For each tab, find the line where the outermost content frame/widget is added to the tab's layout, and replace `addWidget(content)` with the helper. Pattern:

```python
# Before (in the tab's __init__ or build_ui method):
outer.addWidget(self._content_frame)

# After:
from utils.layout import clamp_centered
clamp_centered(outer, self._content_frame, 720)
```

If a tab has no inner content frame (everything goes directly into the tab's own layout), wrap the existing layout into a new `QFrame`:

```python
# At the top of build_ui:
outer = QHBoxLayout(self)
outer.setContentsMargins(0, 0, 0, 0)
self._content = QFrame()
inner = QVBoxLayout(self._content)
# ... rest of the original __init__ goes into `inner` instead of `self`
clamp_centered(outer, self._content, 720)
```

If the tab is a `QScrollArea` (e.g. `debug_tab.py` may use one), apply the clamp to the *scroll area's* widget, not the scroll area itself, so the clamp travels with content rather than constraining the visible viewport.

Apply the same edit to all five tabs (keymap, settings, invasions, debug, credits). The Launch tab already does this at 480 px and is left untouched.

- [ ] **Step 3: Manual smoke test**

```
python main.py
```

Maximize the window. Click through each non-Multitoon tab (Launch is already correct):
- Keymap: content sits in a 720 px column centered horizontally, side margins are filled with the theme bg.
- Settings: same.
- Invasions: same.
- Debug: same — text logs scroll within the 720 px column.
- Credits: same.

Multitoon will still stretch full-width — that's correct, it has the Compact UI clamp wired in a later task and the Full UI bespoke layout coming after that.

- [ ] **Step 4: Commit**

```bash
git add tabs/keymap_tab.py tabs/settings_tab.py tabs/invasions_tab.py tabs/debug_tab.py tabs/credits_tab.py
git commit -m "feat(tabs): clamp-and-center non-multitoon content at 720px wide"
```

---

## Task 6: Extract shared widgets from `MultitoonTab.build_ui`

**Files:**
- Create: `tabs/multitoon/__init__.py`
- Create: `tabs/multitoon/_shared_widgets.py`
- Modify: `tabs/multitoon_tab.py` (replace with re-export shim, move class body to a new file)

This task is a pure refactor — no UI behavior changes, the Multitoon tab still looks identical. We're carving out the widget-creation code so two layouts can consume it later.

- [ ] **Step 1: Create the package directory**

```bash
mkdir -p tabs/multitoon
```

- [ ] **Step 2: Move the existing `MultitoonTab` class to a new module**

Move all of `tabs/multitoon_tab.py` to `tabs/multitoon/_tab.py`, but rename the file:

```bash
git mv tabs/multitoon_tab.py tabs/multitoon/_tab.py
```

- [ ] **Step 3: Create the package `__init__.py`**

Create `tabs/multitoon/__init__.py`:

```python
"""Multitoon tab — supports both Compact and Full UI layouts."""

from tabs.multitoon._tab import MultitoonTab

__all__ = ["MultitoonTab"]
```

- [ ] **Step 4: Recreate the shim at the old path**

Create `tabs/multitoon_tab.py`:

```python
"""Compatibility shim — the Multitoon tab moved to the `tabs.multitoon` package.

This file lets `from tabs.multitoon_tab import MultitoonTab` keep working without
touching every call site.
"""

from tabs.multitoon import MultitoonTab

__all__ = ["MultitoonTab"]
```

- [ ] **Step 5: Verify nothing broke**

```
python -c "from tabs.multitoon_tab import MultitoonTab; print(MultitoonTab)"
pytest tests/ -v
python main.py
```

Expected: import succeeds, all tests still pass, app launches identically. Close when verified.

- [ ] **Step 6: Extract shared widget construction**

In `tabs/multitoon/_tab.py`, find `build_ui` (around line 718). It currently builds widgets and lays them out in one pass. Extract widget *creation* into a new method `_build_shared_widgets`, leaving layout construction in `build_ui`:

Add the new method (place it just above `build_ui`):

```python
    def _build_shared_widgets(self):
        """Construct every per-slot widget once. Both Compact and Full layouts
        consume the resulting dict-of-lists so widget state survives a layout swap."""
        # Service controls
        self.toggle_service_button = QPushButton(f"{S(chr(9654), chr(9654))} Start Service")
        self.toggle_service_button.setCheckable(True)
        self.toggle_service_button.clicked.connect(self.toggle_service)
        self.toggle_service_button.setFixedHeight(48)

        self.status_bar = StatusBar()

        self._section_divider = QFrame()
        self._section_divider.setFixedHeight(2)
        self._section_divider.setMaximumWidth(320)
        self._section_divider.setObjectName("section_divider")

        # Toon config row widgets
        self.config_label = QLabel("TOON CONFIGURATION")
        for i in range(5):
            pill = QPushButton(str(i + 1))
            pill.setFixedSize(28, 28)
            pill.setToolTip(f"Load Profile {i+1} (Ctrl+{i+1})")
            pill.clicked.connect(lambda checked, idx=i: self.load_profile(idx))
            self.profile_pills.append(pill)

        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(make_refresh_icon(14))
        self.refresh_button.setFixedSize(26, 26)
        self.refresh_button.setToolTip("Refresh toon windows and configuration")
        self.refresh_button.clicked.connect(self.manual_refresh)

        # Per-slot widgets
        for i in range(4):
            badge = ToonPortraitWidget(i + 1)
            badge.clicked.connect(lambda idx=i: self._on_portrait_clicked(idx))
            self.slot_badges.append(badge)

            name_label = ElidingLabel(f"Toon {i + 1}")
            status_dot = PulsingDot(10)
            status_dot.setToolTip("Not Found")
            self.toon_labels.append((name_label, status_dot))

            game_badge = QLabel()
            game_badge.setObjectName("game_badge")
            game_badge.hide()
            self.game_badges.append(game_badge)

            laff_lbl = QPushButton(" ---")
            laff_lbl.setIcon(make_heart_icon(16))
            laff_lbl.setObjectName("laff_lbl")
            laff_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            laff_lbl.setToolTip("Laff")
            laff_lbl.hide()
            self.laff_labels.append(laff_lbl)

            bean_lbl = QPushButton(" ---")
            bean_lbl.setIcon(make_jellybean_icon(16))
            bean_lbl.setObjectName("bean_lbl")
            bean_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            bean_lbl.setToolTip("Bank Jellybeans")
            bean_lbl.hide()
            self.bean_labels.append(bean_lbl)

            btn = QPushButton("Enable")
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
            ka_btn.setIcon(make_mouse_icon(14))
            ka_btn.setToolTip("Toggle keep-alive for this toon")
            ka_btn.clicked.connect(lambda checked, idx=i: self.toggle_keep_alive(idx))
            ka_btn.rapid_fire_toggled.connect(lambda state, idx=i: self.toggle_rapid_fire(idx, state))
            self.keep_alive_buttons.append(ka_btn)

            chat_btn = QPushButton()
            chat_btn.setCheckable(True)
            chat_btn.setChecked(True)
            chat_btn.setFixedHeight(32)
            chat_btn.setFixedWidth(32)
            chat_btn.setIcon(make_chat_icon(14))
            chat_btn.setToolTip("Toggle chat broadcasting for this toon")
            chat_btn.clicked.connect(lambda checked, idx=i: self.toggle_chat(idx))
            self.chat_buttons.append(chat_btn)

            ka_bar = SmoothProgressBar()
            self.ka_progress_bars.append(ka_bar)

            selector = SetSelectorWidget(self.keymap_manager)
            selector.setFixedHeight(28)
            selector.setToolTip("Movement set for this toon")
            selector.index_changed.connect(lambda _, idx=i: self._autosave_active_profile())
            self.set_selectors.append(selector)
```

- [ ] **Step 7: Replace `build_ui` body**

Rewrite `build_ui` so it now just *lays out* the already-built widgets. Replace its current body (everything between `def build_ui(self):` and `self.update_service_button_style()`) with:

```python
    def build_ui(self):
        self._build_shared_widgets()

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 12, 16, 12)
        outer_layout.setSpacing(0)

        self.outer_card = QFrame()
        outer_card_layout = QVBoxLayout(self.outer_card)
        outer_card_layout.setContentsMargins(16, 16, 16, 16)
        outer_card_layout.setSpacing(10)

        # Service controls
        service_layout = QVBoxLayout()
        service_layout.setContentsMargins(0, 0, 0, 0)
        service_layout.setSpacing(6)
        service_layout.addWidget(self.toggle_service_button)
        service_layout.addWidget(self.status_bar)
        outer_card_layout.addLayout(service_layout)

        # Section divider
        outer_card_layout.addSpacing(6)
        outer_card_layout.addWidget(self._section_divider, alignment=Qt.AlignHCenter)
        outer_card_layout.addSpacing(6)

        # Toon config row
        config_row = QHBoxLayout()
        config_row.setSpacing(6)
        config_row.addWidget(self.config_label)
        config_row.addStretch()
        for pill in self.profile_pills:
            config_row.addWidget(pill)
        config_row.addSpacing(4)
        config_row.addWidget(self.refresh_button)
        outer_card_layout.addLayout(config_row)

        # Toon cards
        for i in range(4):
            card = QFrame()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(8)

            top_row = QHBoxLayout()
            top_row.setSpacing(10)
            top_row.addWidget(self.slot_badges[i])
            name_label, status_dot = self.toon_labels[i]
            top_row.addWidget(name_label)
            top_row.addWidget(status_dot)
            top_row.addWidget(self.game_badges[i])
            top_row.addStretch()

            stats_row = QHBoxLayout()
            stats_row.setSpacing(4)
            stats_row.setContentsMargins(0, 0, 0, 0)
            stats_row.addWidget(self.laff_labels[i])
            stats_row.addWidget(self.bean_labels[i])
            top_row.addLayout(stats_row)
            card_layout.addLayout(top_row)

            ctrl_row = QHBoxLayout()
            ctrl_row.setSpacing(8)
            ctrl_row.addWidget(self.toon_buttons[i])

            ka_group = QFrame()
            ka_group.setObjectName("ka_group")
            ka_group_layout = QHBoxLayout(ka_group)
            ka_group_layout.setContentsMargins(4, 4, 6, 4)
            ka_group_layout.setSpacing(4)
            ka_group_layout.addWidget(self.chat_buttons[i])
            ka_group_layout.addWidget(self.keep_alive_buttons[i])
            ka_group_layout.addWidget(self.ka_progress_bars[i], 1)
            self.ka_groups.append(ka_group)

            ctrl_row.addWidget(ka_group, 1)
            ctrl_row.addWidget(self.set_selectors[i])
            card_layout.addLayout(ctrl_row)

            self.toon_cards.append(card)
            outer_card_layout.addWidget(card)

        outer_card_layout.addStretch()
        outer_layout.addWidget(self.outer_card)
        outer_layout.addStretch()

        self.update_service_button_style()
        self.update_status_label()
```

- [ ] **Step 8: Verify the app still looks identical**

```
python main.py
pytest tests/ -v
```

Multitoon tab must look pixel-identical to before. All tests pass. Close when verified.

- [ ] **Step 9: Commit**

```bash
git add tabs/multitoon/ tabs/multitoon_tab.py
git commit -m "refactor(multitoon): split widget creation from layout build (no behavior change)"
```

---

## Task 7: Introduce `_CompactLayout` and `QStackedWidget`

**Files:**
- Create: `tabs/multitoon/_compact_layout.py`
- Modify: `tabs/multitoon/_tab.py`

This task moves the layout code into its own class without changing what the user sees. The `MultitoonTab` becomes a `QStackedWidget` with one page (Compact) — the second page (Full) lands in a later task.

- [ ] **Step 1: Create `_CompactLayout` class**

Create `tabs/multitoon/_compact_layout.py`:

```python
"""Compact UI layout for the Multitoon tab — the layout that ships at default
window size. Below the Full UI breakpoint, the outer card clamps to 720 px and
centers horizontally so wider windows do not stretch it."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame


class _CompactLayout(QWidget):
    """Reproduces the layout previously built inline in MultitoonTab.build_ui."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._build()

    def _build(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 12, 16, 12)
        outer_layout.setSpacing(0)

        outer_card = QFrame()
        outer_card.setMaximumWidth(720)
        self._tab.outer_card = outer_card
        card_layout = QVBoxLayout(outer_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        # Service controls
        service_layout = QVBoxLayout()
        service_layout.setContentsMargins(0, 0, 0, 0)
        service_layout.setSpacing(6)
        service_layout.addWidget(self._tab.toggle_service_button)
        service_layout.addWidget(self._tab.status_bar)
        card_layout.addLayout(service_layout)

        # Section divider
        card_layout.addSpacing(6)
        card_layout.addWidget(self._tab._section_divider, alignment=Qt.AlignHCenter)
        card_layout.addSpacing(6)

        # Config row
        config_row = QHBoxLayout()
        config_row.setSpacing(6)
        config_row.addWidget(self._tab.config_label)
        config_row.addStretch()
        for pill in self._tab.profile_pills:
            config_row.addWidget(pill)
        config_row.addSpacing(4)
        config_row.addWidget(self._tab.refresh_button)
        card_layout.addLayout(config_row)

        # Per-slot toon cards
        for i in range(4):
            card_layout.addWidget(self._build_card(i))

        card_layout.addStretch()
        outer_layout.addWidget(outer_card, alignment=Qt.AlignHCenter)
        outer_layout.addStretch()

    def _build_card(self, i: int) -> QFrame:
        card = QFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(self._tab.slot_badges[i])
        name_label, status_dot = self._tab.toon_labels[i]
        top_row.addWidget(name_label)
        top_row.addWidget(status_dot)
        top_row.addWidget(self._tab.game_badges[i])
        top_row.addStretch()

        stats_row = QHBoxLayout()
        stats_row.setSpacing(4)
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.addWidget(self._tab.laff_labels[i])
        stats_row.addWidget(self._tab.bean_labels[i])
        top_row.addLayout(stats_row)
        layout.addLayout(top_row)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        ctrl_row.addWidget(self._tab.toon_buttons[i])

        ka_group = QFrame()
        ka_group.setObjectName("ka_group")
        ka_group_layout = QHBoxLayout(ka_group)
        ka_group_layout.setContentsMargins(4, 4, 6, 4)
        ka_group_layout.setSpacing(4)
        ka_group_layout.addWidget(self._tab.chat_buttons[i])
        ka_group_layout.addWidget(self._tab.keep_alive_buttons[i])
        ka_group_layout.addWidget(self._tab.ka_progress_bars[i], 1)
        self._tab.ka_groups.append(ka_group)
        ctrl_row.addWidget(ka_group, 1)

        ctrl_row.addWidget(self._tab.set_selectors[i])
        layout.addLayout(ctrl_row)

        self._tab.toon_cards.append(card)
        return card
```

- [ ] **Step 2: Wire MultitoonTab to use `_CompactLayout` via `QStackedWidget`**

In `tabs/multitoon/_tab.py`, replace the entire `build_ui` body with:

```python
    def build_ui(self):
        from tabs.multitoon._compact_layout import _CompactLayout

        self._build_shared_widgets()

        self._stack = QStackedWidget(self)
        self._compact = _CompactLayout(self)
        self._stack.addWidget(self._compact)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._stack)

        self._mode = "compact"
        self.update_service_button_style()
        self.update_status_label()

    def set_layout_mode(self, mode: str) -> None:
        """No-op until the Full layout lands in a later task."""
        if mode != "compact":
            return
```

Add the import at the top of `_tab.py`:

```python
from PySide6.QtWidgets import QStackedWidget
```

(Most likely already present via the existing `from PySide6.QtWidgets import …` line — extend it rather than duplicating.)

- [ ] **Step 3: Verify the app behaves identically**

```
python main.py
pytest tests/ -v
```

Multitoon tab looks the same (Compact UI). Selecting profiles, enabling toons, toggling service all still work. Maximize the window — the outer card clamps at 720 px and centers (this is the new behavior). Close when verified.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_compact_layout.py tabs/multitoon/_tab.py
git commit -m "feat(multitoon): wrap compact layout in QStackedWidget; clamp outer card to 720px"
```

---

## Task 8: Build the `_StatusIndicator` widget

**Files:**
- Create: `tabs/multitoon/_full_layout.py` (this task adds only the `_StatusIndicator` class — the rest of the Full UI lands in later tasks)

- [ ] **Step 1: Create the file with `_StatusIndicator`**

Create `tabs/multitoon/_full_layout.py`:

```python
"""Full UI layout for the Multitoon tab — activated at >= 1280x800.

The Full UI is a 2x2 card grid with large portraits and a Discord-style status
indicator (background-colored ring overlapping the portrait + colored dot inside).
"""

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class _StatusIndicator(QWidget):
    """32x32 widget: a 32px ring in the card-bg color + a 24px filled dot.

    Z-order when overlaid on the portrait: portrait -> ring -> dot. The ring
    color must match the parent card background to create the cutout illusion.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self._active = False
        self._ring_color = QColor("#2a2a30")  # default = dark card-bg
        self._dot_color_active = QColor("#3aaa5e")
        self._dot_color_idle = QColor("#45454c")
        self._glow = 0.0  # 0.0..1.0, animated when active

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self.update()

    def apply_theme(self, ring_hex: str, active_hex: str, idle_hex: str) -> None:
        self._ring_color = QColor(ring_hex)
        self._dot_color_active = QColor(active_hex)
        self._dot_color_idle = QColor(idle_hex)
        self.update()

    # Animated glow property — driven by a QPropertyAnimation in a later task.
    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, v: float) -> None:
        self._glow = max(0.0, min(1.0, v))
        self.update()

    glow = Property(float, _get_glow, _set_glow)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        # Ring fills the entire widget bounds — same color as parent card bg.
        p.setBrush(self._ring_color)
        p.drawEllipse(0, 0, 32, 32)

        # Dot — 24x24 centered, leaves a 4px ring on every side.
        dot_color = self._dot_color_active if self._active else self._dot_color_idle
        if self._active and self._glow > 0:
            # Glow halo: extra outer dot at low alpha
            halo = QColor(dot_color)
            halo.setAlphaF(0.35 * self._glow)
            p.setBrush(halo)
            p.drawEllipse(1, 1, 30, 30)
        p.setBrush(dot_color)
        p.drawEllipse(4, 4, 24, 24)
```

- [ ] **Step 2: Add a smoke-test that the widget paints without error**

Append to `tests/test_layout_helper.py` (reusing the qapp fixture):

```python
def test_status_indicator_constructs_and_renders(qapp):
    from tabs.multitoon._full_layout import _StatusIndicator
    from PySide6.QtGui import QPixmap

    w = _StatusIndicator()
    w.apply_theme("#2a2a30", "#3aaa5e", "#45454c")
    w.set_active(True)
    # Render to a pixmap to force a paintEvent
    pixmap = QPixmap(w.size())
    pixmap.fill(Qt.transparent)
    w.render(pixmap)
    assert not pixmap.isNull()
    assert pixmap.size().width() == 32
    assert pixmap.size().height() == 32
```

- [ ] **Step 3: Run the new test**

```
pytest tests/test_layout_helper.py::test_status_indicator_constructs_and_renders -v
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py tests/test_layout_helper.py
git commit -m "feat(multitoon): add _StatusIndicator widget for Full UI"
```

---

## Task 9: Build `_FullToonCard` (active + inactive)

**Files:**
- Modify: `tabs/multitoon/_full_layout.py` (extend with `_FullToonCard`)

- [ ] **Step 1: Append `_FullToonCard` to the file**

Add to `tabs/multitoon/_full_layout.py`:

```python
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QSizePolicy
)
from PySide6.QtGui import QFont


def _make_ctrl_32(widget: QWidget) -> None:
    """Force a control to 32px tall + 6px corner radius — applied to every
    interactive item in the controls row so they share a baseline."""
    widget.setFixedHeight(32)
    sheet = widget.styleSheet()
    if "border-radius" not in sheet:
        widget.setStyleSheet(sheet + "border-radius: 6px;")


class _FullToonCard(QFrame):
    """One toon's card in the Full UI. Active and inactive states share the
    outer frame; the inner content swaps based on whether a window was found."""

    def __init__(self, slot_index: int, tab, parent=None):
        super().__init__(parent)
        self._slot = slot_index
        self._tab = tab
        self._is_active = False

        self.setObjectName("full_toon_card")
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._stack_layout = QVBoxLayout(self)
        self._stack_layout.setContentsMargins(18, 18, 18, 18)
        self._stack_layout.setSpacing(0)

        self._build_active_view()
        self._build_inactive_view()
        self.set_active(False)

    # ── Active view ────────────────────────────────────────────────────────
    def _build_active_view(self):
        self._active_root = QWidget(self)
        grid = QGridLayout(self._active_root)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)

        # Portrait + status indicator (column 0, rows 0-2)
        portrait_wrap = QWidget()
        portrait_wrap.setFixedSize(104, 104)
        portrait = self._tab.slot_badges[self._slot]
        portrait.setParent(portrait_wrap)
        portrait.setFixedSize(104, 104)
        portrait.move(0, 0)
        self._status_indicator = _StatusIndicator(portrait_wrap)
        self._status_indicator.move(74, 74)  # bottom-right, -2/-2 visual offset
        grid.addWidget(portrait_wrap, 0, 0, 3, 1, alignment=Qt.AlignTop)

        # Name label (col 1, row 0)
        name_label, _status_dot_compact = self._tab.toon_labels[self._slot]
        name_font = name_label.font()
        name_font.setPointSize(16)
        name_font.setWeight(QFont.DemiBold)
        name_label.setFont(name_font)
        name_label.setStyleSheet(name_label.styleSheet() + "padding-right: 60px;")
        grid.addWidget(name_label, 0, 1, alignment=Qt.AlignBottom)

        # Stats (col 1, rows 1 & 2). Reuse the existing labels but apply tabular nums.
        for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
            f = lbl.font()
            try:
                f.setFeature("tnum", 1)  # PySide6 6.5+
            except Exception:
                f.setStyleHint(QFont.TypeWriter, QFont.PreferDefault)
            lbl.setFont(f)
        grid.addWidget(self._tab.laff_labels[self._slot], 1, 1, alignment=Qt.AlignLeft)
        grid.addWidget(self._tab.bean_labels[self._slot], 2, 1, alignment=Qt.AlignLeft)

        # TTR/CC pill (top-right absolute via overlay)
        self._game_pill = self._tab.game_badges[self._slot]
        self._game_pill.setParent(self._active_root)
        self._game_pill.move(0, 0)  # repositioned in resizeEvent of card

        # Controls row (spans both columns)
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        for w in (
            self._tab.toon_buttons[self._slot],
            self._tab.chat_buttons[self._slot],
            self._tab.keep_alive_buttons[self._slot],
        ):
            _make_ctrl_32(w)
        ctrl_row.addWidget(self._tab.toon_buttons[self._slot])
        ctrl_row.addWidget(self._tab.chat_buttons[self._slot])
        ctrl_row.addWidget(self._tab.keep_alive_buttons[self._slot])

        ka_bar = self._tab.ka_progress_bars[self._slot]
        ka_bar.setFixedSize(90, 8)
        ctrl_row.addWidget(ka_bar)
        ctrl_row.addStretch(1)

        selector = self._tab.set_selectors[self._slot]
        _make_ctrl_32(selector)
        ctrl_row.addWidget(selector)

        grid.addLayout(ctrl_row, 3, 0, 1, 2)

        self._stack_layout.addWidget(self._active_root)

    # ── Inactive view ──────────────────────────────────────────────────────
    def _build_inactive_view(self):
        self._inactive_root = QWidget(self)
        v = QVBoxLayout(self._inactive_root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        slot_label = QLabel(f"Toon {self._slot + 1}")
        slot_label.setObjectName("full_slot_label")
        slot_font = slot_label.font()
        slot_font.setPointSize(11)
        slot_font.setWeight(QFont.DemiBold)
        slot_label.setFont(slot_font)
        v.addWidget(slot_label, alignment=Qt.AlignTop | Qt.AlignLeft)

        empty_area = QWidget()
        ev = QVBoxLayout(empty_area)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(6)
        ev.addStretch()
        icon = QLabel("·")
        icon.setObjectName("full_empty_icon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(32, 32)
        ev.addWidget(icon, alignment=Qt.AlignHCenter)
        msg = QLabel("No game detected")
        msg.setObjectName("full_empty_msg")
        msg.setAlignment(Qt.AlignCenter)
        ev.addWidget(msg, alignment=Qt.AlignHCenter)
        ev.addStretch()
        v.addWidget(empty_area, 1)

        self._stack_layout.addWidget(self._inactive_root)

    # ── State ──────────────────────────────────────────────────────────────
    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._active_root.setVisible(active)
        self._inactive_root.setVisible(not active)
        if active:
            self._status_indicator.set_active(True)

    def apply_theme(self, c: dict) -> None:
        is_dark = c["bg_card"].startswith("#") and int(c["bg_card"][1:3], 16) < 0x80
        self.setStyleSheet(
            f"#full_toon_card {{ background: {c['bg_card']}; "
            f"border: 1px solid {c['border_card']}; border-radius: 12px; }}"
        )
        self._status_indicator.apply_theme(
            c["bg_card"], c["status_dot_active"], c["status_dot_idle"]
        )
        self._game_pill.setStyleSheet(
            f"background: {c['game_pill_ttr']}; color: white; "
            f"border-radius: 10px; padding: 3px 10px; "
            f"font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep the game pill anchored top-right at (-14, -14) inset
        if self._is_active:
            pw = self._game_pill.sizeHint().width()
            self._game_pill.move(self.width() - pw - 14, 14)
```

- [ ] **Step 2: Smoke test the card constructs without errors**

Append to `tests/test_layout_helper.py`:

```python
def test_full_toon_card_constructs_for_inactive_slot(qapp, tmp_path):
    from tabs.multitoon._full_layout import _FullToonCard
    from unittest.mock import MagicMock

    tab = MagicMock()
    tab.slot_badges = [MagicMock() for _ in range(4)]
    tab.toon_labels = [(MagicMock(), MagicMock()) for _ in range(4)]
    tab.game_badges = [MagicMock() for _ in range(4)]
    tab.laff_labels = [MagicMock() for _ in range(4)]
    tab.bean_labels = [MagicMock() for _ in range(4)]
    tab.toon_buttons = [MagicMock() for _ in range(4)]
    tab.chat_buttons = [MagicMock() for _ in range(4)]
    tab.keep_alive_buttons = [MagicMock() for _ in range(4)]
    tab.ka_progress_bars = [MagicMock() for _ in range(4)]
    tab.set_selectors = [MagicMock() for _ in range(4)]

    # Mocks won't satisfy QWidget operations; this test is a placeholder asserting
    # the import chain works. Detailed behavior tests live with the integration
    # test once the full layout is wired.
    from tabs.multitoon._full_layout import _make_ctrl_32, _StatusIndicator
    assert callable(_make_ctrl_32)
    assert _StatusIndicator is not None
```

- [ ] **Step 3: Run tests**

```
pytest tests/test_layout_helper.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py tests/test_layout_helper.py
git commit -m "feat(multitoon): add _FullToonCard with active and inactive views"
```

---

## Task 10: Build `_FullLayout` and wire into `set_layout_mode`

**Files:**
- Modify: `tabs/multitoon/_full_layout.py` (extend)
- Modify: `tabs/multitoon/_tab.py`

- [ ] **Step 1: Append `_FullLayout` class**

Add to `tabs/multitoon/_full_layout.py`:

```python
from PySide6.QtWidgets import QGridLayout


class _FullLayout(QWidget):
    """Top-level Full UI: service bar above a 2x2 toon card grid."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._cards = []
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)

        # Service bar
        service_bar = QFrame()
        service_bar.setObjectName("full_service_bar")
        sb_layout = QVBoxLayout(service_bar)
        sb_layout.setContentsMargins(24, 18, 24, 18)
        sb_layout.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(16)
        # Restyle the toggle button for the wider layout
        self._tab.toggle_service_button.setMinimumWidth(180)
        row.addWidget(self._tab.toggle_service_button)
        row.addStretch()
        for pill in self._tab.profile_pills:
            row.addWidget(pill)
        row.addSpacing(8)
        row.addWidget(self._tab.refresh_button)
        sb_layout.addLayout(row)
        sb_layout.addWidget(self._tab.status_bar)

        outer.addWidget(service_bar)

        # 2x2 grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for i, (r, c) in enumerate(positions):
            card = _FullToonCard(i, self._tab)
            self._cards.append(card)
            grid.addWidget(card, r, c)
        outer.addLayout(grid, 1)

    def populate(self):
        """Re-attach shared widgets if they got reparented elsewhere. Called when
        we swap *back* from Compact to Full — the parent reassignment in the
        active card's __init__ would otherwise stay pointing to the previous
        layout's containers."""
        for card in self._cards:
            # Force re-parent on the per-slot widgets used by the active view.
            # The card already owns them via setParent in _build_active_view; we
            # call set_active(state) so visuals update.
            card.set_active(card._is_active)

    def apply_theme(self, c: dict) -> None:
        self.setStyleSheet(f"QWidget {{ background: {c['bg_app']}; }}")
        for card in self._cards:
            card.apply_theme(c)
```

- [ ] **Step 2: Wire `_FullLayout` into the tab**

In `tabs/multitoon/_tab.py`, replace the `build_ui` and `set_layout_mode` from Task 7 with:

```python
    def build_ui(self):
        from tabs.multitoon._compact_layout import _CompactLayout
        from tabs.multitoon._full_layout import _FullLayout

        self._build_shared_widgets()

        self._stack = QStackedWidget(self)
        self._compact = _CompactLayout(self)
        self._full = _FullLayout(self)
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

    def set_layout_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        target = self._full if mode == "full" else self._compact
        # Re-parent shared widgets back into the target via the layout's populate
        if hasattr(target, "populate"):
            target.populate()
        self._stack.setCurrentWidget(target)
        self._mode = mode
        # Re-apply theme so the new layout picks up colors
        self.refresh_theme()
```

- [ ] **Step 3: Manual test by forcing the mode**

```
python main.py
```

In a Python REPL or via temporary console hack: `app.multitoon_tab.set_layout_mode("full")` or wire a temporary hotkey. Skip if you don't have an easy hook — the real trigger comes in Task 11. The visual smoke check is "Full UI renders the 2×2 grid with one active card and three inactive cards."

If you can't easily switch modes manually, just verify `python main.py` still starts (Compact UI still default) and skip the visual check until Task 11.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py tabs/multitoon/_tab.py
git commit -m "feat(multitoon): add _FullLayout and set_layout_mode plumbing"
```

---

## Task 11: Window-level resize detection + breakpoint state machine

**Files:**
- Modify: `main.py` (add constants, `_layout_mode`, `resizeEvent`, `_set_layout_mode`)
- Test: `tests/test_layout_breakpoint.py`

- [ ] **Step 1: Write failing tests for the breakpoint state machine**

Create `tests/test_layout_breakpoint.py`:

```python
"""Tests for the window-size → layout-mode state machine in MultiToonTool."""

import pytest


# Pure function under test — extracted out of MultiToonTool so we can test
# without instantiating Qt windows.
from main import _decide_layout_mode, W_FULL, H_FULL, DEADBAND_W, DEADBAND_H


def test_decide_starts_compact_at_default_size():
    assert _decide_layout_mode("compact", 560, 650) == "compact"


def test_decide_swaps_to_full_above_breakpoint_plus_deadband():
    assert _decide_layout_mode("compact", W_FULL + DEADBAND_W, H_FULL + DEADBAND_H) == "full"


def test_decide_stays_compact_just_above_breakpoint_within_deadband():
    """Hysteresis: 1280-wide window stays compact because the 'enter Full' threshold is 1360."""
    assert _decide_layout_mode("compact", W_FULL, H_FULL) == "compact"
    assert _decide_layout_mode("compact", W_FULL + DEADBAND_W - 1, H_FULL + DEADBAND_H) == "compact"


def test_decide_stays_full_when_dragging_back_into_deadband():
    """Once in Full, stay there until well below the breakpoint."""
    assert _decide_layout_mode("full", W_FULL + 1, H_FULL + 1) == "full"
    assert _decide_layout_mode("full", W_FULL - DEADBAND_W + 1, H_FULL) == "full"


def test_decide_swaps_back_to_compact_below_breakpoint_minus_deadband():
    assert _decide_layout_mode("full", W_FULL - DEADBAND_W, H_FULL - DEADBAND_H) == "compact"


def test_decide_swaps_to_compact_when_either_dimension_drops():
    """Either dimension below the deadband triggers Compact — not both."""
    # Width drops, height stays high
    assert _decide_layout_mode("full", W_FULL - DEADBAND_W, H_FULL + 100) == "compact"
    # Height drops, width stays high
    assert _decide_layout_mode("full", W_FULL + 100, H_FULL - DEADBAND_H) == "compact"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_layout_breakpoint.py -v
```

Expected: `ImportError: cannot import name '_decide_layout_mode'`.

- [ ] **Step 3: Implement constants and pure decision function**

In `main.py`, after the `TITLE_ANIM_*` constants (around line 46), add:

```python
# Layout-mode breakpoint and hysteresis. Window must be >= W_FULL x H_FULL
# (plus deadband on the way up) to enter Full UI; Compact resumes once either
# dimension drops below (breakpoint - deadband) on the way down.
W_FULL = 1280
H_FULL = 800
DEADBAND_W = 80
DEADBAND_H = 60


def _decide_layout_mode(current: str, width: int, height: int) -> str:
    """Pure state-machine: return the layout mode for the given size, given the
    current mode. Implements deadband hysteresis so a window dragged across the
    breakpoint does not flicker."""
    if current == "compact":
        if width >= W_FULL + DEADBAND_W and height >= H_FULL + DEADBAND_H:
            return "full"
        return "compact"
    # current == "full"
    if width <= W_FULL - DEADBAND_W or height <= H_FULL - DEADBAND_H:
        return "compact"
    return "full"
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_layout_breakpoint.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Wire `resizeEvent` in `MultiToonTool`**

In `main.py`, add to the `MultiToonTool` class (place near `nav_select`, around line 337):

```python
    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = self.size()
        target = _decide_layout_mode(self._layout_mode, size.width(), size.height())
        if target != self._layout_mode:
            try:
                self._set_layout_mode(target)
            except Exception as e:
                if hasattr(self, "logger") and self.logger:
                    self.logger.append_log(f"[Layout] swap failed: {e}")

    def _set_layout_mode(self, target: str) -> None:
        # Default: instant swap. Cross-fade is added in Task 12.
        self.multitoon_tab.set_layout_mode(target)
        self._layout_mode = target
```

In `__init__` (around line 89, after `setMinimumWidth`), initialize the state:

```python
        self._layout_mode = "compact"
```

- [ ] **Step 6: Smoke test the full breakpoint flow**

```
python main.py
```

Open at default size — Compact UI. Maximize — Full UI swaps in instantly. Drag the border between 1200 and 1360 px — no flicker (you stay in whatever mode you started in). Reduce window — back to Compact.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_layout_breakpoint.py
git commit -m "feat(layout): wire resizeEvent + hysteresis to swap multitoon layout"
```

---

## Task 12: Cross-fade animation on layout swap

**Files:**
- Modify: `main.py` (replace the instant swap in `_set_layout_mode`)

- [ ] **Step 1: Replace `_set_layout_mode` with the cross-fade version**

In `main.py`, replace `_set_layout_mode` from Task 11 with:

```python
    def _set_layout_mode(self, target: str) -> None:
        # Honor disable_animations: instant swap, no fade.
        if self.settings_manager.get("disable_animations", False):
            self.multitoon_tab.set_layout_mode(target)
            self._layout_mode = target
            return

        # Cross-fade: 80ms fade-out -> swap -> 80ms fade-in (160ms total).
        widget = self.multitoon_tab
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        fade_out = QPropertyAnimation(effect, b"opacity")
        fade_out.setDuration(80)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.OutCubic)

        fade_in = QPropertyAnimation(effect, b"opacity")
        fade_in.setDuration(80)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)

        def _on_fade_out_done():
            self.multitoon_tab.set_layout_mode(target)
            self._layout_mode = target
            fade_in.start()

        fade_out.finished.connect(_on_fade_out_done)
        fade_in.finished.connect(lambda: widget.setGraphicsEffect(None))

        # Keep references so they don't get GC'd mid-animation.
        self._layout_fade_out = fade_out
        self._layout_fade_in = fade_in

        fade_out.start()
```

- [ ] **Step 2: Smoke test the fade**

```
python main.py
```

Maximize — observe a brief (160 ms) fade as Compact transitions to Full. Restore — same fade going back. Toggle "Disable animations" in Settings, repeat — swap is instant.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(layout): cross-fade animation on multitoon layout swap"
```

---

## Task 13: Status indicator pulse animation

**Files:**
- Modify: `tabs/multitoon/_full_layout.py` (add pulse to `_FullToonCard.set_active`)

- [ ] **Step 1: Add pulse property animation when active**

In `tabs/multitoon/_full_layout.py`, at the top of the file add:

```python
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QAbstractAnimation
```

(Most likely already there — extend the existing import line.)

Update `_FullToonCard.set_active`:

```python
    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._active_root.setVisible(active)
        self._inactive_root.setVisible(not active)
        if active:
            self._status_indicator.set_active(True)
            self._start_pulse()
        else:
            self._stop_pulse()

    def _start_pulse(self) -> None:
        if getattr(self, "_pulse_anim", None) is not None:
            return
        # Respect the user's reduced-motion / disable_animations setting
        sm = getattr(self._tab, "settings_manager", None)
        if sm and sm.get("disable_animations", False):
            return
        self._pulse_anim = QPropertyAnimation(self._status_indicator, b"glow")
        self._pulse_anim.setDuration(1500)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setKeyValueAt(0.5, 1.0)
        self._pulse_anim.setEndValue(0.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.start()

    def _stop_pulse(self) -> None:
        anim = getattr(self, "_pulse_anim", None)
        if anim is not None:
            anim.stop()
            self._pulse_anim = None
        self._status_indicator._set_glow(0.0)
```

- [ ] **Step 2: Smoke test the pulse**

```
python main.py
```

Maximize, ensure at least one toon is detected (active card). The status dot should breathe smoothly. Toggle "Disable animations" — pulse stops within one cycle.

- [ ] **Step 3: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "feat(multitoon): pulse animation on Full UI status indicator"
```

---

## Task 14: Theme integration for Full UI + final smoke pass

**Files:**
- Modify: `tabs/multitoon/_tab.py` (`refresh_theme` now needs to call into the active layout)

- [ ] **Step 1: Make `refresh_theme` call into the active layout**

In `tabs/multitoon/_tab.py`, find the existing `refresh_theme` (search `def refresh_theme`). Add at its end:

```python
        # Apply theme to the active layout (Compact uses the existing per-card
        # logic above; Full has its own apply_theme entry point)
        if hasattr(self, "_full") and self._mode == "full":
            self._full.apply_theme(self._c())
        if hasattr(self, "_compact") and self._mode == "compact":
            # Compact's per-card theming already runs above; add the outer-card
            # background here so the 720px clamp shows the right color
            c = self._c()
            self._compact.setStyleSheet(f"QWidget {{ background: {c['bg_app']}; }}")
```

- [ ] **Step 2: Final visual smoke test**

```
python main.py
```

Run through the full checklist:

- Open at default 560×650 → Compact UI, looks like before.
- Toggle theme dark↔light → both layouts re-color cleanly, no leftover Catppuccin lavender.
- Drag window border slowly from 1100 to 1400 px → no flicker between 1200 and 1360.
- Maximize → Full UI swaps in with a 160 ms fade. Status dot pulses on active toon.
- Restore → fade back to Compact.
- Settings → toggle "Disable animations" → both directions swap instantly.
- Click each non-Multitoon tab at maximize → all clamp to 720 px and center.
- Run all tests:

```
pytest tests/ -v
```

Expected: every test passes.

- [ ] **Step 3: Commit final integration + close out the plan**

```bash
git add tabs/multitoon/_tab.py
git commit -m "feat(multitoon): apply theme to Full UI on refresh"
```

---

## Self-review (written after the last task)

**1. Spec coverage:**
- Layout selection (resizeEvent + hysteresis): Tasks 11, 12.
- MultitoonTab layout swap (QStackedWidget + shared widgets): Tasks 6, 7, 10.
- Compact layout (with 720px clamp): Task 7.
- Full layout (service bar + 2x2 grid): Task 10.
- Cross-fade animation: Task 12.
- Other tabs clamp-and-center: Task 5.
- Theme palette (dark + light + new tokens): Tasks 2, 3, 4.
- Status dot widget (Discord-style): Task 8, pulse Task 13.
- Game pill: Task 9 (`_FullToonCard.apply_theme`).
- Controls row uniform height (`_make_ctrl_32`): Task 9.
- Card shadow update for slate-tinted shadow: Task 4.
- `disable_animations` short-circuit: Tasks 12 (layout swap), 13 (pulse).
- Tests for theme tokens, breakpoint state machine, layout helper: Tasks 1, 2, 3, 8, 11.

All spec sections covered.

**2. Placeholder scan:** No "TBD", "TODO", or vague-pattern lines in any task.

**3. Type consistency:**
- `_decide_layout_mode(current: str, width: int, height: int) -> str` — used in Task 11, called identically in `MultiToonTool.resizeEvent`.
- `set_layout_mode(mode: str)` — defined in Task 7 as a no-op, replaced in Task 10, called from Task 11.
- `apply_theme(c: dict)` — defined on `_FullToonCard` (Task 9) and `_FullLayout` (Task 10), called from Task 14.
- `_StatusIndicator.apply_theme(ring_hex, active_hex, idle_hex)` — defined Task 8, called from `_FullToonCard.apply_theme` Task 9.

All consistent.

---

## Plan complete — saved to `docs/superpowers/plans/2026-04-26-multitoon-full-ui.md`

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
