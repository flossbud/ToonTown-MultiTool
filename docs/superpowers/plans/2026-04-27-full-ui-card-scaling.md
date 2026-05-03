# Full UI Card Content Scaling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scale the Full UI toon card content (portrait, typography, controls) to match the mockup proportions, and fix the game pill clipping bug.

**Architecture:** The Full UI's `_FullToonCard` uses shared widgets from `MultitoonTab` that are created at compact-sized defaults. `populate_active()` and `apply_theme()` must override sizes for Full UI, and `_CompactLayout._populate_card()` must reset them when swapping back. The game pill's parent changes from `_active_root` to the card frame to fix coordinate-space clipping.

**Tech Stack:** PySide6 (QGridLayout, QFrame, QSizePolicy), Python

---

## File Map

- **Modify:** `tabs/multitoon/_full_layout.py` — portrait sizing, control sizing, typography, game pill parent, `_make_ctrl_32` → `_style_ctrl`
- **Modify:** `tabs/multitoon/_compact_layout.py` — add button size resets in `_populate_card`
- **Test:** `tests/test_layout_reparent.py` — update existing assertions, add new sizing/position tests

---

### Task 1: Fix game pill coordinate clipping

The game pill is parented to `_active_root` but positioned using `self.width()` (the card's full width). Since `_active_root` is 36px narrower (18px margins), the pill extends past its parent and gets clipped. Fix: parent the pill to the card (`self`) and manage visibility in `set_active()`.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:186-188` (populate_active, pill parent)
- Modify: `tabs/multitoon/_full_layout.py:247-250` (set_active, pill visibility)
- Test: `tests/test_layout_reparent.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_layout_reparent.py`:

```python
def test_game_pill_parented_to_card_not_active_root(tab):
    """The game pill must be a child of the card frame, not _active_root,
    so resizeEvent's self.width()-based positioning is in the right
    coordinate space."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    pill = card._game_pill
    assert pill is not None, "game_pill should be set after populate_active"
    assert pill.parent() is card, (
        f"game_pill should be parented to card, not {pill.parent().__class__.__name__}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_game_pill_parented_to_card_not_active_root -v`
Expected: FAIL — pill is currently parented to `_active_root`

- [ ] **Step 3: Implement fix**

In `tabs/multitoon/_full_layout.py`, change `populate_active()` pill parent (line 187):

```python
# Before:
self._game_pill.setParent(self._active_root)

# After:
self._game_pill.setParent(self)
```

In `set_active()` (line 247-250), add pill visibility management:

```python
def set_active(self, active: bool) -> None:
    self._is_active = active
    self._active_root.setVisible(active)
    self._inactive_root.setVisible(not active)
    if self._game_pill is not None:
        self._game_pill.setVisible(active)
    if active:
        self._status_indicator.set_active(True)
        self._start_pulse()
    else:
        self._stop_pulse()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_game_pill_parented_to_card_not_active_root -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add tabs/multitoon/_full_layout.py tests/test_layout_reparent.py
git commit -m "fix(multitoon): parent game pill to card frame to fix clipping"
```

---

### Task 2: Scale Full UI typography

Name label goes from 16px → 20px. Stats labels (LAFF/beans) get a Full UI override at 15px — currently they stay at compact's 13px because `apply_theme()` only overrides the name label.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:285-311` (apply_theme)
- Modify: `tests/test_layout_reparent.py:186-197` (update existing name test, add stats test)

- [ ] **Step 1: Write failing tests**

Update `test_full_name_label_styling_survives_refresh_theme` — change the expected font-size from `16px` to `20px`:

```python
def test_full_name_label_styling_survives_refresh_theme(tab):
    """Critical bug regression: refresh_theme must not wipe Full UI's name styling."""
    tab.set_layout_mode("full")
    tab.refresh_theme()

    name_label, _ = tab.toon_labels[0]
    sheet = name_label.styleSheet()
    assert "font-size: 20px" in sheet, f"Full name-label should be 20px; got {sheet!r}"
    assert "padding-right: 60px" in sheet, (
        f"Full name-label should reserve 60px for game pill; got {sheet!r}"
    )
```

Add new test for stats labels:

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

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_name_label_styling_survives_refresh_theme tests/test_layout_reparent.py::test_full_stats_labels_get_scaled_font -v`
Expected: Both FAIL — name is 16px, stats are 13px

- [ ] **Step 3: Update apply_theme**

In `tabs/multitoon/_full_layout.py`, update `apply_theme()`:

Change name label styling (lines 303-311):

```python
# Before:
name_label.setStyleSheet(
    f"font-size: 16px; font-weight: 600; color: {c['text_primary']}; "
    f"background: transparent; border: none; padding-right: 60px;"
)
f = name_label.font()
f.setPointSize(16)
f.setWeight(QFont.DemiBold)
name_label.setFont(f)

# After:
name_label.setStyleSheet(
    f"font-size: 20px; font-weight: 600; color: {c['text_primary']}; "
    f"background: transparent; border: none; padding-right: 60px;"
)
f = name_label.font()
f.setPointSize(20)
f.setWeight(QFont.DemiBold)
name_label.setFont(f)
```

Add stats label override after the name label block (after line 311):

```python
for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
    lbl.setStyleSheet(
        f"border: none; background: transparent; font-weight: 600; "
        f"font-size: 15px; color: {c['text_primary']};"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_name_label_styling_survives_refresh_theme tests/test_layout_reparent.py::test_full_stats_labels_get_scaled_font -v`
Expected: Both PASS

- [ ] **Step 5: Run full test suite**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tabs/multitoon/_full_layout.py tests/test_layout_reparent.py
git commit -m "fix(multitoon): scale Full UI name to 20px, stats to 15px"
```

---

### Task 3: Scale portrait, controls, and progress bar

Portrait wrapper 104→120px, status indicator repositioned. Controls row: buttons 32→40px tall, enable button 88→100px wide, icon buttons 32→40px square, progress bar 90×8→120×10. Rename `_make_ctrl_32` → `_style_ctrl` with height parameter.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:73-79` (`_make_ctrl_32` → `_style_ctrl`)
- Modify: `tabs/multitoon/_full_layout.py:136-140` (`_build_active_structure`, portrait + indicator)
- Modify: `tabs/multitoon/_full_layout.py:158-208` (`populate_active`, all sizes)
- Test: `tests/test_layout_reparent.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_layout_reparent.py`:

```python
def test_full_portrait_and_controls_scaled(tab):
    """Full UI portrait must be 120x120 and controls 40px tall."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]

    assert card._portrait_wrap.width() == 120, (
        f"portrait wrapper should be 120px wide; got {card._portrait_wrap.width()}"
    )
    assert card._portrait_wrap.height() == 120, (
        f"portrait wrapper should be 120px tall; got {card._portrait_wrap.height()}"
    )

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

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_portrait_and_controls_scaled -v`
Expected: FAIL — portrait is 104, buttons are 32, etc.

- [ ] **Step 3: Rename `_make_ctrl_32` → `_style_ctrl` with height parameter**

In `tabs/multitoon/_full_layout.py`, replace the function (lines 73-79):

```python
# Before:
def _make_ctrl_32(widget: QWidget) -> None:
    """Force a control to 32px tall + 6px corner radius — applied to every
    interactive item in the controls row so they share a baseline."""
    widget.setFixedHeight(32)
    sheet = widget.styleSheet()
    if "border-radius" not in sheet:
        widget.setStyleSheet(sheet + "border-radius: 6px;")

# After:
def _style_ctrl(widget: QWidget, height: int = 32) -> None:
    """Force a control to the given height + 6px corner radius."""
    widget.setFixedHeight(height)
    sheet = widget.styleSheet()
    if "border-radius" not in sheet:
        widget.setStyleSheet(sheet + "border-radius: 6px;")
```

- [ ] **Step 4: Update `_build_active_structure` — portrait 104→120, indicator (74,74)→(90,90)**

In `tabs/multitoon/_full_layout.py` (lines 137-140):

```python
# Before:
self._portrait_wrap = QWidget()
self._portrait_wrap.setFixedSize(104, 104)
self._status_indicator = _StatusIndicator(self._portrait_wrap)
self._status_indicator.move(74, 74)

# After:
self._portrait_wrap = QWidget()
self._portrait_wrap.setFixedSize(120, 120)
self._status_indicator = _StatusIndicator(self._portrait_wrap)
self._status_indicator.move(90, 90)
```

- [ ] **Step 5: Update `populate_active` — portrait, indicator, controls**

In `tabs/multitoon/_full_layout.py`, update portrait size in `populate_active` (line 160):

```python
# Before:
portrait.setFixedSize(104, 104)

# After:
portrait.setFixedSize(120, 120)
```

Update indicator position (line 165):

```python
# Before:
self._status_indicator.move(74, 74)

# After:
self._status_indicator.move(90, 90)
```

Replace the controls row block (lines 190-208) with:

```python
        # Controls row
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

- [ ] **Step 6: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_portrait_and_controls_scaled -v`
Expected: PASS

- [ ] **Step 7: Run full test suite**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`
Expected: All pass (existing tests that check compact sizes should still pass because compact resets run on startup)

- [ ] **Step 8: Commit**

```bash
git add tabs/multitoon/_full_layout.py tests/test_layout_reparent.py
git commit -m "fix(multitoon): scale Full UI portrait to 120px, controls to 40px"
```

---

### Task 4: Add Compact resets for new Full UI button sizes

When swapping from Full to Compact, `_populate_card` must reset button dimensions that `populate_active` changed (100×40 enable, 40×40 icon buttons) back to their creation defaults (88×32, 32×32).

**Files:**
- Modify: `tabs/multitoon/_compact_layout.py:145-178` (`_populate_card`)
- Test: `tests/test_layout_reparent.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_layout_reparent.py`:

```python
def test_full_to_compact_roundtrip_restores_button_sizes(tab):
    """After Full → Compact, buttons must reset to Compact's creation defaults."""
    tab.set_layout_mode("full")
    assert tab.toon_buttons[0].maximumHeight() == 40

    tab.set_layout_mode("compact")

    btn = tab.toon_buttons[0]
    assert btn.maximumHeight() == 32, (
        f"enable button height should reset to 32; got {btn.maximumHeight()}"
    )
    assert btn.maximumWidth() == 88, (
        f"enable button width should reset to 88; got {btn.maximumWidth()}"
    )

    chat = tab.chat_buttons[0]
    assert chat.maximumHeight() == 32, (
        f"chat button height should reset to 32; got {chat.maximumHeight()}"
    )
    assert chat.maximumWidth() == 32, (
        f"chat button width should reset to 32; got {chat.maximumWidth()}"
    )

    ka = tab.keep_alive_buttons[0]
    assert ka.maximumHeight() == 32, (
        f"KA button height should reset to 32; got {ka.maximumHeight()}"
    )
    assert ka.maximumWidth() == 32, (
        f"KA button width should reset to 32; got {ka.maximumWidth()}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_to_compact_roundtrip_restores_button_sizes -v`
Expected: FAIL — buttons stay at Full's 40px after swap

- [ ] **Step 3: Add button resets in `_populate_card`**

In `tabs/multitoon/_compact_layout.py`, add after the name_label reset block (after line 177, before the `# ── existing populate logic` comment):

```python
        self._tab.toon_buttons[i].setFixedHeight(32)
        self._tab.toon_buttons[i].setFixedWidth(88)
        self._tab.chat_buttons[i].setFixedHeight(32)
        self._tab.chat_buttons[i].setFixedWidth(32)
        self._tab.keep_alive_buttons[i].setFixedHeight(32)
        self._tab.keep_alive_buttons[i].setFixedWidth(32)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_to_compact_roundtrip_restores_button_sizes -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tabs/multitoon/_compact_layout.py tests/test_layout_reparent.py
git commit -m "fix(multitoon): reset button sizes when swapping Full → Compact"
```

---

### Task 5: Visual verification

Launch the app, switch to Full UI, and verify the card layout matches the mockup proportions.

- [ ] **Step 1: Run the app and compare**

Run: `python main.py`

Check:
- Portrait is visibly larger (~120px)
- Name text is large and bold (~20px)
- Stats (LAFF/beans) are clearly larger than compact
- Game pill (TTR/CC badge) sits in the top-right corner of the card, not clipped
- Bottom controls row has taller buttons (~40px), wider enable button
- Progress bar is wider and slightly taller
- Content packs at the top with empty space below (not vertically centered)

- [ ] **Step 2: Switch between Full and Compact to verify roundtrip**

Switch to Compact → verify buttons/portrait/text revert to compact sizes.
Switch back to Full → verify everything scales up again.
