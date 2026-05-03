# Full UI Card Internals Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update in-card element sizes (portrait, name, controls) so they fill the 7:4 cards proportionally, matching the user's Photoshop mockup.

**Architecture:** All changes are to reference constants in `_FullToonCard` and the `_style_ctrl` helper. The existing `_scale_content` mechanism multiplies these refs by a scale factor derived from card height — no new scaling logic. Six tests need updated assertions to match the new ref values.

**Tech Stack:** PySide6/Qt, pytest with `QT_QPA_PLATFORM=offscreen`

---

### Task 1: Update test expectations (red)

**Files:**
- Modify: `tests/test_layout_reparent.py`

Update all test assertions to expect the new reference values. Tests will fail until the implementation matches.

- [ ] **Step 1: Update `test_full_card_portrait_fixed_size` (line 252)**

Change all `130` references to `150`:

```python
def test_full_card_portrait_fixed_size(qapp, tab):
    """Portrait must be fixed at 150x150 in Full UI, not dynamic."""
    tab.set_layout_mode("full")
    tab._full._cards[0].set_active(True)

    wrap = tab._full._cards[0]._portrait_wrap
    assert wrap.maximumWidth() == 150, (
        f"portrait wrap should be 150px wide; got {wrap.maximumWidth()}"
    )
    assert wrap.maximumHeight() == 150, (
        f"portrait wrap should be 150px tall; got {wrap.maximumHeight()}"
    )
    badge = tab.slot_badges[0]
    assert badge.maximumWidth() == 150 and badge.maximumHeight() == 150, (
        f"badge should be 150x150; got {badge.maximumSize()}"
    )
```

- [ ] **Step 2: Update `test_full_controls_scaled` (line 283)**

Change button heights to 42, chat width to 42, remove fixed ka_bar width assertion:

```python
def test_full_controls_scaled(tab):
    """Full UI controls must be 42px tall."""
    tab.set_layout_mode("full")

    btn = tab.toon_buttons[0]
    assert btn.maximumHeight() == 42, (
        f"enable button should be 42px tall; got max height {btn.maximumHeight()}"
    )
    assert btn.maximumWidth() == 100, (
        f"enable button should be 100px wide; got max width {btn.maximumWidth()}"
    )

    chat = tab.chat_buttons[0]
    assert chat.maximumHeight() == 42, (
        f"chat button should be 42px tall; got {chat.maximumHeight()}"
    )
    assert chat.maximumWidth() == 42, (
        f"chat button should be 42px wide; got {chat.maximumWidth()}"
    )

    ka_bar = tab.ka_progress_bars[0]
    assert ka_bar.maximumHeight() == 10, (
        f"ka progress bar should be 10px tall; got {ka_bar.maximumHeight()}"
    )
```

- [ ] **Step 3: Update `test_full_to_compact_roundtrip_restores_shared_widget_sizes` (line 157)**

Change the Full-mode selector assertion from 40 to 42:

```python
    tab.set_layout_mode("full")
    # Full mutates: selector becomes 42, ka_bar flex-fill, name padding-right
    assert tab.set_selectors[0].maximumHeight() == 42
```

- [ ] **Step 4: Update `test_full_to_compact_roundtrip_restores_button_sizes` (line 312)**

Change the Full-mode assertion from 40 to 42:

```python
    tab.set_layout_mode("full")
    assert tab.toon_buttons[0].maximumHeight() == 42
```

- [ ] **Step 5: Update `test_full_name_label_styling_survives_refresh_theme` (line 202)**

Change expected font-size from 22px to 28px:

```python
def test_full_name_label_styling_survives_refresh_theme(tab):
    """Critical bug regression: refresh_theme must not wipe Full UI's name styling."""
    tab.set_layout_mode("full")
    tab.refresh_theme()

    name_label, _ = tab.toon_labels[0]
    sheet = name_label.styleSheet()
    assert "font-size: 28px" in sheet, f"Full name-label should be 28px; got {sheet!r}"
    assert "padding-right: 60px" in sheet, (
        f"Full name-label should reserve 60px for game pill; got {sheet!r}"
    )
```

- [ ] **Step 6: Update `test_full_stats_labels_get_scaled_font` (line 216)**

Change expected font-size from 15px to 16px:

```python
def test_full_stats_labels_get_scaled_font(tab):
    """Stats labels (LAFF/beans) must get Full UI's 16px override, not
    compact's 13px, after refresh_theme + Full apply_theme."""
    tab.set_layout_mode("full")
    tab.refresh_theme()

    for label_list in (tab.laff_labels, tab.bean_labels):
        sheet = label_list[0].styleSheet()
        assert "font-size: 16px" in sheet, (
            f"Full stats label should be 16px; got {sheet!r}"
        )
```

- [ ] **Step 7: Update `test_full_content_scales_with_card_size` (line 392)**

Change portrait scale assertions from 130 to 150:

```python
def test_full_content_scales_with_card_size(qapp, tab):
    """Content must scale proportionally when the card shrinks."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card.set_active(True)

    card.resize(600, 400)
    qapp.processEvents()
    portrait_full = tab.slot_badges[0].maximumHeight()
    assert portrait_full == 150, (
        f"portrait at scale 1.0 should be 150; got {portrait_full}"
    )

    card.resize(375, 250)
    qapp.processEvents()
    portrait_small = tab.slot_badges[0].maximumHeight()
    assert portrait_small < 150, (
        f"portrait should shrink below 150 at smaller card size; got {portrait_small}"
    )
    assert portrait_small >= 90, (
        f"portrait should not go below min scale (0.6 * 150 = 90); got {portrait_small}"
    )
```

- [ ] **Step 8: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: 7 tests FAIL (the ones updated above). The remaining 11 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add tests/test_layout_reparent.py
git commit -m "test(layout): update card internals expectations for redesign"
```

---

### Task 2: Update `_style_ctrl` border-radius

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:73-78`

- [ ] **Step 1: Change border-radius from 6px to 8px**

```python
def _style_ctrl(widget: QWidget, height: int = 32) -> None:
    """Force a control to the given height + 8px corner radius."""
    widget.setFixedHeight(height)
    sheet = widget.styleSheet()
    if "border-radius" not in sheet:
        widget.setStyleSheet(sheet + "border-radius: 8px;")
```

- [ ] **Step 2: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "style(layout): bump Full UI control border-radius to 8px"
```

---

### Task 3: Update `_build_active_structure` reference sizes

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:122-148`

- [ ] **Step 1: Update portrait and content spacing refs**

```python
    def _build_active_structure(self):
        self._active_root = QWidget(self)
        root_vbox = QVBoxLayout(self._active_root)
        root_vbox.setContentsMargins(0, 0, 0, 0)
        root_vbox.setSpacing(10)

        self._content_row = QHBoxLayout()
        self._content_row.setSpacing(20)

        self._portrait_wrap = QWidget()
        self._portrait_wrap.setFixedSize(150, 150)
        self._status_indicator = _StatusIndicator(self._portrait_wrap)
        self._status_indicator.move(118, 118)

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

- [ ] **Step 2: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "feat(layout): increase Full UI portrait to 150px and content gap to 20px"
```

---

### Task 4: Update `populate_active` sizes and progress bar layout

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:151-210`

- [ ] **Step 1: Update portrait, buttons, and progress bar**

```python
    def populate_active(self):
        """(Re-)attach the shared widgets into the active layout. Idempotent."""
        from tabs.multitoon._layout_utils import clear_layout

        clear_layout(self._info_col)
        clear_layout(self._ctrl_row)

        # Portrait — fixed 150x150
        portrait = self._tab.slot_badges[self._slot]
        portrait.setParent(self._portrait_wrap)
        portrait.setFixedSize(150, 150)
        portrait.move(0, 0)
        self._status_indicator.setParent(self._portrait_wrap)
        self._status_indicator.move(118, 118)

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

        # Controls row — 42px height, proportional widths
        btn = self._tab.toon_buttons[self._slot]
        _style_ctrl(btn, 42)
        btn.setFixedWidth(100)
        self._ctrl_row.addWidget(btn)

        chat = self._tab.chat_buttons[self._slot]
        _style_ctrl(chat, 42)
        chat.setFixedWidth(42)
        self._ctrl_row.addWidget(chat)

        ka = self._tab.keep_alive_buttons[self._slot]
        _style_ctrl(ka, 42)
        ka.setFixedWidth(42)
        self._ctrl_row.addWidget(ka)

        ka_bar = self._tab.ka_progress_bars[self._slot]
        ka_bar.setFixedHeight(10)
        ka_bar.setMinimumWidth(40)
        self._ctrl_row.addWidget(ka_bar, 1)

        selector = self._tab.set_selectors[self._slot]
        _style_ctrl(selector, 42)
        self._ctrl_row.addWidget(selector)
```

- [ ] **Step 2: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "feat(layout): update populate_active with new ref sizes and flex-fill bar"
```

---

### Task 5: Update `_scale_content` and `_apply_scaled_styles`

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:318-372`

- [ ] **Step 1: Update `_scale_content` with new ref values**

```python
    def _scale_content(self):
        m = self._stack_layout.contentsMargins()
        content_h = self.height() - m.top() - m.bottom()
        if content_h <= 0:
            return
        ref_h = self._REF_H - m.top() - m.bottom()
        scale = max(0.6, min(1.5, content_h / ref_h))
        if abs(scale - self._scale) < 0.01:
            return
        self._scale = scale

        ps = int(150 * scale)
        self._portrait_wrap.setFixedSize(ps, ps)
        self._tab.slot_badges[self._slot].setFixedSize(ps, ps)
        ind_offset = ps - 32
        self._status_indicator.move(ind_offset, ind_offset)

        bh = int(42 * scale)
        self._tab.toon_buttons[self._slot].setFixedHeight(bh)
        self._tab.toon_buttons[self._slot].setFixedWidth(int(100 * scale))
        self._tab.chat_buttons[self._slot].setFixedHeight(bh)
        self._tab.chat_buttons[self._slot].setFixedWidth(bh)
        self._tab.keep_alive_buttons[self._slot].setFixedHeight(bh)
        self._tab.keep_alive_buttons[self._slot].setFixedWidth(bh)

        self._tab.ka_progress_bars[self._slot].setFixedHeight(max(4, int(10 * scale)))
        self._tab.set_selectors[self._slot].setFixedHeight(bh)

        self._active_root.layout().setSpacing(int(10 * scale))
        self._content_row.setSpacing(int(20 * scale))
        self._ctrl_row.setSpacing(int(8 * scale))

        self._apply_scaled_styles()
```

- [ ] **Step 2: Update `_apply_scaled_styles` with new font sizes and weight**

```python
    def _apply_scaled_styles(self):
        if self._theme_colors is None:
            return
        c = self._theme_colors
        s = self._scale
        name_label, _ = self._tab.toon_labels[self._slot]
        name_label.setStyleSheet(
            f"font-size: {int(28 * s)}px; font-weight: 700; color: {c['text_primary']}; "
            f"background: transparent; border: none; padding-right: 60px;"
        )
        f = name_label.font()
        f.setPointSize(int(28 * s))
        f.setWeight(QFont.Bold)
        name_label.setFont(f)
        for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
            lbl.setStyleSheet(
                f"border: none; background: transparent; font-weight: 600; "
                f"font-size: {int(16 * s)}px; color: {c['text_primary']};"
            )
```

- [ ] **Step 3: Run all tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All 18 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "feat(layout): update scale_content and styles with new card ref values"
```

---

### Task 6: Visual verification

**Files:** None (manual testing)

- [ ] **Step 1: Launch the app**

```bash
python main.py
```

- [ ] **Step 2: Verify Full UI card internals**

Check with a toon detected:
- Portrait is noticeably larger than before
- Name label is a bold heading (bigger, heavier)
- Stats (heart/jellybean) are slightly larger
- Progress bar fills the gap between KA button and Default selector (no dead space)
- Controls have slightly rounder corners (8px)
- All elements scale proportionally when resizing the window

- [ ] **Step 3: Verify Compact roundtrip**

Switch to Compact mode and back to Full — all elements should look correct in both modes.

- [ ] **Step 4: Verify at min and max window sizes**

Resize to minimum width — elements should scale down cleanly, nothing clips.
Maximize window — elements should scale up, portrait stays proportional, no overflow.
