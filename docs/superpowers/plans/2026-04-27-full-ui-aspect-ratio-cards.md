# Full UI Aspect Ratio Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Do NOT add any `Co-Authored-By` line to commit messages.**

**Goal:** Replace the QGridLayout-based 2x2 card grid with manually-positioned 3:2 aspect ratio cards that cap at 600x400 and center as a group, with content that scales proportionally inside each card.

**Architecture:** `_FullLayout` manually positions 4 cards in a 2x2 arrangement within a grid container widget, enforcing 3:2 aspect ratio and 600x400 max. `_FullToonCard.resizeEvent` computes a scale factor from card height (reference 400px = scale 1.0) and resizes all internal elements proportionally. `QGridLayout` is removed entirely.

**Tech Stack:** PySide6 (QWidget, QFrame, QVBoxLayout/QHBoxLayout, manual geometry via `setGeometry`)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `tabs/multitoon/_full_layout.py` | Modify | Grid positioning + card content scaling |
| `tabs/multitoon/_compact_layout.py` | Modify | Update comments for dynamic Full sizes |
| `tests/test_layout_reparent.py` | Modify | Remove obsolete test, add new tests |

---

### Task 1: Add new tests and remove obsolete test

Before changing production code, update tests so new ones fail against current code.

**Files:**
- Modify: `tests/test_layout_reparent.py`

- [ ] **Step 1: Remove `test_full_card_content_block_bounded`**

Delete the entire test function (lines 347-358) — `_active_root` will no longer have max bounds:

```python
# DELETE this entire function:
def test_full_card_content_block_bounded(qapp, tab):
    """_active_root must have max size of 500x240 and be centered."""
    ...
```

- [ ] **Step 2: Add `test_full_grid_enforces_aspect_ratio`**

Add at the end of the file:

```python
def test_full_grid_enforces_aspect_ratio(qapp, tab):
    """Cards in the Full UI grid must maintain a 3:2 aspect ratio."""
    tab.set_layout_mode("full")
    tab._full.resize(1200, 800)
    qapp.processEvents()

    card = tab._full._cards[0]
    assert card.width() > 0 and card.height() > 0, "card must have real geometry"
    ratio = card.width() / card.height()
    assert abs(ratio - 1.5) < 0.1, (
        f"card aspect ratio should be ~1.5 (3:2); got {ratio:.2f}"
    )
```

- [ ] **Step 3: Add `test_full_grid_caps_at_max_size`**

Add at the end of the file:

```python
def test_full_grid_caps_at_max_size(qapp, tab):
    """Cards must not exceed 600x400 even on very large windows."""
    tab.set_layout_mode("full")
    tab._full.resize(2400, 1400)
    qapp.processEvents()

    card = tab._full._cards[0]
    assert card.width() <= 600, (
        f"card width should cap at 600; got {card.width()}"
    )
    assert card.height() <= 400, (
        f"card height should cap at 400; got {card.height()}"
    )
```

- [ ] **Step 4: Add `test_full_content_scales_with_card_size`**

Add at the end of the file:

```python
def test_full_content_scales_with_card_size(qapp, tab):
    """Content must scale proportionally when the card shrinks."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card.set_active(True)

    card.resize(600, 400)
    qapp.processEvents()
    portrait_full = tab.slot_badges[0].maximumHeight()
    assert portrait_full == 130, (
        f"portrait at scale 1.0 should be 130; got {portrait_full}"
    )

    card.resize(375, 250)
    qapp.processEvents()
    portrait_small = tab.slot_badges[0].maximumHeight()
    assert portrait_small < 130, (
        f"portrait should shrink below 130 at smaller card size; got {portrait_small}"
    )
    assert portrait_small >= 78, (
        f"portrait should not go below min scale (0.6 * 130 = 78); got {portrait_small}"
    )
```

- [ ] **Step 5: Run tests to verify state**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: The 3 new tests FAIL (no aspect ratio enforcement or scaling yet). All other tests PASS. The removed `test_full_card_content_block_bounded` should no longer appear.

- [ ] **Step 6: Commit**

```bash
git add tests/test_layout_reparent.py
git commit -m "test: add aspect ratio and scaling tests, remove obsolete content block test"
```

---

### Task 2: Replace QGridLayout with manual 3:2 grid positioning

Replace `QGridLayout` in `_FullLayout._build_structure` with a plain `QWidget` grid container. Position cards manually in `resizeEvent`.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py` — `_FullLayout` class (lines 341-431)

- [ ] **Step 1: Remove `QGridLayout` from imports**

Change the import line (line 10) from:

```python
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
)
```

to:

```python
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
)
```

- [ ] **Step 2: Rewrite `_FullLayout._build_structure` grid section**

Replace the grid section of `_build_structure` (the part starting at `# 2x2 grid of card shells` through the end of the method). Keep the service bar unchanged. Replace:

```python
        # 2x2 grid of card shells
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for i, (r, c) in enumerate(positions):
            card = _FullToonCard(i, self._tab)
            self._cards.append(card)
            grid.addWidget(card, r, c)
        outer.addLayout(grid, 1)
```

with:

```python
        # Grid container — cards are children, positioned manually in resizeEvent
        self._grid_container = QWidget()
        for i in range(4):
            card = _FullToonCard(i, self._tab, parent=self._grid_container)
            self._cards.append(card)
        outer.addWidget(self._grid_container, 1)
```

- [ ] **Step 3: Add `resizeEvent` and `_position_cards` to `_FullLayout`**

Add these methods to the `_FullLayout` class, after `_build_structure` and before `populate`:

```python
    _H_SPACING = 12
    _V_SPACING = 12
    _MAX_CARD_W = 600
    _MAX_CARD_H = 400

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout().activate()
        self._position_cards()

    def _position_cards(self):
        w = self._grid_container.width()
        h = self._grid_container.height()
        if w <= 0 or h <= 0:
            return

        card_w = (w - self._H_SPACING) / 2
        card_h = card_w / 1.5

        if card_h * 2 + self._V_SPACING > h:
            card_h = (h - self._V_SPACING) / 2
            card_w = card_h * 1.5

        card_w = int(min(card_w, self._MAX_CARD_W))
        card_h = int(min(card_h, self._MAX_CARD_H))

        grid_w = card_w * 2 + self._H_SPACING
        grid_h = card_h * 2 + self._V_SPACING
        ox = (w - grid_w) // 2
        oy = (h - grid_h) // 2

        positions = [
            (ox, oy),
            (ox + card_w + self._H_SPACING, oy),
            (ox, oy + card_h + self._V_SPACING),
            (ox + card_w + self._H_SPACING, oy + card_h + self._V_SPACING),
        ]
        for card, (x, y) in zip(self._cards, positions):
            card.setGeometry(x, y, card_w, card_h)
```

- [ ] **Step 4: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: `test_full_grid_enforces_aspect_ratio` and `test_full_grid_caps_at_max_size` now PASS. `test_full_content_scales_with_card_size` still FAILS (no scaling yet). All other tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "feat(layout): replace QGridLayout with manual 3:2 aspect ratio positioning"
```

---

### Task 3: Add proportional content scaling to `_FullToonCard`

Add `_scale_content` method that resizes all card elements based on a scale factor derived from card height. Put `_active_root` back in `_stack_layout`. Remove the manual content positioning.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py` — `_FullToonCard` class (lines 81-338)

- [ ] **Step 1: Add `_scale` and `_theme_colors` to `__init__`**

In `_FullToonCard.__init__` (line 90), add two new instance variables after `self._pulse_anim = None`:

```python
        self._scale = 1.0
        self._theme_colors = None
```

- [ ] **Step 2: Rewrite `_build_active_structure`**

Replace the current `_build_active_structure` method (lines 118-147) with:

```python
    def _build_active_structure(self):
        self._active_root = QWidget(self)
        root_vbox = QVBoxLayout(self._active_root)
        root_vbox.setContentsMargins(0, 0, 0, 0)
        root_vbox.setSpacing(10)

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

        self._ctrl_row = QHBoxLayout()
        self._ctrl_row.setSpacing(8)

        root_vbox.addLayout(self._content_row, 1)
        root_vbox.addLayout(self._ctrl_row, 0)

        self._stack_layout.addWidget(self._active_root)
```

Key changes from current:
- Removed `self._active_root.setMaximumSize(500, 240)`
- Added `self._stack_layout.addWidget(self._active_root)` at the end

- [ ] **Step 3: Rewrite `resizeEvent`, delete `_position_content`**

Replace the current `resizeEvent` and `_position_content` methods (lines 319-338) with:

```python
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._is_active:
            self._scale_content()
        if self._is_active and self._game_pill is not None:
            pw = self._game_pill.sizeHint().width()
            self._game_pill.move(self.width() - pw - 14, 14)
```

Delete `_position_content` entirely — it is replaced by `_scale_content`.

- [ ] **Step 4: Add `_MAX_CARD_H` class constant**

Add at the top of the `_FullToonCard` class body (after the docstring, before `__init__`):

```python
    _MAX_CARD_H = 400
```

- [ ] **Step 5: Add `_scale_content` method**

Add after the `resizeEvent` method:

```python
    def _scale_content(self):
        m = self._stack_layout.contentsMargins()
        content_h = self.height() - m.top() - m.bottom()
        if content_h <= 0:
            return
        ref_h = self._MAX_CARD_H - m.top() - m.bottom()
        scale = max(0.6, min(1.0, content_h / ref_h))
        if abs(scale - self._scale) < 0.01:
            return
        self._scale = scale

        ps = int(130 * scale)
        self._portrait_wrap.setFixedSize(ps, ps)
        self._tab.slot_badges[self._slot].setFixedSize(ps, ps)
        ind_offset = ps - 30
        self._status_indicator.move(ind_offset, ind_offset)

        bh = int(40 * scale)
        self._tab.toon_buttons[self._slot].setFixedHeight(bh)
        self._tab.toon_buttons[self._slot].setFixedWidth(int(100 * scale))
        self._tab.chat_buttons[self._slot].setFixedHeight(bh)
        self._tab.chat_buttons[self._slot].setFixedWidth(bh)
        self._tab.keep_alive_buttons[self._slot].setFixedHeight(bh)
        self._tab.keep_alive_buttons[self._slot].setFixedWidth(bh)

        self._tab.ka_progress_bars[self._slot].setFixedSize(
            int(120 * scale), max(4, int(10 * scale))
        )
        self._tab.set_selectors[self._slot].setFixedHeight(bh)

        self._active_root.layout().setSpacing(int(10 * scale))
        self._content_row.setSpacing(int(16 * scale))
        self._ctrl_row.setSpacing(int(8 * scale))

        self._apply_scaled_styles()
```

- [ ] **Step 6: Add `_apply_scaled_styles` method**

Add after `_scale_content`:

```python
    def _apply_scaled_styles(self):
        if self._theme_colors is None:
            return
        c = self._theme_colors
        s = self._scale
        name_label, _ = self._tab.toon_labels[self._slot]
        name_label.setStyleSheet(
            f"font-size: {int(22 * s)}px; font-weight: 600; color: {c['text_primary']}; "
            f"background: transparent; border: none; padding-right: 60px;"
        )
        f = name_label.font()
        f.setPointSize(int(22 * s))
        f.setWeight(QFont.DemiBold)
        name_label.setFont(f)
        for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
            lbl.setStyleSheet(
                f"border: none; background: transparent; font-weight: 600; "
                f"font-size: {int(15 * s)}px; color: {c['text_primary']};"
            )
```

- [ ] **Step 7: Modify `apply_theme` to store colors and delegate font styling**

Replace the current `apply_theme` method (lines 286-317) with:

```python
    def apply_theme(self, c: dict) -> None:
        self._theme_colors = c
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
        self._apply_scaled_styles()
```

- [ ] **Step 8: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: ALL tests pass, including the new `test_full_content_scales_with_card_size`.

- [ ] **Step 9: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "feat(layout): proportional content scaling based on card height"
```

---

### Task 4: Update compact reset comments

The compact resets themselves are correct (they restore constructor defaults regardless of what Full set). Only the comments referencing specific Full sizes need updating since Full now sets dynamic sizes.

**Files:**
- Modify: `tabs/multitoon/_compact_layout.py`

- [ ] **Step 1: Update comments in `_populate_card`**

In `_compact_layout.py`, update these comments:

Line 150 — change:
```python
        self._tab.set_selectors[i].setFixedHeight(28)  # Full sets 32; SetSelectorWidget defaults to 28
```
to:
```python
        self._tab.set_selectors[i].setFixedHeight(28)  # Full scales dynamically; SetSelectorWidget defaults to 28
```

Lines 152-153 — change:
```python
        # slot_badge: Full sets setFixedSize(104, 104); ToonPortraitWidget's
```
to:
```python
        # slot_badge: Full scales dynamically; ToonPortraitWidget's
```

Lines 160-161 — change:
```python
        # ka_bar: Full sets setFixedSize(90, 8); SmoothProgressBar's constructor
```
to:
```python
        # ka_bar: Full scales dynamically; SmoothProgressBar's constructor
```

Lines 179-180 — change:
```python
        # Buttons: Full sets 100×40 enable, 40×40 chat/KA; constructor defaults
        # are 88×32 enable, 32×32 chat/KA.
```
to:
```python
        # Buttons: Full scales dynamically; constructor defaults are
        # 88×32 enable, 32×32 chat/KA.
```

- [ ] **Step 2: Run roundtrip tests to verify resets still work**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_to_compact_roundtrip_restores_shared_widget_sizes tests/test_layout_reparent.py::test_full_to_compact_roundtrip_restores_button_sizes tests/test_layout_reparent.py::test_compact_startup_uses_original_widget_sizes -v`

Expected: All 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add tabs/multitoon/_compact_layout.py
git commit -m "fix(compact): update reset comments for dynamic Full scaling"
```

---

### Task 5: Full test suite and visual verification

**Files:** None (verification only)

- [ ] **Step 1: Run the full test file**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All tests PASS (count should be 17: 15 original minus 1 removed plus 3 added).

- [ ] **Step 2: Run the application for visual check**

Run: `cd /home/jaret/Projects/ToonTownMultiTool-v2 && python main.py`

Verify visually:
1. Full UI cards maintain 3:2 aspect ratio at all window sizes
2. At ~1280x800 (minimum Full UI), cards fill most of the grid area
3. At 1920x1080+, cards cap at 600x400 and the 2x2 grid centers
4. Content scales proportionally — portrait, text, and buttons all resize together
5. Switching to Compact and back works without visual glitches
6. Inactive cards ("No game detected") display correctly
7. Game pill stays at the card's top-right corner

- [ ] **Step 3: Commit any fixups**

If visual check reveals minor issues, fix and commit with descriptive messages.
