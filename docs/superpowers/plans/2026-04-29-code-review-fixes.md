# Code Review Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 6 issues identified in the code review of Codex's Full UI absolute-positioning rewrite.

**Architecture:** Small, targeted fixes across 4 files. Each issue is independent. Tests first (TDD) where applicable, direct fix where not.

**Tech Stack:** PySide6/Qt, pytest with `QT_QPA_PLATFORM=offscreen`

---

### Task 1: Add icon size reset to Compact (Issue #1)

Full UI scales `iconSize` on chat/KA buttons (14px) and stat labels (16px) via `setIconSize()` in `_layout_active_content`. Compact never resets them, so switching from Full at non-1.0 scale leaves shrunken icons.

**Files:**
- Modify: `tabs/multitoon/_compact_layout.py:5,175-198`
- Modify: `tests/test_layout_reparent.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_layout_reparent.py` after the `test_full_to_compact_roundtrip_restores_button_sizes` test (after line 461):

```python
def test_full_to_compact_roundtrip_restores_icon_sizes(qapp, tab):
    """After Full at non-1.0 scale -> Compact, icon sizes must reset to defaults."""
    tab.set_layout_mode("full")
    card = tab._full._cards[0]
    card.set_active(True)
    card.resize(375, 214)
    qapp.processEvents()

    tab.set_layout_mode("compact")

    from PySide6.QtCore import QSize
    assert tab.chat_buttons[0].iconSize() == QSize(14, 14), (
        f"chat icon size should reset to 14x14; got {tab.chat_buttons[0].iconSize()}"
    )
    assert tab.keep_alive_buttons[0].iconSize() == QSize(14, 14), (
        f"KA icon size should reset to 14x14; got {tab.keep_alive_buttons[0].iconSize()}"
    )
    assert tab.laff_labels[0].iconSize() == QSize(16, 16), (
        f"laff icon size should reset to 16x16; got {tab.laff_labels[0].iconSize()}"
    )
    assert tab.bean_labels[0].iconSize() == QSize(16, 16), (
        f"bean icon size should reset to 16x16; got {tab.bean_labels[0].iconSize()}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_to_compact_roundtrip_restores_icon_sizes -v`

Expected: FAIL — icon sizes are still at the scaled Full values.

- [ ] **Step 3: Add icon size resets to `_compact_layout.py`**

In `tabs/multitoon/_compact_layout.py`, add `QSize` to the imports on line 5:

```python
from PySide6.QtCore import Qt, QSize
```

Then in `_populate_card`, after the button size resets (after line 198), add:

```python
        self._tab.chat_buttons[i].setIconSize(QSize(14, 14))
        self._tab.keep_alive_buttons[i].setIconSize(QSize(14, 14))
        self._tab.laff_labels[i].setIconSize(QSize(16, 16))
        self._tab.bean_labels[i].setIconSize(QSize(16, 16))
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_compact_layout.py tests/test_layout_reparent.py
git commit -m "fix(compact): reset icon sizes after Full UI roundtrip"
```

---

### Task 2: Fix font unit mismatch in name label (Issue #2)

`_apply_scaled_styles` sets `font-size: Npx` in the stylesheet but then calls `f.setPointSize(N)` with the same number. Points != pixels (~1.33px per pt at 96 DPI). The `setPointSize` call should be `setPixelSize` to match the stylesheet.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:465`

- [ ] **Step 1: Fix the font size call**

In `tabs/multitoon/_full_layout.py`, line 465, change:

```python
        f.setPointSize(max(1, round(self._REF_NAME_FONT * s)))
```

to:

```python
        f.setPixelSize(max(1, round(self._REF_NAME_FONT * s)))
```

- [ ] **Step 2: Run tests to verify nothing broke**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "fix(layout): use setPixelSize for name label to match stylesheet px units"
```

---

### Task 3: Remove dead `_make_ctrl_32` function (Issue #3)

`_make_ctrl_32` at `_full_layout.py:87-93` is never called in production. It exists only because `tests/test_layout_helper.py` imports and tests it. Remove both the function and its tests.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:87-93`
- Modify: `tests/test_layout_helper.py:61-80`

- [ ] **Step 1: Remove the function from `_full_layout.py`**

Delete lines 87-93 of `tabs/multitoon/_full_layout.py`:

```python
def _make_ctrl_32(widget: QWidget) -> QWidget:
    """Compatibility helper: force a control to Compact's 32px baseline."""
    widget.setFixedHeight(32)
    sheet = widget.styleSheet()
    if "border-radius" not in sheet:
        widget.setStyleSheet(sheet + "border-radius: 6px;")
    return widget
```

- [ ] **Step 2: Update `test_layout_helper.py`**

In `tests/test_layout_helper.py`, remove the `_make_ctrl_32` import from line 64 and the `callable` assertion from line 68. Then remove the entire `test_make_ctrl_32_sets_fixed_height_and_radius` function (lines 71-80).

The `test_full_layout_helper_imports_resolve` function should become:

```python
def test_full_layout_helper_imports_resolve(qapp):
    """Sanity: the new symbols added in Task 9 are importable."""
    from tabs.multitoon._full_layout import (
        _StatusIndicator, _FullToonCard
    )
    assert _StatusIndicator is not None
    assert _FullToonCard is not None
```

- [ ] **Step 3: Run all tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_helper.py tests/test_layout_reparent.py -v`

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py tests/test_layout_helper.py
git commit -m "refactor(layout): remove dead _make_ctrl_32 helper"
```

---

### Task 4: Eliminate double layout call on activation (Issue #4)

`set_active(True)` calls `_scale_content()` → `_layout_active_content()`, but `populate_active()` already calls `_layout_active_content(force=True)` right before `set_active` is called. This causes every card to layout twice during init and mode switches.

Fix: remove the `_scale_content()` call from `set_active()`. The `populate_active` → `_layout_active_content(force=True)` path is the canonical one. `resizeEvent` handles subsequent relayouts.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:278-290`

- [ ] **Step 1: Remove `_scale_content` call from `set_active`**

In `tabs/multitoon/_full_layout.py`, replace lines 278-290:

```python
    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._active_root.setVisible(active)
        self._inactive_root.setVisible(not active)
        if self._game_pill is not None:
            self._game_pill.setVisible(active)
        if active:
            if getattr(self._tab, "_mode", "compact") == "full":
                self._scale_content()
            self._status_indicator.set_active(True)
            self._start_pulse()
        else:
            self._stop_pulse()
```

with:

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

- [ ] **Step 2: Remove the now-unnecessary `_scale_content` wrapper**

Delete the `_scale_content` method at lines 381-382:

```python
    def _scale_content(self):
        self._layout_active_content()
```

- [ ] **Step 3: Run tests to verify nothing broke**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All tests PASS. The `_layout_active_content(force=True)` in `populate_active` and `resizeEvent` are the only callers needed.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "perf(layout): remove redundant layout pass from set_active"
```

---

### Task 5: Add clarifying comment for pill positioning flow (Issue #5)

The conditional flow between `_apply_game_pill_style` and `_position_game_pill` at lines 449-452 is non-obvious. Add a one-line comment.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:449-452`

- [ ] **Step 1: Add the comment**

In `tabs/multitoon/_full_layout.py`, replace lines 449-452:

```python
        self._apply_scaled_styles()
        self._apply_game_pill_style()
        if same_scale:
            self._position_game_pill()
```

with:

```python
        self._apply_scaled_styles()
        # _apply_game_pill_style repositions the pill when scale changes; when
        # only geometry changed (same_scale), reposition without restyling.
        self._apply_game_pill_style()
        if same_scale:
            self._position_game_pill()
```

- [ ] **Step 2: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "docs(layout): clarify pill positioning flow in _layout_active_content"
```

---

### Task 6: Replace regex stylesheet editing with direct approach (Issue #6)

`_scale_button_styles` uses `re.sub` on stylesheets to update `font-size`, which is fragile. Replace with clearing and re-setting the full font-size property, and drop the `import re`.

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:7,476-491`

- [ ] **Step 1: Rewrite `_scale_button_styles`**

In `tabs/multitoon/_full_layout.py`, replace lines 476-490:

```python
    def _scale_button_styles(self) -> None:
        font_px = max(10, round(self._REF_BUTTON_FONT * self._scale))
        for widget in (
            self._tab.toon_buttons[self._slot],
            self._tab.chat_buttons[self._slot],
            self._tab.keep_alive_buttons[self._slot],
        ):
            sheet = widget.styleSheet()
            if not sheet:
                continue
            if "font-size" in sheet:
                sheet = re.sub(r"font-size:\s*\d+px", f"font-size: {font_px}px", sheet)
            else:
                sheet += f"\nfont-size: {font_px}px;"
            widget.setStyleSheet(sheet)
```

with:

```python
    def _scale_button_styles(self) -> None:
        font_px = max(10, round(self._REF_BUTTON_FONT * self._scale))
        for widget in (
            self._tab.toon_buttons[self._slot],
            self._tab.chat_buttons[self._slot],
            self._tab.keep_alive_buttons[self._slot],
        ):
            f = widget.font()
            f.setPixelSize(font_px)
            widget.setFont(f)
```

- [ ] **Step 2: Remove `import re` from line 7**

Delete or remove `import re` from the top of the file (line 7). Verify no other code in the file uses `re`.

- [ ] **Step 3: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py tests/test_layout_helper.py -v`

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "refactor(layout): use QFont.setPixelSize instead of regex for button font scaling"
```

---

### Self-Review Checklist

1. **Review coverage:** All 6 issues from the code review are addressed (icon reset, font units, dead code, double layout, comment, regex).
2. **Placeholder scan:** No TBDs, TODOs, or vague steps. Every step has exact code.
3. **Type consistency:** `QSize` import added where needed. `setPixelSize` used consistently for px units. No new public API introduced.
