# Full UI Card Internals Redesign — Design Spec

## Problem

The active toon card's internal elements are undersized relative to the card area. The name label is small (22px ref, DemiBold), the portrait is modest (130px ref), and the progress bar has a fixed width (120px) leaving a dead gap before the set selector. The user's Photoshop mockup shows a better balance: a larger portrait, a bold heading-sized name, and the progress bar filling the available space.

## Solution

Update the reference sizes for in-card elements so they fill the card proportionally. All values continue to scale via the existing `_scale_content` mechanism (`scale = content_h / (_REF_H - margins)`). No new scaling logic needed.

## Reference Size Changes

All values below are at scale 1.0 (card height = `_REF_H`). The scale factor is applied identically to today.

| Element | Current ref | New ref | Notes |
|---------|------------|---------|-------|
| Portrait | 130px | 150px | `_portrait_wrap` + `slot_badges` |
| Status indicator offset | `ps - 30` | `ps - 32` | Keeps dot at bottom-right edge |
| Name font | 22px / DemiBold (600) | 28px / Bold (700) | Heading style |
| Name padding-right | 60px | 60px | Unchanged, prevents overlap with game pill |
| Stats font | 15px / 600wt | 16px / 600wt | Minor bump for balance |
| Button height | 40px | 42px | All ctrl-row buttons |
| Enable button width | 100px | 100px | Unchanged |
| Chat/KA button width | `bh` (40px) | `bh` (42px) | Matches height |
| Progress bar height | 10px | 10px | Unchanged |
| Progress bar width | fixed 120px | flex fill | Removes `addStretch(1)`, bar gets stretch factor |
| Content row spacing | 16px | 20px | Gap between portrait and info col |
| Ctrl row spacing | 8px | 8px | Unchanged |
| Root vbox spacing | 10px | 10px | Unchanged |
| Border-radius (controls) | 6px | 8px | `_style_ctrl` default |

## Code Changes

### `_style_ctrl` (line 73)

Change default border-radius from 6px to 8px:

```python
def _style_ctrl(widget: QWidget, height: int = 32) -> None:
    widget.setFixedHeight(height)
    sheet = widget.styleSheet()
    if "border-radius" not in sheet:
        widget.setStyleSheet(sheet + "border-radius: 8px;")
```

### `_FullToonCard._build_active_structure` (line 122)

Update portrait ref size and content row spacing:

```python
self._portrait_wrap = QWidget()
self._portrait_wrap.setFixedSize(150, 150)       # was 130
self._status_indicator = _StatusIndicator(self._portrait_wrap)
self._status_indicator.move(118, 118)             # was 100, 100

self._content_row.setSpacing(20)                  # was 16
```

### `_FullToonCard.populate_active` (line 151)

Update portrait size and progress bar layout:

```python
# Portrait — fixed 150x150
portrait = self._tab.slot_badges[self._slot]
portrait.setParent(self._portrait_wrap)
portrait.setFixedSize(150, 150)                   # was 130
portrait.move(0, 0)
self._status_indicator.setParent(self._portrait_wrap)
self._status_indicator.move(118, 118)             # was 100, 100
```

Button heights change to 42:

```python
btn = self._tab.toon_buttons[self._slot]
_style_ctrl(btn, 42)                              # was 40
btn.setFixedWidth(100)

chat = self._tab.chat_buttons[self._slot]
_style_ctrl(chat, 42)                             # was 40
chat.setFixedWidth(42)                            # was 40

ka = self._tab.keep_alive_buttons[self._slot]
_style_ctrl(ka, 42)                               # was 40
ka.setFixedWidth(42)                              # was 40
```

Progress bar becomes flex-fill:

```python
ka_bar = self._tab.ka_progress_bars[self._slot]
ka_bar.setFixedHeight(10)
ka_bar.setMinimumWidth(40)
self._ctrl_row.addWidget(ka_bar, 1)               # stretch factor 1, was addWidget + addStretch
# REMOVE: self._ctrl_row.addStretch(1)

selector = self._tab.set_selectors[self._slot]
_style_ctrl(selector, 42)                         # was 40
```

### `_FullToonCard._scale_content` (line 318)

Update portrait ref, button ref, progress bar scaling, and content spacing:

```python
ps = int(150 * scale)                             # was 130
self._portrait_wrap.setFixedSize(ps, ps)
self._tab.slot_badges[self._slot].setFixedSize(ps, ps)
ind_offset = ps - 32                              # was ps - 30
self._status_indicator.move(ind_offset, ind_offset)

bh = int(42 * scale)                              # was 40
self._tab.toon_buttons[self._slot].setFixedHeight(bh)
self._tab.toon_buttons[self._slot].setFixedWidth(int(100 * scale))
self._tab.chat_buttons[self._slot].setFixedHeight(bh)
self._tab.chat_buttons[self._slot].setFixedWidth(bh)
self._tab.keep_alive_buttons[self._slot].setFixedHeight(bh)
self._tab.keep_alive_buttons[self._slot].setFixedWidth(bh)

self._tab.ka_progress_bars[self._slot].setFixedHeight(max(4, int(10 * scale)))
# No width scaling — bar is flex-fill
self._tab.set_selectors[self._slot].setFixedHeight(bh)

self._active_root.layout().setSpacing(int(10 * scale))
self._content_row.setSpacing(int(20 * scale))     # was 16
self._ctrl_row.setSpacing(int(8 * scale))
```

### `_FullToonCard._apply_scaled_styles` (line 354)

Update name font size and weight:

```python
name_label.setStyleSheet(
    f"font-size: {int(28 * s)}px; font-weight: 700; color: {c['text_primary']}; "
    f"background: transparent; border: none; padding-right: 60px;"
)
f = name_label.font()
f.setPointSize(int(28 * s))
f.setWeight(QFont.Bold)                           # was DemiBold
name_label.setFont(f)
for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
    lbl.setStyleSheet(
        f"border: none; background: transparent; font-weight: 600; "
        f"font-size: {int(16 * s)}px; color: {c['text_primary']};"
    )
```

## Compact Resets

`_compact_layout.py` `_populate_card` already resets:
- `slot_badges[i]` to min 38x38 / max 64x64
- `toon_buttons[i]` to 88x32
- `chat_buttons[i]` / `keep_alive_buttons[i]` to 32x32
- `ka_progress_bars[i]` to fixedHeight(7), minWidth(40), maxWidth(QWIDGETSIZE_MAX)
- `name_label` font cleared

No new resets needed — the existing resets cover all changed values.

## Test Updates

- `test_full_controls_scaled` (line 284) — update expected button height from 40 to 42, chat/KA width from 40 to 42, portrait from 130 to 150. Remove `ka_bar.maximumWidth() == 120` assertion (bar is now flex-fill, no fixed width). Keep `ka_bar.maximumHeight() == 10`.
- `test_full_card_portrait_fixed_size` (line 252) — update expected portrait size from 130 to 150 in all assertions
- `test_full_content_scales_with_card_size` (line 393) — update `portrait_full == 130` to 150, `0.6 * 130 = 78` to `0.6 * 150 = 90`
- `test_full_to_compact_roundtrip_restores_button_sizes` (line 312) — update `maximumHeight() == 40` assertion to 42
- `test_full_to_compact_roundtrip_restores_shared_widget_sizes` (line 157) — update `set_selectors[0].maximumHeight() == 40` to 42
- All reparenting tests — no changes (widget hierarchy unchanged)
