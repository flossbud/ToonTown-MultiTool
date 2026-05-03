# Full UI Centered Content Block Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Do NOT add any `Co-Authored-By` line to commit messages.**

**Goal:** Replace the stretchy QVBoxLayout-based card content with a bounded, manually-positioned content block that stays proportional and centered within the card at any window size.

**Architecture:** Remove `_active_root` from `_stack_layout` and position it manually in `resizeEvent` with a hard max of 500x240. Internal elements use fixed proportional sizes (130px portrait, 22px name, 15px stats, 40px controls). Excess card space becomes padding around the content block. Game pill repositions relative to the content block, not the card corners.

**Tech Stack:** PySide6 (QWidget manual geometry, QFrame, QVBoxLayout/QHBoxLayout)

---

## File Structure

| File | Role |
|------|------|
| `tabs/multitoon/_full_layout.py` | Primary changes: card architecture, content positioning, sizing |
| `tabs/multitoon/_compact_layout.py` | Update compact resets to match new Full sizes (40px controls, etc.) |
| `tests/test_layout_reparent.py` | Update assertions for new proportional sizes |

---

### Task 1: Update test assertions for the new proportional sizes

All existing tests pass with the current (broken) layout. Before changing any production code, update the test expectations to match the new design so they **fail** against the current code — confirming we're testing the right things.

**Files:**
- Modify: `tests/test_layout_reparent.py`

- [ ] **Step 1: Update `test_full_controls_scaled` for 40px controls**

Change button/control assertions from 44px to 40px and enable button from 110 to 100, ka_bar from 140x12 to 120x10:

```python
def test_full_controls_scaled(tab):
    """Full UI controls must be 40px tall."""
    tab.set_layout_mode("full")

    btn = tab.toon_buttons[0]
    assert btn.maximumHeight() == 40, (
        f"enable button should be 40px tall; got max height {btn.maximumHeight()}"
    )
    assert btn.maximumWidth() == 100, (
        f"enable button should be 100px wide; got max width {btn.maximumWidth()}"
    )

    chat = tab.chat_buttons[0]
    assert chat.maximumHeight() == 40, (
        f"chat button should be 40px tall; got {chat.maximumHeight()}"
    )
    assert chat.maximumWidth() == 40, (
        f"chat button should be 40px wide; got {chat.maximumWidth()}"
    )

    ka_bar = tab.ka_progress_bars[0]
    assert ka_bar.maximumWidth() == 120, (
        f"ka progress bar should be 120px wide; got {ka_bar.maximumWidth()}"
    )
    assert ka_bar.maximumHeight() == 10, (
        f"ka progress bar should be 10px tall; got {ka_bar.maximumHeight()}"
    )
```

- [ ] **Step 2: Update `test_full_name_label_styling_survives_refresh_theme` for 22px name**

Change assertion from `font-size: 26px` to `font-size: 22px`:

```python
def test_full_name_label_styling_survives_refresh_theme(tab):
    """Critical bug regression: refresh_theme must not wipe Full UI's name styling."""
    tab.set_layout_mode("full")
    tab.refresh_theme()

    name_label, _ = tab.toon_labels[0]
    sheet = name_label.styleSheet()
    assert "font-size: 22px" in sheet, f"Full name-label should be 22px; got {sheet!r}"
    assert "padding-right: 60px" in sheet, (
        f"Full name-label should reserve 60px for game pill; got {sheet!r}"
    )
```

- [ ] **Step 3: Update `test_full_stats_labels_get_scaled_font` for 15px stats**

Change assertion from `font-size: 17px` to `font-size: 15px`:

```python
def test_full_stats_labels_get_scaled_font(tab):
    """Stats labels (LAFF/beans) must get Full UI's 15px override, not
    compact's 13px, after refresh_theme + Full apply_theme."""
    tab.set_layout_mode("full")
    tab.refresh_theme()

    for label_list in (tab.laff_labels, tab.bean_labels):
        sheet = label_list[0].styleSheet()
        assert "font-size: 15px" in sheet, (
            f"Full stats label should be 15px; got {sheet!r}"
        )
```

- [ ] **Step 4: Update `test_full_to_compact_roundtrip_restores_shared_widget_sizes` for 40px selector**

Change selector assertion from 44 to 40:

```python
    tab.set_layout_mode("full")
    # Full mutates: selector becomes 40, ka_bar fixed-size, name padding-right
    assert tab.set_selectors[0].maximumHeight() == 40
```

- [ ] **Step 5: Update `test_full_to_compact_roundtrip_restores_button_sizes` for 40px buttons**

Change Full-state assertion from 44 to 40:

```python
def test_full_to_compact_roundtrip_restores_button_sizes(tab):
    """After Full -> Compact, buttons must reset to Compact's creation defaults."""
    tab.set_layout_mode("full")
    assert tab.toon_buttons[0].maximumHeight() == 40
```

The Compact-restored assertions (32px) stay the same.

- [ ] **Step 6: Replace `test_full_card_portrait_scales_with_card` with fixed portrait test**

The old test checked dynamic portrait sizing. Replace with a test that verifies the portrait is fixed at 130x130:

```python
def test_full_card_portrait_fixed_size(qapp, tab):
    """Portrait must be fixed at 130x130 in Full UI, not dynamic."""
    tab.set_layout_mode("full")
    tab._full._cards[0].set_active(True)

    wrap = tab._full._cards[0]._portrait_wrap
    assert wrap.maximumWidth() == 130, (
        f"portrait wrap should be 130px wide; got {wrap.maximumWidth()}"
    )
    assert wrap.maximumHeight() == 130, (
        f"portrait wrap should be 130px tall; got {wrap.maximumHeight()}"
    )
    badge = tab.slot_badges[0]
    assert badge.maximumWidth() == 130 and badge.maximumHeight() == 130, (
        f"badge should be 130x130; got {badge.maximumSize()}"
    )
```

- [ ] **Step 7: Add test for content block max bounds**

```python
def test_full_card_content_block_bounded(qapp, tab):
    """_active_root must have max size of 500x240 and be centered."""
    tab.set_layout_mode("full")
    tab._full._cards[0].set_active(True)

    root = tab._full._cards[0]._active_root
    assert root.maximumWidth() == 500, (
        f"content block max width should be 500; got {root.maximumWidth()}"
    )
    assert root.maximumHeight() == 240, (
        f"content block max height should be 240; got {root.maximumHeight()}"
    )
```

- [ ] **Step 8: Run tests to verify they fail against current code**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: Multiple FAILs on the changed assertions (44 != 40, 26px != 22px, etc.). Tests that were not modified should still PASS.

- [ ] **Step 9: Commit**

```bash
git add tests/test_layout_reparent.py
git commit -m "test: update Full UI assertions for centered content block design"
```

---

### Task 2: Restructure `_FullToonCard` — manual positioning + fixed sizes

This is the core architectural change. Remove `_active_root` from `_stack_layout`, position it manually in `resizeEvent`, set fixed portrait size, and use proportional control sizes.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:81-341`

- [ ] **Step 1: Rewrite `_build_active_structure` — remove from stack, set max bounds**

Replace the current `_build_active_structure` method (lines 119-146) with:

```python
def _build_active_structure(self):
    # _active_root is NOT added to _stack_layout — it's manually
    # positioned in resizeEvent so it stays centered and bounded.
    self._active_root = QWidget(self)
    self._active_root.setMaximumSize(500, 240)
    root_vbox = QVBoxLayout(self._active_root)
    root_vbox.setContentsMargins(0, 0, 0, 0)
    root_vbox.setSpacing(10)

    # Content area: portrait (left) + info column (right)
    self._content_row = QHBoxLayout()
    self._content_row.setSpacing(16)

    self._portrait_wrap = QWidget()
    self._portrait_wrap.setFixedSize(130, 130)
    self._status_indicator = _StatusIndicator(self._portrait_wrap)
    self._status_indicator.move(100, 100)

    self._info_col = QVBoxLayout()
    self._info_col.setSpacing(4)

    self._content_row.addWidget(self._portrait_wrap)
    self._content_row.addLayout(self._info_col, 1)

    # Controls row
    self._ctrl_row = QHBoxLayout()
    self._ctrl_row.setSpacing(8)

    root_vbox.addLayout(self._content_row, 1)
    root_vbox.addLayout(self._ctrl_row, 0)
```

Key changes:
- `self._active_root` is created as `QWidget(self)` but NOT added to `_stack_layout`
- `setMaximumSize(500, 240)` caps the content block
- Portrait wrap is `setFixedSize(130, 130)`
- Status indicator is positioned at `(100, 100)` on the 130px portrait (bottom-right)
- Spacing tuned: 10px vertical between content and controls, 16px horizontal portrait-to-info

- [ ] **Step 2: Remove the `_stack_layout.addWidget(self._active_root)` line**

In `__init__`, the line `self._stack_layout.addWidget(self._active_root)` (currently line 146) must be removed — it's gone from `_build_active_structure` already. Also remove `self._last_portrait_size = 0` from `__init__` (line 111) since dynamic portrait sizing is gone.

- [ ] **Step 3: Rewrite `populate_active` — use 40px controls and 130px portrait**

Replace the current `populate_active` method (lines 149-207) with:

```python
def populate_active(self):
    """(Re-)attach the shared widgets into the active layout. Idempotent."""
    from tabs.multitoon._layout_utils import clear_layout

    clear_layout(self._info_col)
    clear_layout(self._ctrl_row)

    # Portrait — fixed 130x130
    portrait = self._tab.slot_badges[self._slot]
    portrait.setParent(self._portrait_wrap)
    portrait.setFixedSize(130, 130)
    portrait.move(0, 0)
    self._status_indicator.setParent(self._portrait_wrap)
    self._status_indicator.move(100, 100)

    # Info column: vertically centered name + stats
    name_label, _status_dot_compact = self._tab.toon_labels[self._slot]
    for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
        f = lbl.font()
        try:
            f.setFeature("tnum", 1)
        except Exception:
            f.setStyleHint(QFont.TypeWriter, QFont.PreferDefault)
        lbl.setFont(f)

    self._info_col.addStretch(1)
    self._info_col.addWidget(name_label)
    self._info_col.addWidget(self._tab.laff_labels[self._slot])
    self._info_col.addWidget(self._tab.bean_labels[self._slot])
    self._info_col.addStretch(1)

    # TTR/CC pill — parented to card frame, positioned in resizeEvent
    self._game_pill = self._tab.game_badges[self._slot]
    self._game_pill.setParent(self)
    self._game_pill.move(0, 0)

    # Controls row — 40px height, proportional widths
    btn = self._tab.toon_buttons[self._slot]
    _style_ctrl(btn, 40)
    btn.setFixedWidth(100)
    self._ctrl_row.addWidget(btn)

    chat = self._tab.chat_buttons[self._slot]
    _style_ctrl(chat, 40)
    chat.setFixedWidth(40)
    self._ctrl_row.addWidget(chat)

    ka = self._tab.keep_alive_buttons[self._slot]
    _style_ctrl(ka, 40)
    ka.setFixedWidth(40)
    self._ctrl_row.addWidget(ka)

    ka_bar = self._tab.ka_progress_bars[self._slot]
    ka_bar.setFixedSize(120, 10)
    self._ctrl_row.addWidget(ka_bar)
    self._ctrl_row.addStretch(1)

    selector = self._tab.set_selectors[self._slot]
    _style_ctrl(selector, 40)
    self._ctrl_row.addWidget(selector)
```

- [ ] **Step 4: Replace `resizeEvent` and remove `_resize_portrait`**

Delete the entire `_resize_portrait` method (lines 325-341). Replace `resizeEvent` (lines 317-323) with:

```python
def resizeEvent(self, event):
    super().resizeEvent(event)
    self._position_content()
    if self._is_active and self._game_pill is not None:
        root = self._active_root
        pill_w = self._game_pill.sizeHint().width()
        # Position relative to content block top-right
        pill_x = root.x() + root.width() - pill_w
        pill_y = root.y()
        self._game_pill.move(pill_x, pill_y)

def _position_content(self):
    """Center _active_root within the card's content area."""
    m = self._stack_layout.contentsMargins()
    avail_w = self.width() - m.left() - m.right()
    avail_h = self.height() - m.top() - m.bottom()
    # Content block: up to 500x240, centered
    block_w = min(500, avail_w)
    block_h = min(240, avail_h)
    x = m.left() + (avail_w - block_w) // 2
    y = m.top() + (avail_h - block_h) // 2
    self._active_root.setGeometry(x, y, block_w, block_h)
```

- [ ] **Step 5: Update `apply_theme` — 22px name, 15px stats**

In `apply_theme` (lines 284-315), change font sizes:
- Name label: `font-size: 26px` → `font-size: 22px`, `f.setPointSize(26)` → `f.setPointSize(22)`
- Stats labels: `font-size: 17px` → `font-size: 15px`

```python
def apply_theme(self, c: dict) -> None:
    self.setStyleSheet(
        f"#full_toon_card {{ background: {c['bg_card']}; "
        f"border: 1px solid {c['border_card']}; border-radius: 12px; }}"
    )
    self._status_indicator.apply_theme(
        c["bg_card"], c["status_dot_active"], c["status_dot_idle"]
    )
    if self._game_pill is not None:
        self._game_pill.setStyleSheet(
            f"background: {c['game_pill_ttr']}; color: {c['text_on_accent']}; "
            f"border-radius: 10px; padding: 3px 10px; "
            f"font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
        )
    name_label, _ = self._tab.toon_labels[self._slot]
    name_label.setStyleSheet(
        f"font-size: 22px; font-weight: 600; color: {c['text_primary']}; "
        f"background: transparent; border: none; padding-right: 60px;"
    )
    f = name_label.font()
    f.setPointSize(22)
    f.setWeight(QFont.DemiBold)
    name_label.setFont(f)
    for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
        lbl.setStyleSheet(
            f"border: none; background: transparent; font-weight: 600; "
            f"font-size: 15px; color: {c['text_primary']};"
        )
```

- [ ] **Step 6: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All tests PASS — the new code matches the updated assertions from Task 1.

- [ ] **Step 7: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "feat(layout): centered content block with fixed proportional sizes"
```

---

### Task 3: Update Compact resets for new Full sizes

When swapping Full → Compact, `_populate_card` must reset shared widgets from the new Full sizes (40px controls, 130px portrait, 120x10 ka_bar) back to Compact defaults.

**Files:**
- Modify: `tabs/multitoon/_compact_layout.py:145-186`

- [ ] **Step 1: Update the reset comment for new Full sizes**

In `_populate_card` (line 179), update the comment:
- Old: `# Buttons: Full sets 110×44 enable, 44×44 chat/KA`
- New: `# Buttons: Full sets 100×40 enable, 40×40 chat/KA`

No functional change — the reset lines already restore to 88x32 / 32x32 which is correct. The resets already handle the button/control sizes correctly (they restore Compact defaults regardless of what Full set). But confirm every reset path:

| Widget | Full sets | Compact restores to | Line |
|--------|----------|-------------------|------|
| `set_selectors[i]` | 40px height | 28px height | 150 |
| `slot_badges[i]` | 130x130 fixed | 38-64 min/max | 157-158 |
| `ka_progress_bars[i]` | 120x10 fixed | 40 minW, elastic maxW, 7px height | 166-168 |
| `toon_buttons[i]` | 100x40 | 88x32 | 181-182 |
| `chat_buttons[i]` | 40x40 | 32x32 | 183-184 |
| `keep_alive_buttons[i]` | 40x40 | 32x32 | 185-186 |
| `name_label` font | 22pt DemiBold | default QFont | 173-174 |

All resets are already correct — they restore to constructor defaults, not "the inverse of Full." Only the comment needs updating.

- [ ] **Step 2: Run roundtrip tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_to_compact_roundtrip_restores_shared_widget_sizes tests/test_layout_reparent.py::test_full_to_compact_roundtrip_restores_button_sizes tests/test_layout_reparent.py::test_compact_startup_uses_original_widget_sizes -v`

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tabs/multitoon/_compact_layout.py
git commit -m "fix(compact): update reset comment to match new Full control sizes"
```

---

### Task 4: Run full test suite and verify visually

**Files:** None (verification only)

- [ ] **Step 1: Run the full test file**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All 14 tests PASS (the renamed test changes the count name but not the total).

- [ ] **Step 2: Run the application for visual check**

Run: `cd /home/jaret/Projects/ToonTownMultiTool-v2 && python main.py`

Verify visually:
1. Full UI cards show a **centered content block** — not stretched to edges
2. Portrait is ~130px, text is proportional (22px name, 15px stats)
3. Controls are 40px tall at the bottom of the content block
4. On larger windows, excess space appears as padding around the content block
5. Game pill floats at the content block's top-right corner
6. Switching to Compact and back works without visual glitches
7. Inactive cards still show the "No game detected" placeholder centered

- [ ] **Step 3: Commit any fixups**

If visual check reveals minor issues, fix and commit with descriptive messages.
