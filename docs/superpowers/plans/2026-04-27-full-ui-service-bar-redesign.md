# Full UI Service Bar Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Full UI's inline service bar with a centered frameless control block, and change card aspect ratio from 16:10 to 7:4.

**Architecture:** The `_FullLayout._build_structure` replaces the QFrame-based service bar with a centered `QWidget` (max-width 960px) containing the toggle button, status bar, and profile pills stacked vertically. The config label moves inside the `_GridContainer` and is manually positioned by `_position_cards()` to left-align with the card grid. Aspect ratio constant changes from 1.6 to 1.75, max card width from 960 to 1050.

**Tech Stack:** PySide6/Qt6, Python 3, pytest with QT_QPA_PLATFORM=offscreen

---

### Task 1: Update test expectations for new aspect ratio and max size

**Files:**
- Modify: `tests/test_layout_reparent.py:347-373`

The two grid-geometry tests assert the old 16:10 ratio and 960px max width. Update them to expect 7:4 (1.75) and 1050px before changing the implementation, so they fail first.

- [ ] **Step 1: Update `test_full_grid_enforces_aspect_ratio` to expect 1.75**

In `tests/test_layout_reparent.py`, change the assertion on lines 356-358:

```python
def test_full_grid_enforces_aspect_ratio(qapp, tab):
    """Cards in the Full UI grid must maintain a 7:4 aspect ratio."""
    tab.set_layout_mode("full")
    tab._full.resize(1200, 800)
    qapp.processEvents()

    card = tab._full._cards[0]
    assert card.width() > 0 and card.height() > 0, "card must have real geometry"
    ratio = card.width() / card.height()
    assert abs(ratio - 1.75) < 0.1, (
        f"card aspect ratio should be ~1.75 (7:4); got {ratio:.2f}"
    )
```

- [ ] **Step 2: Update `test_full_grid_caps_at_max_size` to expect 1050**

In `tests/test_layout_reparent.py`, change the assertion on lines 368-369:

```python
def test_full_grid_caps_at_max_size(qapp, tab):
    """Cards must not exceed 1050x600 even on very large windows."""
    tab.set_layout_mode("full")
    tab._full.resize(3000, 2000)
    qapp.processEvents()

    card = tab._full._cards[0]
    assert card.width() <= 1050, (
        f"card width should cap at 1050; got {card.width()}"
    )
    assert card.height() <= 600, (
        f"card height should cap at 600; got {card.height()}"
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_grid_enforces_aspect_ratio tests/test_layout_reparent.py::test_full_grid_caps_at_max_size -v`

Expected: Both FAIL — the implementation still uses 1.6 and 960.

- [ ] **Step 4: Commit**

```bash
git add tests/test_layout_reparent.py
git commit -m "test: update grid geometry expectations for 7:4 aspect ratio and 1050px max"
```

---

### Task 2: Change aspect ratio and max card constants

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:385-389`

- [ ] **Step 1: Update the constants in `_FullLayout`**

In `tabs/multitoon/_full_layout.py`, change lines 385-389:

```python
    _H_SPACING = 12
    _V_SPACING = 12
    _ASPECT = 1.75  # 7:4
    _MAX_CARD_W = 1050
    _MAX_CARD_H = 600
```

- [ ] **Step 2: Run the two geometry tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_full_grid_enforces_aspect_ratio tests/test_layout_reparent.py::test_full_grid_caps_at_max_size -v`

Expected: Both PASS.

- [ ] **Step 3: Run the full test suite to check nothing else broke**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "feat(layout): change Full UI cards to 7:4 aspect ratio and 1050px max width"
```

---

### Task 3: Write test for config label reparenting

**Files:**
- Modify: `tests/test_layout_reparent.py`

The config label (`tab.config_label`) must be a descendant of `tab._full` when in full mode, and a descendant of `tab._compact` when in compact mode. This test will fail until Task 5 implements the new populate logic.

- [ ] **Step 1: Add test for config label reparenting**

Add after `test_swap_to_full_reparents_shared_widgets` (around line 120) in `tests/test_layout_reparent.py`:

```python
def test_config_label_reparented_to_full(tab):
    """Config label must be a descendant of _full in full mode."""
    tab.set_layout_mode("full")
    assert _is_descendant_of(tab.config_label, tab._full), (
        "config_label should be under _full in full mode"
    )
    assert not _is_descendant_of(tab.config_label, tab._compact), (
        "config_label should NOT be under _compact in full mode"
    )

    tab.set_layout_mode("compact")
    assert _is_descendant_of(tab.config_label, tab._compact), (
        "config_label should be under _compact after swap back"
    )
```

- [ ] **Step 2: Run test to verify it passes (config_label is already reparented by existing populate)**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_config_label_reparented_to_full -v`

Expected: PASS — the existing populate already reparents config_label via `addWidget`. If it fails, that's fine — Task 5 will fix it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_layout_reparent.py
git commit -m "test: add config label reparenting assertion for full/compact swap"
```

---

### Task 4: Rebuild `_FullLayout._build_structure` with centered controls

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:375-433`

Replace the `QFrame`-based service bar with a centered frameless control block. The config label becomes a child of `_grid_container`.

- [ ] **Step 1: Replace `_build_structure` and update cached layout references**

In `tabs/multitoon/_full_layout.py`, replace the `_FullLayout` class attributes and `__init__` + `_build_structure` (lines 375-433) with:

```python
class _FullLayout(QWidget):
    """Top-level Full UI: centered controls above a 2x2 toon card grid.

    Two-phase construction:
    - `_build_structure` builds the centered controls widget with empty slot
      layouts and four `_FullToonCard` shells inside a grid container.
    - `populate` clears the control slots + each card's active view, then
      re-adds the shared widgets in correct order.
    """

    _H_SPACING = 12
    _V_SPACING = 12
    _ASPECT = 1.75  # 7:4
    _MAX_CARD_W = 1050
    _MAX_CARD_H = 600

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._cards = []
        self._ctrl_layout = None
        self._pills_row = None
        self._build_structure()
        self.populate()

    def _build_structure(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(0)

        # Centered controls block — no frame, just a widget with max-width
        controls = QWidget()
        controls.setMaximumWidth(960)
        controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._ctrl_layout = QVBoxLayout(controls)
        self._ctrl_layout.setContentsMargins(0, 0, 0, 0)
        self._ctrl_layout.setSpacing(0)

        self._pills_row = QHBoxLayout()
        self._pills_row.setSpacing(6)

        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.addStretch(1)
        center_row.addWidget(controls, 100)
        center_row.addStretch(1)
        outer.addLayout(center_row)
        outer.addSpacing(16)

        # Grid container with manually positioned config label + cards
        layout_ref = self

        class _GridContainer(QWidget):
            def resizeEvent(self, ev):
                super().resizeEvent(ev)
                layout_ref._position_cards()

        self._grid_container = _GridContainer()
        for i in range(4):
            card = _FullToonCard(i, self._tab, parent=self._grid_container)
            self._cards.append(card)
        outer.addWidget(self._grid_container, 1)
```

- [ ] **Step 2: Remove the `QFrame` import if no longer needed**

Check if `QFrame` is still used elsewhere in the file. `_FullToonCard` extends `QFrame`, so the import stays. No change needed.

- [ ] **Step 3: Add `QLabel` to the import list if not already there**

`QLabel` is already imported on line 10. No change needed.

- [ ] **Step 4: Run tests — expect some failures since populate hasn't been updated yet**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v 2>&1 | tail -20`

Expected: Tests that touch service bar widgets may fail. Card tests should still pass since `_GridContainer` and `_FullToonCard` are unchanged.

- [ ] **Step 5: Commit (work in progress)**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "refactor(layout): replace Full UI service bar frame with centered controls block"
```

---

### Task 5: Rewrite `_FullLayout.populate` and `_position_cards`

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:450-515`

Update `populate()` to use the new `_ctrl_layout` and `_pills_row` slots, reparent config_label into the grid container, and update `_position_cards()` to account for the config label above the card grid.

- [ ] **Step 1: Replace `populate` method**

In `tabs/multitoon/_full_layout.py`, replace the `populate` method (currently lines 484-514) with:

```python
    def populate(self):
        """(Re-)attach shared widgets into the controls block and each card."""
        from tabs.multitoon._layout_utils import clear_layout

        # Controls block: toggle button → status bar → pills row
        clear_layout(self._ctrl_layout)
        clear_layout(self._pills_row)

        self._tab.toggle_service_button.setMinimumWidth(0)
        self._ctrl_layout.addWidget(self._tab.toggle_service_button)
        self._ctrl_layout.addSpacing(8)
        self._ctrl_layout.addWidget(self._tab.status_bar)
        self._ctrl_layout.addSpacing(12)

        self._pills_row.addStretch()
        for pill in self._tab.profile_pills:
            self._pills_row.addWidget(pill)
        self._pills_row.addSpacing(4)
        self._pills_row.addWidget(self._tab.refresh_button)
        self._pills_row.addStretch()
        self._ctrl_layout.addLayout(self._pills_row)

        # Config label — reparent into grid container, positioned manually
        self._tab.config_label.setParent(self._grid_container)
        self._tab.config_label.show()

        # Cards
        for card in self._cards:
            card.populate_active()
            card.set_active(card._is_active)
```

- [ ] **Step 2: Replace `_position_cards` to account for config label**

In `tabs/multitoon/_full_layout.py`, replace the `_position_cards` method (currently lines 450-482) with:

```python
    def _position_cards(self):
        self.layout().setGeometry(QRect(0, 0, self.width(), self.height()))
        w = self._grid_container.width()
        h = self._grid_container.height()
        if w <= 0 or h <= 0:
            return

        label_h = self._tab.config_label.sizeHint().height() if self._tab.config_label.text() else 0
        label_gap = 8 if label_h > 0 else 0
        avail_h = h - label_h - label_gap

        card_w = (w - self._H_SPACING) / 2
        card_h = card_w / self._ASPECT

        if card_h * 2 + self._V_SPACING > avail_h:
            card_h = (avail_h - self._V_SPACING) / 2
            card_w = card_h * self._ASPECT

        card_w = int(min(card_w, self._MAX_CARD_W))
        card_h = int(min(card_h, self._MAX_CARD_H))

        grid_w = card_w * 2 + self._H_SPACING
        grid_h = card_h * 2 + self._V_SPACING
        total_h = label_h + label_gap + grid_h
        ox = (w - grid_w) // 2
        oy = (h - total_h) // 2

        if label_h > 0:
            self._tab.config_label.setGeometry(ox, oy, grid_w, label_h)

        cards_oy = oy + label_h + label_gap
        positions = [
            (ox, cards_oy),
            (ox + card_w + self._H_SPACING, cards_oy),
            (ox, cards_oy + card_h + self._V_SPACING),
            (ox + card_w + self._H_SPACING, cards_oy + card_h + self._V_SPACING),
        ]
        for card, (x, y) in zip(self._cards, positions):
            card.setGeometry(x, y, card_w, card_h)
```

- [ ] **Step 3: Run the full test suite**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All tests PASS. The reparenting tests (`test_swap_to_full_reparents_shared_widgets`, etc.) should still pass because `toggle_service_button` is added to `_ctrl_layout` which is inside a `controls` QWidget which is inside the `_FullLayout` — so `_is_descendant_of(button, tab._full)` is still True.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "feat(layout): rewrite Full UI populate and position_cards for centered controls + config label"
```

---

### Task 6: Update `apply_theme` to remove service bar frame styling

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:522-525`

The old `apply_theme` set a stylesheet on all QWidgets with the app background. With no service bar QFrame, we should scope the background style more carefully to avoid it leaking into the controls wrapper.

- [ ] **Step 1: Update `apply_theme` in `_FullLayout`**

In `tabs/multitoon/_full_layout.py`, replace the `apply_theme` method:

```python
    def apply_theme(self, c: dict) -> None:
        self.setStyleSheet(
            f"_FullLayout {{ background: {c['bg_app']}; }}"
        )
        for card in self._cards:
            card.apply_theme(c)
```

Note: `_FullLayout` is not a named Qt object type — but `self.setStyleSheet` with a selector won't match child widgets. If this causes issues, use:

```python
    def apply_theme(self, c: dict) -> None:
        for card in self._cards:
            card.apply_theme(c)
```

The app background is already set by the parent. The service bar styling (`#full_service_bar`) was on the old QFrame and can be removed — there is no service bar frame anymore.

- [ ] **Step 2: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "fix(theme): remove service bar frame styling from Full UI apply_theme"
```

---

### Task 7: Verify Compact populate still handles config_label correctly

**Files:**
- Modify: `tabs/multitoon/_compact_layout.py` (if needed)

The Compact layout's `_build_structure` directly adds `_section_divider` and its `populate()` adds `config_label` to `_config_row`. Since Full's new populate reparents `config_label` into `_grid_container` (via `setParent`), Compact's `populate()` must reclaim it via `addWidget` which re-parents automatically. Verify this works.

- [ ] **Step 1: Run the roundtrip reparenting tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py::test_swap_back_to_compact_reparents_again tests/test_layout_reparent.py::test_config_label_reparented_to_full -v`

Expected: Both PASS. If `test_config_label_reparented_to_full` fails on the compact-swap-back assertion, the Compact `populate()` method at line 134 (`self._config_row.addWidget(self._tab.config_label)`) will need to also call `self._tab.config_label.show()` since Full's `setParent` to the grid container may not automatically make it visible when re-added to a layout.

- [ ] **Step 2: If the test fails, add `show()` call in Compact's populate**

In `tabs/multitoon/_compact_layout.py`, after line 134:

```python
        self._config_row.addWidget(self._tab.config_label)
        self._tab.config_label.show()
```

- [ ] **Step 3: Run full test suite**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_layout_reparent.py -v`

Expected: All PASS.

- [ ] **Step 4: Commit (only if changes were needed)**

```bash
git add tabs/multitoon/_compact_layout.py
git commit -m "fix(layout): ensure config_label is visible after compact re-populate"
```

---

### Task 8: Visual verification

**Files:**
- No code changes — manual testing only

- [ ] **Step 1: Launch the application**

Run: `python main.py`

- [ ] **Step 2: Resize window to trigger Full UI (>= 1280x800)**

Verify:
- Start/Stop button is centered, full-width within a ~960px block
- Status bar sits below the button (8px gap)
- Profile pill circles are centered below the status bar (12px gap)
- "TOON CONFIGURATION" label is left-aligned with the card grid
- Cards maintain 7:4 aspect ratio
- ~16px gap between pills and "TOON CONFIGURATION" label
- ~8px gap between label and card tops

- [ ] **Step 3: Maximize on a 1440p monitor (if available)**

Verify:
- Controls block doesn't stretch past ~960px — it centers
- Cards cap at ~1050x600 and center
- Clear visual separation between controls and card grid

- [ ] **Step 4: Resize back to compact (< 1280px wide)**

Verify:
- Compact UI renders correctly — config_label, pills, buttons all in the right place
- No visual artifacts from the Full→Compact widget reparenting

- [ ] **Step 5: Toggle back to Full UI**

Verify:
- Full UI renders correctly on the second swap
- All widgets are in the correct positions

- [ ] **Step 6: Commit any visual polish fixes discovered during testing**

```bash
git add -u
git commit -m "fix(layout): visual polish from manual testing"
```
