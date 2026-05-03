# Full UI Aspect Ratio Cards — Design Spec

## Problem

The Full UI 2x2 card grid uses `QGridLayout`, which divides space equally with no aspect ratio constraint. On large monitors (1440p+) cards become enormous rectangles with tiny content blocks floating inside. The content block was fixed at 500x240, so it doesn't scale with the card at all.

## Solution

Replace `QGridLayout` with manual 2x2 positioning. Cards maintain a fixed 3:2 aspect ratio, cap at 600x400, and center as a group when they hit max size. Content inside each card scales proportionally with card dimensions.

## Card Sizing

Computed in `_FullLayout.resizeEvent`:

1. Available grid area = tab space minus service bar height, outer margins (20/16px), and spacing (14px between service bar and grid).
2. `card_w = (avail_w - h_spacing) / 2`
3. `card_h = card_w / 1.5` (3:2 ratio)
4. If `card_h * 2 + v_spacing > avail_h`: height-constrained mode. `card_h = (avail_h - v_spacing) / 2`, `card_w = card_h * 1.5`.
5. Clamp both to max 600x400.
6. Compute grid block dimensions: `grid_w = card_w * 2 + h_spacing`, `grid_h = card_h * 2 + v_spacing`.
7. Center the grid block within available space: `offset_x = (avail_w - grid_w) / 2`, `offset_y = (avail_h - grid_h) / 2`.
8. Position each card via `setGeometry`:
   - Card 0: `(offset_x, offset_y)`
   - Card 1: `(offset_x + card_w + h_spacing, offset_y)`
   - Card 2: `(offset_x, offset_y + card_h + v_spacing)`
   - Card 3: `(offset_x + card_w + h_spacing, offset_y + card_h + v_spacing)`

Grid spacing: 12px horizontal, 12px vertical (same as current `QGridLayout` settings).

## Content Scaling

Computed in `_FullToonCard.resizeEvent`:

- Reference height: 400px (the max card height). At this height, `scale = 1.0`.
- `scale = (card_height - vertical_margins) / (400 - vertical_margins)` where vertical margins = top + bottom card padding (18 + 18 = 36px).
- Minimum scale: 0.6 (prevents content from becoming unreadable on very small cards).

Scaled elements (all values are at scale 1.0):

| Element | Size at scale 1.0 | Formula |
|---------|-------------------|---------|
| Portrait | 130x130 | `int(130 * scale)` square |
| Name font | 22px | `int(22 * scale)` px, min 14 |
| Stats font | 15px | `int(15 * scale)` px, min 11 |
| Enable button | 100x40 | `int(100 * scale)` x `int(40 * scale)` |
| Chat button | 40x40 | `int(40 * scale)` square |
| KA button | 40x40 | `int(40 * scale)` square |
| KA progress bar | 120x10 | `int(120 * scale)` x `int(10 * scale)` |
| Set selector | height 40 | `int(40 * scale)` |
| Content row spacing | 16px | `int(16 * scale)` |
| Root vbox spacing | 10px | `int(10 * scale)` |
| Ctrl row spacing | 8px | `int(8 * scale)` |

Status indicator stays fixed at 32x32 — it's a small overlay dot that doesn't need scaling. Its position on the portrait scales: `(portrait_size - 30, portrait_size - 30)`.

Game pill stays fixed size (font-size 10px, padding 3px 10px) — it's a small badge. Its position is relative to the card's top-right corner: `(self.width() - pill_w - 14, 14)`.

## Layout Structure Changes

### `_FullLayout._build_structure`

Remove `QGridLayout`. Instead:
- Create the service bar as before (QFrame with service_row + status_bar).
- Create 4 `_FullToonCard` instances, store in `self._cards`.
- Create a plain `QWidget` as the grid container. Cards are children of this container.
- The outer `QVBoxLayout` holds the service bar and the grid container (stretch=1).

### `_FullLayout.resizeEvent`

New method. Computes card size and positions all 4 cards within the grid container using `setGeometry`.

### `_FullToonCard._build_active_structure`

Revert `_active_root` to being part of `_stack_layout` (remove manual positioning). Remove `setMaximumSize(500, 240)`. The card is now properly sized by the grid, so `_active_root` fills it naturally.

### `_FullToonCard.resizeEvent`

Replace `_position_content()` with `_scale_content()`:
- Compute scale factor from card height.
- Resize portrait, buttons, progress bar, selector.
- Update font sizes on name/stats labels via stylesheet.
- Reposition status indicator on portrait.
- Reposition game pill at card top-right.

### `_FullToonCard.populate_active`

Remove all fixed pixel sizes. Set initial sizes based on a default scale (1.0). The actual sizes will be overridden by `_scale_content()` on the first `resizeEvent`.

### `_FullToonCard._position_content` / `_resize_portrait`

Both deleted. Replaced by `_scale_content`.

## Compact Resets

`_compact_layout.py`'s `_populate_card` already resets shared widgets to constructor defaults. The reset values (88x32 enable, 32x32 chat/KA, 28px selector, 38-64 badge, 7px ka_bar) remain correct regardless of what scale Full applied. No functional changes needed — only the comment about Full's sizes needs updating since they're now dynamic.

## Test Updates

Tests that assert fixed pixel values for Full UI will need to account for scaling. Since tests run offscreen with no real geometry, the card may not have received a meaningful `resizeEvent`. Options:

1. Force a resize in the test: `card.resize(600, 400)` then `qapp.processEvents()` — then assert scale-1.0 values.
2. Test the scale computation logic directly rather than pixel values.

Tests to update:
- `test_full_controls_scaled` — force resize, then assert scale-1.0 values
- `test_full_card_portrait_fixed_size` — rename, force resize, assert 130x130
- `test_full_card_content_block_bounded` — remove (no longer has max bounds on `_active_root`)
- `test_full_name_label_styling_survives_refresh_theme` — assert 22px (scale 1.0 after forced resize)
- `test_full_stats_labels_get_scaled_font` — assert 15px (scale 1.0 after forced resize)
- `test_full_to_compact_roundtrip_restores_shared_widget_sizes` — force resize before asserting Full values
- `test_full_to_compact_roundtrip_restores_button_sizes` — force resize before asserting Full values

## Behavior at Key Resolutions

| Resolution | Available grid area | Card size | Scale | Notes |
|-----------|-------------------|-----------|-------|-------|
| 1280x800 (min Full UI) | ~1200x670 | ~497x331 | 0.81 | Cards fill most of the space |
| 1920x1080 | ~1840x920 | 600x400 (capped) | 1.0 | Grid ~1212x812, centered |
| 2560x1440 | ~2460x1300 | 600x400 (capped) | 1.0 | Grid centers with generous margin |
