# Full UI Service Bar Redesign — Design Spec

## Problem

The Full UI's service bar is a compact inline row: a small toggle button (min 180px), profile pills, and refresh — all crammed into one horizontal strip wrapped in a QFrame. On large monitors this looks undersized and disconnected from the Compact UI's more prominent controls. The user's Photoshop mockup shows a better approach: a centered floating control block with a full-width button, status bar, and profile pills stacked vertically.

## Solution

Replace the framed single-row service bar with a centered, frameless vertical control block. Simultaneously adjust the card aspect ratio from 16:10 (1.6) to 7:4 (1.75).

## Service Controls Layout

Top-to-bottom, centered in the available width:

1. **Start/Stop button** — full width within the centered block
2. **Status bar** — full width, below button (8px gap)
3. **Profile pills row** — numbered circles + refresh button, centered (12px gap from status)

The controls block has a max-width of **960px** and centers horizontally using the stretch pattern (`addStretch(1) | widget(100) | addStretch(1)`) with `setSizePolicy(Expanding, Preferred)`.

No QFrame wrapper — controls sit directly on the app background.

## Config Label + Card Grid

Below the controls (16px gap from pills to label):

4. **"TOON CONFIGURATION" label** — left-aligned with the card grid's left edge
5. **Card grid** — 2x2, 8px below the label

The config label is a child of the grid container, positioned manually in `_position_cards()` so it always aligns with the computed grid `offset_x`.

## Card Aspect Ratio Change

Aspect ratio changes from **1.6 (16:10)** to **1.75 (7:4)**.

Max card size: **1050x600** (1050/1.75 = 600, maintains the same max height).

Constants:
- `_ASPECT = 1.75`
- `_MAX_CARD_W = 1050`
- `_MAX_CARD_H = 600`

## Spacing Summary

| Gap | Pixels | Between |
|-----|--------|---------|
| Button → status bar | 8 | toggle_service_button bottom → status_bar top |
| Status bar → pills | 12 | status_bar bottom → pills row top |
| Pills → config label | 16 | pills row bottom → "TOON CONFIGURATION" top |
| Config label → cards | 8 | label bottom → card grid top |
| Card horizontal | 12 | left card right edge → right card left edge |
| Card vertical | 12 | top card bottom edge → bottom card top edge |
| Outer margins | 20/16/20/16 | left/top/right/bottom around the entire layout |

## Layout Structure

### Current
```
outer QVBoxLayout (margins 20/16/20/16, spacing 14)
├── service_bar QFrame
│   └── QVBoxLayout
│       ├── service_row QHBoxLayout (toggle | stretch | pills | refresh)
│       └── status_bar
└── _GridContainer (stretch=1)
    └── 4x _FullToonCard (positioned via setGeometry)
```

### New
```
outer QVBoxLayout (margins 20/16/20/16, spacing 0)
├── controls_center QHBoxLayout
│   ├── stretch(1)
│   ├── controls_wrapper QWidget (max-width 960, expanding) [stretch 100]
│   │   └── QVBoxLayout (no margins, spacing 0)
│   │       ├── toggle_service_button
│   │       ├── spacing(8)
│   │       ├── status_bar
│   │       ├── spacing(12)
│   │       └── pills_row QHBoxLayout (centered: stretch | pills | refresh | stretch)
│   └── stretch(1)
├── spacing(16)
└── _GridContainer (stretch=1)
    ├── config_label (positioned manually, left-aligned with grid)
    └── 4x _FullToonCard (positioned via setGeometry)
```

## Code Changes

### `_FullLayout._build_structure`

Remove the `service_bar` QFrame. Replace with:

```python
controls = QWidget()
controls.setMaximumWidth(960)
controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
ctrl_layout = QVBoxLayout(controls)
ctrl_layout.setContentsMargins(0, 0, 0, 0)
ctrl_layout.setSpacing(0)
# Slots for populate(): self._ctrl_layout, self._pills_row
```

Center it:
```python
center_row = QHBoxLayout()
center_row.addStretch(1)
center_row.addWidget(controls, 100)
center_row.addStretch(1)
outer.addLayout(center_row)
outer.addSpacing(16)
```

The config label becomes a child of `_grid_container`, positioned in `_position_cards()`.

### `_FullLayout._position_cards`

Account for the config label above the card grid:

```python
label_h = self._config_label.sizeHint().height()  # ~20px
label_gap = 8

avail_h = h - label_h - label_gap  # remaining height for cards

# ... compute card_w, card_h as before but with avail_h ...

# Center the block: label + gap + grid
total_h = label_h + label_gap + grid_h
oy = (h - total_h) // 2

# Position label
self._config_label.setGeometry(ox, oy, grid_w, label_h)

# Position cards starting below label
cards_oy = oy + label_h + label_gap
```

### `_FullLayout.populate`

Replace the service-row logic:

```python
clear_layout(self._ctrl_layout)
self._ctrl_layout.addWidget(self._tab.toggle_service_button)
self._ctrl_layout.addSpacing(8)
self._ctrl_layout.addWidget(self._tab.status_bar)
self._ctrl_layout.addSpacing(12)

clear_layout(self._pills_row)
self._pills_row.addStretch()
for pill in self._tab.profile_pills:
    self._pills_row.addWidget(pill)
self._pills_row.addSpacing(4)
self._pills_row.addWidget(self._tab.refresh_button)
self._pills_row.addStretch()
self._ctrl_layout.addLayout(self._pills_row)
```

The `config_label` is reparented to `_grid_container` (it's positioned manually).

### `_FullLayout` constants

```python
_ASPECT = 1.75   # was 1.6
_MAX_CARD_W = 1050  # was 960
_MAX_CARD_H = 600   # unchanged
```

### `_FullToonCard._REF_H`

Unchanged at 400. Content scaling reference height is independent of the card max size.

## Compact Resets

No changes needed. `_compact_layout.py`'s `_populate_card` resets shared widgets to constructor defaults regardless of what Full applied.

## Test Updates

- `test_full_grid_enforces_aspect_ratio` — change expected ratio from ~1.6 to ~1.75
- `test_full_grid_caps_at_max_size` — change max width assertion from 960 to 1050 (height stays 600)
- Tests that check service bar reparenting (`test_swap_to_full_reparents_shared_widgets`, etc.) — `toggle_service_button` is now under `controls_wrapper` which is a child of `_full`, so `_is_descendant_of(toggle_service_button, tab._full)` still passes
- All other tests should pass without changes since content scaling, button sizes, and roundtrip resets are unaffected

## Behavior at Key Resolutions

| Resolution | Controls width | Card size | Scale | Notes |
|-----------|---------------|-----------|-------|-------|
| 1280x800 | ~720px | ~485x277 | 0.66 | Controls fill most width, cards fit |
| 1920x1080 | ~960px (capped) | ~730x417 | 1.05 | Controls centered, cards fill well |
| 2560x1440 | ~960px (capped) | 1045x597 | 1.54 | Controls centered, cards near max |
