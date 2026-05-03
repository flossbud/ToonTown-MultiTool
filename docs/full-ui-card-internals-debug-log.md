# Full UI Card Internals — Debug Log

## The Problem

The Full UI's active toon card internals didn't match the Photoshop mockup. Despite six distinct implementation attempts across multiple sessions, every iteration produced controls that looked visibly wrong compared to the target design.

The mockup showed that card internals should behave as a single design surface — every element positioned and scaled proportionally relative to the card frame, not managed by Qt layouts with independent size policies.

---

## What Was Tried (All Failed)

### Attempt 1: Original Full UI card sizes

First pass at card internals. Portrait 90px, buttons at Compact defaults (32px). Controls were too small relative to the 7:4 card area.

**Result:** Controls too small, card felt empty. Rejected.

### Attempt 2: Bumped sizes without proportional thinking

Increased portrait to 104px, buttons to 36px, progress bar to 90x8. Ad-hoc numbers with no consistent scaling rule.

**Result:** Better but proportions were arbitrary. Rejected.

### Attempt 3: "Card Internals Redesign" — custom Full-only references

Wrote a formal design spec and picked new "Full reference sizes" (42px buttons, 100px enable width, 10px bar height). Every element was scaled by a different factor — enable button went from 2.75:1 to 2.38:1 aspect ratio, selector grew 50% while buttons grew 31%.

**Result:** Controls were visibly disproportionate. "wrong. it looks wrong."

### Attempt 4: Fix stats label alignment

Added `text-align: left;` to stats stylesheet. Symptom fix only.

### Attempt 5: Fix name label style persistence

Found `_refresh_toon_name_labels()` was overwriting Full's 28px name to Compact's 14px on every detection callback. Added mode-aware re-application.

**Result:** Name label persisted correctly, but controls still had wrong proportions.

### Attempt 6: Switch to Compact base sizes with uniform scale

Changed `populate_active` and `_scale_content` to use Compact's constructor defaults (32h, 88w, etc.) as the base, scaled uniformly. Tests passed, but visual result was still wrong — Qt layouts were fighting the scaling, and the proportional relationships between elements (e.g., where the name sits relative to the portrait, how much gap between controls) still didn't match the mockup.

**Result:** Proportions improved but layout engine interference made pixel-perfect placement impossible.

---

## What Actually Fixed It (Codex)

The fundamental realization: **Qt layouts cannot reproduce a design-surface mockup.** The card internals needed to be treated as a single coordinate system where every element has a fixed position and size relative to a reference card, then the whole thing scales as one unit.

### Architectural Change: Layout-free absolute positioning

Codex replaced the entire `QVBoxLayout`/`QHBoxLayout` structure inside `_FullToonCard` with **absolute positioning using reference rectangles**.

**Reference design surface** — a 632x360 pixel coordinate system captured from the Photoshop mockup:

| Element | QRect (x, y, w, h) | Notes |
|---------|-------------------|-------|
| Portrait | (26, 88, 168, 168) | Large circle, left side |
| Status indicator | (132, 132, 42, 42) | Relative to portrait, overlaps edge |
| Name label | (219, 104, 360, 54) | Right of portrait, bold heading |
| LAFF label | (249, 158, 150, 30) | Below name, with icon |
| Beans label | (249, 200, 165, 30) | Below LAFF, with icon |
| Enable button | (24, 279, 118, 43) | Bottom-left |
| Chat button | (151, 279, 43, 43) | Square, next to enable |
| Keep-alive button | (203, 279, 43, 43) | Square, next to chat |
| Progress bar | (255, 296, 150, 9) | Fixed width, vertically centered in row |
| Selector | (436, 284, 174, 36) | Right side of controls row |
| Game pill | (568, 14, 51, 23) | Top-right corner, proper rounded pill |

**Scaling** — a single scale factor derived from `min(card_w / 632, card_h / 360)`, clamped to `[0.55, ∞)`. Every QRect is multiplied by this factor via `_scaled_rect()`, so the entire card scales as one design surface.

### Key changes in `_full_layout.py`:

1. **Removed all QVBoxLayout/QHBoxLayout from card internals.** No more `_info_col`, `_ctrl_row`, `_content_row`, `_stack_layout`. The `_active_root` is now a plain QWidget with children positioned via `setGeometry()`.

2. **`_layout_active_content()`** replaces both `_scale_content()` and `resizeEvent` positioning. Computes scale once, then calls `_scaled_rect()` for every element and `_place_fixed()` to set geometry.

3. **`_StatusIndicator` now accepts a `size` parameter** and paints relative to its own bounds instead of hardcoded 32px. Ring and dot sizes scale with the widget.

4. **`_detach_from_layouts()`** helper cleanly removes shared widgets from any ancestor layouts before manual `setParent()`, preventing Qt layout conflicts.

5. **`_make_ctrl_32()`** compatibility helper for setting controls back to Compact's 32px baseline with 6px radius.

6. **Game pill is now a proper rounded pill** — `_apply_game_pill_style()` computes pill dimensions from the reference rect, sets `border-radius: height/2`, centers text with `Qt.AlignCenter`, and distinguishes TTR vs CC colors.

7. **Button font scaling** — `_scale_button_styles()` updates `font-size` in button stylesheets proportionally via regex replacement.

8. **Icon scaling** — chat/KA button icons and stat label icons resize with the scale factor via `setIconSize()`.

9. **Selector paint scaling** — if the selector widget has a `set_paint_scale()` method, it gets the current scale factor for internal paint adjustments.

### Key changes in `_compact_layout.py`:

1. **Selector width reset** — added `setMinimumWidth(130)` and `setMaximumWidth(QWIDGETSIZE_MAX)` to undo Full's fixed-width selector.

2. **`set_paint_scale(1.0)` reset** — restores selector's internal paint scale.

3. **Game badge size reset** — `setMinimumSize(0, 0)` and `setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)` to undo Full's fixed pill size.

4. **Icon restoration** — re-applies `make_heart_icon(16)` and `make_jellybean_icon(16)` to stat labels.

### Key changes in `_tab.py`:

1. **`_c()` method** now accessible for theme color lookups from card code.

2. **Full mode guard in `apply_visual_state`** — `_layout_active_content` only fires when actually in full mode, preventing hidden Full cards from mutating shared widget sizes while Compact is visible.

### Key changes in tests:

1. **Reference sizes updated** — portrait 150→168, buttons 42→43, selector 42→36, bar 10→9, enable width 100→118.

2. **New test: `test_compact_visual_state_does_not_apply_full_scaling`** — verifies that window detection in Compact mode doesn't let hidden Full cards resize shared widgets.

3. **New test: `test_stats_labels_keep_icons_in_full_mode`** — Full stats labels retain their heart/jellybean icons.

4. **New test: `test_game_pill_text_is_centered`** — pill text uses `Qt.AlignCenter`.

5. **New test: `test_full_inactive_card_root_does_not_cover_card_frame`** — inactive card roots use transparent backgrounds so the card frame shows through.

6. **New test: `test_full_layout_uses_full_surface_colors`** — Full card surfaces use theme card colors.

7. **New tests for light/dark Compact card surfaces** — verify correct card colors per theme.

8. **New test: `test_full_status_indicator_is_not_clipped_by_portrait`** — status dot is parented to `_active_root` (not `_portrait_wrap`) so it can visually overflow the portrait edge.

9. **New test: `test_full_progress_bar_width_is_capped`** — bar uses fixed width from reference, not flex-fill.

10. **New test: `test_full_active_card_reference_ratios_hold_across_sizes`** — verifies that all element position/size ratios remain constant when the card is resized, proving the design-surface scaling works.

---

## Root Cause

Qt layouts (QVBoxLayout, QHBoxLayout) distribute space according to size policies, stretch factors, and minimum/maximum constraints. When you need pixel-perfect reproduction of a design mockup, layouts fight you — they add spacing, redistribute leftover pixels, and make independent sizing decisions per widget.

The fix was to abandon layouts inside the card and treat it as a fixed coordinate system that scales uniformly. Every element has one source of truth: its QRect in the 632x360 reference surface.

---

## Lessons

1. **Qt layouts are wrong for design-surface reproduction.** Use absolute positioning with reference rects when the goal is "make it look exactly like this mockup."
2. **A single scale factor for everything** is the only way to guarantee proportional relationships hold across sizes.
3. **Six failed attempts** all shared the same mistake: trying to make Qt's layout engine produce a specific visual result by tweaking individual widget sizes.
4. **The status indicator must parent to `_active_root`, not `_portrait_wrap`**, so it can visually overflow the portrait bounds without clipping.
5. **Shared widget reparenting needs `_detach_from_layouts()`** to cleanly sever layout ownership before manual positioning.
