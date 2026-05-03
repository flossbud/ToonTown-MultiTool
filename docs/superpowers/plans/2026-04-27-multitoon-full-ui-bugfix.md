# Multitoon Full UI Bugfix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two bugs found in the final review of the multitoon-full-ui branch — (1) Full UI renders empty because shared widgets never get re-attached when the layout swaps, (2) accent buttons in Compact UI and other tabs hardcode `color: white`, failing AA in dark mode where accents are now Tailwind 400-series. Plus one minor race fix in the cross-fade.

**Architecture:** Each layout class (`_CompactLayout`, `_FullLayout`, `_FullToonCard`) splits construction into `_build_structure()` (creates persistent QFrame/QLayout shells, caches references) + `populate()` (clears slot layouts via a `clear_layout` helper, re-adds shared widgets in the correct order). `MultitoonTab.set_layout_mode` calls the target's `populate()` before showing it. `color: white` callsites paired with `c['accent_*']` get replaced with `c['text_on_accent']`. `_set_layout_mode` updates `self._layout_mode` synchronously to avoid the cross-fade race.

**Tech Stack:** PySide6 6.5+, pytest with `QT_QPA_PLATFORM=offscreen` for the reparent regression test.

**Spec:** `docs/superpowers/specs/2026-04-26-multitoon-full-ui-design.md`

---

## File Structure

**Created:**
- `tabs/multitoon/_layout_utils.py` — `clear_layout(layout)` helper used by both Compact and Full populate logic.
- `tests/test_layout_reparent.py` — regression test that drives `set_layout_mode` and asserts shared widgets end up parented under the active layout.

**Modified:**
- `tabs/multitoon/_compact_layout.py` — split `_build` into `_build_structure` + `populate`; cache slot-layout references.
- `tabs/multitoon/_full_layout.py` — split `_FullToonCard._build_active_view` into `_build_active_structure` + `populate_active`; split `_FullLayout._build` into `_build_structure` + `populate` (real re-add, not just `set_active` toggle).
- `tabs/multitoon/_tab.py` — `set_layout_mode` calls `target.populate()`, plus initial-population trigger in `build_ui` so Compact wins the initial widget ownership. Replace `color: white` with `c['text_on_accent']` at lines 1170, 1217, 1267, 1282 (audit other lines too).
- `tabs/launch_tab.py`, `tabs/keymap_tab.py`, `tabs/invasions_tab.py`, `tabs/settings_tab.py` — same `color: white` → `c['text_on_accent']` replacements at the audited callsites.
- `main.py` — fix race in `_set_layout_mode` (synchronous mode update).

---

## Task 1: Add `clear_layout` helper

**Files:**
- Create: `tabs/multitoon/_layout_utils.py`
- Test: `tests/test_layout_helper.py` (extend)

The helper takes all items out of a `QLayout` without deleting the widgets they contain — widgets are shared and owned by the tab, so the layout just needs to release its references so subsequent `addWidget` calls don't create duplicate `QLayoutItem`s.

- [ ] **Step 1: Write the failing test**

Append to `/home/jaret/Projects/ToonTownMultiTool-v2/tests/test_layout_helper.py`:

```python
def test_clear_layout_removes_all_items(qapp):
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
    from tabs.multitoon._layout_utils import clear_layout

    parent = QWidget()
    layout = QHBoxLayout(parent)
    btn1 = QPushButton("a", parent=parent)
    btn2 = QPushButton("b", parent=parent)
    layout.addWidget(btn1)
    layout.addWidget(btn2)
    layout.addStretch()
    assert layout.count() == 3

    clear_layout(layout)
    assert layout.count() == 0


def test_clear_layout_does_not_destroy_widgets(qapp):
    """Widgets are owned externally and must survive the clear."""
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
    from tabs.multitoon._layout_utils import clear_layout

    parent = QWidget()
    layout = QHBoxLayout(parent)
    btn = QPushButton("x", parent=parent)
    layout.addWidget(btn)

    clear_layout(layout)
    # Widget still exists; just no parent layout.
    assert btn is not None
    btn.setText("still alive")
    assert btn.text() == "still alive"
```

- [ ] **Step 2: Run test to verify it fails**

```
cd /home/jaret/Projects/ToonTownMultiTool-v2 && pytest tests/test_layout_helper.py::test_clear_layout_removes_all_items -v
```

Expected: `ImportError` or `ModuleNotFoundError` for `tabs.multitoon._layout_utils`.

- [ ] **Step 3: Implement the helper**

Create `/home/jaret/Projects/ToonTownMultiTool-v2/tabs/multitoon/_layout_utils.py`:

```python
"""Small Qt layout helpers used by the Multitoon Compact/Full layout classes."""

from PySide6.QtWidgets import QLayout


def clear_layout(layout: QLayout) -> None:
    """Take every item out of `layout` without destroying the widgets.

    Used during a layout-mode swap: the new layout calls this on its slot
    sub-layouts before re-adding the shared widgets, so we don't accumulate
    stale `QLayoutItem`s referencing widgets that have been re-parented.
    Widgets themselves are owned by `MultitoonTab` (the shared-widgets pool)
    and must survive — only the layout's references are dropped.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            # Detach so a subsequent addWidget on this widget reparents cleanly.
            widget.setParent(None)
        # If the item is a sub-layout (not a widget), takeAt has already
        # removed it; the sub-layout itself isn't destroyed but is now orphan.
        # Callers re-add their sub-layouts by hand after clear.
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_layout_helper.py -v
```

Expected: 6 passed (4 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_layout_utils.py tests/test_layout_helper.py
git commit -m "feat(multitoon): add clear_layout helper for re-populating shared widgets"
```

---

## Task 2: Refactor `_CompactLayout` — split into structure + populate

**Files:**
- Modify: `tabs/multitoon/_compact_layout.py` (full rewrite — same external API, internal split)

The current `_build` does both: creates the QFrame/QLayout shells AND calls `addWidget` on shared widgets. We split this into:
- `_build_structure()` — creates the cards (4 `QFrame`s) and their sub-layouts (`top_row`, `stats_row`, `ctrl_row`, `ka_group_layout`); caches references in `self._slots`.
- `populate()` — clears each slot via `clear_layout`, then re-adds the shared widgets in correct order.

`__init__` calls both. `set_layout_mode` (Task 5) calls only `populate()` on subsequent swaps.

- [ ] **Step 1: Replace the file body**

Replace the entire contents of `/home/jaret/Projects/ToonTownMultiTool-v2/tabs/multitoon/_compact_layout.py` with:

```python
"""Compact UI layout for the Multitoon tab — the layout that ships at default
window size. Below the Full UI breakpoint, the outer card clamps to 720 px and
centers horizontally so wider windows do not stretch it."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame

from tabs.multitoon._layout_utils import clear_layout


class _CompactLayout(QWidget):
    """Reproduces the default Multitoon layout. Two-phase construction:

    - `_build_structure` creates the persistent QFrame/QLayout tree.
    - `populate` (re-)adds the shared per-slot widgets into the cached slots.
    """

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        # Cached references to slot sub-layouts (populated in _build_structure)
        self._service_layout = None
        self._config_row = None
        self._card_slots = []  # list of dicts per card with sub-layout refs
        self._build_structure()
        self.populate()

    # ── Structure ──────────────────────────────────────────────────────────
    def _build_structure(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 12, 16, 12)
        outer_layout.setSpacing(0)

        outer_card = QFrame()
        outer_card.setMaximumWidth(720)
        self._tab.outer_card = outer_card
        card_layout = QVBoxLayout(outer_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(10)

        # Service controls slot — empty until populate()
        self._service_layout = QVBoxLayout()
        self._service_layout.setContentsMargins(0, 0, 0, 0)
        self._service_layout.setSpacing(6)
        card_layout.addLayout(self._service_layout)

        # Section divider (no shared widgets — added directly here)
        card_layout.addSpacing(6)
        card_layout.addWidget(self._tab._section_divider, alignment=Qt.AlignHCenter)
        card_layout.addSpacing(6)

        # Config row slot — empty until populate()
        self._config_row = QHBoxLayout()
        self._config_row.setSpacing(6)
        card_layout.addLayout(self._config_row)

        # Per-slot toon cards (4 frames, each with empty sub-layouts)
        for i in range(4):
            card_layout.addWidget(self._build_card_structure(i))

        card_layout.addStretch()
        outer_layout.addWidget(outer_card, alignment=Qt.AlignHCenter)
        outer_layout.addStretch()

    def _build_card_structure(self, i: int) -> QFrame:
        """Build the persistent QFrame + sub-layouts for one card slot.
        Sub-layouts stay empty until populate() runs."""
        card = QFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(4)
        stats_row.setContentsMargins(0, 0, 0, 0)

        layout.addLayout(top_row)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        ka_group = QFrame()
        ka_group.setObjectName("ka_group")
        ka_group_layout = QHBoxLayout(ka_group)
        ka_group_layout.setContentsMargins(4, 4, 6, 4)
        ka_group_layout.setSpacing(4)

        layout.addLayout(ctrl_row)

        # Cache slot refs for populate()
        self._card_slots.append({
            "card": card,
            "top_row": top_row,
            "stats_row": stats_row,
            "ctrl_row": ctrl_row,
            "ka_group": ka_group,
            "ka_group_layout": ka_group_layout,
        })
        self._tab.toon_cards.append(card)
        self._tab.ka_groups.append(ka_group)
        return card

    # ── Populate ───────────────────────────────────────────────────────────
    def populate(self):
        """Clear slot layouts and re-add shared widgets in the correct order.
        Idempotent: safe to call after a layout-mode swap or theme refresh."""
        # Service controls
        clear_layout(self._service_layout)
        self._service_layout.addWidget(self._tab.toggle_service_button)
        self._service_layout.addWidget(self._tab.status_bar)

        # Config row
        clear_layout(self._config_row)
        self._config_row.addWidget(self._tab.config_label)
        self._config_row.addStretch()
        for pill in self._tab.profile_pills:
            self._config_row.addWidget(pill)
        self._config_row.addSpacing(4)
        self._config_row.addWidget(self._tab.refresh_button)

        # Each card slot
        for i, slot in enumerate(self._card_slots):
            self._populate_card(i, slot)

    def _populate_card(self, i: int, slot: dict):
        # top_row: badge | name | status_dot | game_badge | <stretch> | stats_row(laff bean)
        clear_layout(slot["top_row"])
        clear_layout(slot["stats_row"])
        slot["top_row"].addWidget(self._tab.slot_badges[i])
        name_label, status_dot = self._tab.toon_labels[i]
        slot["top_row"].addWidget(name_label)
        slot["top_row"].addWidget(status_dot)
        slot["top_row"].addWidget(self._tab.game_badges[i])
        slot["top_row"].addStretch()
        slot["stats_row"].addWidget(self._tab.laff_labels[i])
        slot["stats_row"].addWidget(self._tab.bean_labels[i])
        slot["top_row"].addLayout(slot["stats_row"])

        # ctrl_row: toon_button | ka_group(chat ka_btn ka_bar) | set_selector
        clear_layout(slot["ctrl_row"])
        clear_layout(slot["ka_group_layout"])
        slot["ctrl_row"].addWidget(self._tab.toon_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.chat_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.keep_alive_buttons[i])
        slot["ka_group_layout"].addWidget(self._tab.ka_progress_bars[i], 1)
        slot["ctrl_row"].addWidget(slot["ka_group"], 1)
        slot["ctrl_row"].addWidget(self._tab.set_selectors[i])
```

- [ ] **Step 2: Run all tests**

```
cd /home/jaret/Projects/ToonTownMultiTool-v2 && pytest tests/ -v
```

Expected: all tests still pass (70). The Compact UI behaves the same — `_build_structure` + `populate` together produce the exact same layout as the old monolithic `_build`.

- [ ] **Step 3: Manual import smoke test**

```
python -c "from tabs.multitoon_tab import MultitoonTab; t = MultitoonTab(); print('compact:', t._compact is not None, 'cards:', len(t._compact._card_slots), 'tab cards:', len(t.toon_cards))"
```

Expected: `compact: True cards: 4 tab cards: 4`.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_compact_layout.py
git commit -m "refactor(multitoon): split _CompactLayout into structure + populate phases"
```

---

## Task 3: Refactor `_FullToonCard` — split active view into structure + populate

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:82-265` (just the `_FullToonCard` class — `_StatusIndicator` and `_make_ctrl_32` stay untouched; `_FullLayout` updates in Task 4)

`_build_active_view` mixes structure (creating `portrait_wrap`, `_active_root`, the grid, `ctrl_row`) with widget-attach (calling `setParent` on the portrait/game_pill, `addWidget` on the name/stats/buttons). Split into `_build_active_structure` (caches `_active_grid`, `_ctrl_row`, `_portrait_wrap`) and `populate_active` (clears slots, re-attaches shared widgets).

The inactive view has no shared widgets — no populate logic needed.

- [ ] **Step 1: Replace the `_FullToonCard` class body**

In `/home/jaret/Projects/ToonTownMultiTool-v2/tabs/multitoon/_full_layout.py`, find `class _FullToonCard(QFrame):` (line 82) and replace it through the end of `resizeEvent` (line 265) with:

```python
class _FullToonCard(QFrame):
    """One toon's card in the Full UI. Active and inactive states share the
    outer frame; the inner content swaps based on whether a window was found.

    Two-phase construction (active view): `_build_active_structure` creates the
    grid + ctrl_row shells; `populate_active` re-attaches shared widgets so we
    can rebuild after a layout-mode swap stole them.
    """

    def __init__(self, slot_index: int, tab, parent=None):
        super().__init__(parent)
        self._slot = slot_index
        self._tab = tab
        self._is_active = False

        self.setObjectName("full_toon_card")
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._stack_layout = QVBoxLayout(self)
        self._stack_layout.setContentsMargins(18, 18, 18, 18)
        self._stack_layout.setSpacing(0)

        # Cached refs for populate_active()
        self._active_grid = None
        self._ctrl_row = None
        self._portrait_wrap = None
        self._status_indicator = None
        self._game_pill = None  # set on first populate_active

        self._build_active_structure()
        self._build_inactive_view()
        self.populate_active()
        self.set_active(False)

    # ── Active view structure ──────────────────────────────────────────────
    def _build_active_structure(self):
        self._active_root = QWidget(self)
        grid = QGridLayout(self._active_root)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        self._active_grid = grid

        # Portrait wrapper (104x104) — static container; the portrait widget itself
        # is a shared widget reattached in populate_active.
        self._portrait_wrap = QWidget()
        self._portrait_wrap.setFixedSize(104, 104)
        self._status_indicator = _StatusIndicator(self._portrait_wrap)
        self._status_indicator.move(74, 74)  # bottom-right inset

        # Empty ctrl_row sub-layout — re-filled by populate_active()
        self._ctrl_row = QHBoxLayout()
        self._ctrl_row.setSpacing(8)

        self._stack_layout.addWidget(self._active_root)

    # ── Active view populate ───────────────────────────────────────────────
    def populate_active(self):
        """(Re-)attach the shared widgets into the active grid. Idempotent."""
        from tabs.multitoon._layout_utils import clear_layout

        # Clear the grid and ctrl_row of any prior shared widgets
        clear_layout(self._active_grid)
        clear_layout(self._ctrl_row)

        # Portrait + status indicator (column 0, rows 0-2)
        portrait = self._tab.slot_badges[self._slot]
        portrait.setParent(self._portrait_wrap)
        portrait.setFixedSize(104, 104)
        portrait.move(0, 0)
        # Re-parent status_indicator too (it's a child of portrait_wrap, which
        # was re-parented to None when clear_layout ran on the grid).
        self._status_indicator.setParent(self._portrait_wrap)
        self._status_indicator.move(74, 74)
        self._active_grid.addWidget(self._portrait_wrap, 0, 0, 3, 1, alignment=Qt.AlignTop)

        # Name label (col 1, row 0)
        name_label, _status_dot_compact = self._tab.toon_labels[self._slot]
        name_font = name_label.font()
        name_font.setPointSize(16)
        name_font.setWeight(QFont.DemiBold)
        name_label.setFont(name_font)
        name_label.setStyleSheet(name_label.styleSheet() + "padding-right: 60px;")
        self._active_grid.addWidget(name_label, 0, 1, alignment=Qt.AlignBottom)

        # Stats with tabular nums (col 1, rows 1 & 2)
        for lbl in (self._tab.laff_labels[self._slot], self._tab.bean_labels[self._slot]):
            f = lbl.font()
            try:
                f.setFeature("tnum", 1)  # PySide6 6.5+
            except Exception:
                f.setStyleHint(QFont.TypeWriter, QFont.PreferDefault)
            lbl.setFont(f)
        self._active_grid.addWidget(self._tab.laff_labels[self._slot], 1, 1, alignment=Qt.AlignLeft)
        self._active_grid.addWidget(self._tab.bean_labels[self._slot], 2, 1, alignment=Qt.AlignLeft)

        # TTR/CC pill (top-right absolute via overlay — re-parents to active_root)
        self._game_pill = self._tab.game_badges[self._slot]
        self._game_pill.setParent(self._active_root)
        self._game_pill.move(0, 0)  # repositioned in resizeEvent

        # Controls row
        for w in (
            self._tab.toon_buttons[self._slot],
            self._tab.chat_buttons[self._slot],
            self._tab.keep_alive_buttons[self._slot],
        ):
            _make_ctrl_32(w)
        self._ctrl_row.addWidget(self._tab.toon_buttons[self._slot])
        self._ctrl_row.addWidget(self._tab.chat_buttons[self._slot])
        self._ctrl_row.addWidget(self._tab.keep_alive_buttons[self._slot])

        ka_bar = self._tab.ka_progress_bars[self._slot]
        ka_bar.setFixedSize(90, 8)
        self._ctrl_row.addWidget(ka_bar)
        self._ctrl_row.addStretch(1)

        selector = self._tab.set_selectors[self._slot]
        _make_ctrl_32(selector)
        self._ctrl_row.addWidget(selector)

        self._active_grid.addLayout(self._ctrl_row, 3, 0, 1, 2)

    # ── Inactive view ──────────────────────────────────────────────────────
    def _build_inactive_view(self):
        self._inactive_root = QWidget(self)
        v = QVBoxLayout(self._inactive_root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        slot_label = QLabel(f"Toon {self._slot + 1}")
        slot_label.setObjectName("full_slot_label")
        slot_font = slot_label.font()
        slot_font.setPointSize(11)
        slot_font.setWeight(QFont.DemiBold)
        slot_label.setFont(slot_font)
        v.addWidget(slot_label, alignment=Qt.AlignTop | Qt.AlignLeft)

        empty_area = QWidget()
        ev = QVBoxLayout(empty_area)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(6)
        ev.addStretch()
        icon = QLabel("·")
        icon.setObjectName("full_empty_icon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(32, 32)
        ev.addWidget(icon, alignment=Qt.AlignHCenter)
        msg = QLabel("No game detected")
        msg.setObjectName("full_empty_msg")
        msg.setAlignment(Qt.AlignCenter)
        ev.addWidget(msg, alignment=Qt.AlignHCenter)
        ev.addStretch()
        v.addWidget(empty_area, 1)

        self._stack_layout.addWidget(self._inactive_root)

    # ── State ──────────────────────────────────────────────────────────────
    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._active_root.setVisible(active)
        self._inactive_root.setVisible(not active)
        if active:
            self._status_indicator.set_active(True)
            self._start_pulse()
        else:
            self._stop_pulse()

    def _start_pulse(self) -> None:
        if getattr(self, "_pulse_anim", None) is not None:
            return
        sm = getattr(self._tab, "settings_manager", None)
        if sm and sm.get("disable_animations", False):
            return
        self._pulse_anim = QPropertyAnimation(self._status_indicator, b"glow")
        self._pulse_anim.setDuration(1500)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setKeyValueAt(0.5, 1.0)
        self._pulse_anim.setEndValue(0.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.start()

    def _stop_pulse(self) -> None:
        anim = getattr(self, "_pulse_anim", None)
        if anim is not None:
            anim.stop()
            self._pulse_anim = None
        self._status_indicator._set_glow(0.0)

    def apply_theme(self, c: dict) -> None:
        self.setStyleSheet(
            f"#full_toon_card {{ background: {c['bg_card']}; "
            f"border: 1px solid {c['border_card']}; border-radius: 12px; }}"
        )
        self._status_indicator.apply_theme(
            c["bg_card"], c["status_dot_active"], c["status_dot_idle"]
        )
        # text_on_accent (Material 3 onPrimary): white on light, slate-900 on dark
        if self._game_pill is not None:
            self._game_pill.setStyleSheet(
                f"background: {c['game_pill_ttr']}; color: {c['text_on_accent']}; "
                f"border-radius: 10px; padding: 3px 10px; "
                f"font-size: 10px; font-weight: 700; letter-spacing: 0.5px;"
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._is_active and self._game_pill is not None:
            pw = self._game_pill.sizeHint().width()
            self._game_pill.move(self.width() - pw - 14, 14)
```

- [ ] **Step 2: Run tests**

```
cd /home/jaret/Projects/ToonTownMultiTool-v2 && pytest tests/ -v
```

Expected: 70/70 still pass (no test changes; this is a refactor).

- [ ] **Step 3: Smoke import**

```
python -c "from tabs.multitoon._full_layout import _FullToonCard; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "refactor(multitoon): split _FullToonCard active view into structure + populate"
```

---

## Task 4: Refactor `_FullLayout` — real populate that re-adds widgets

**Files:**
- Modify: `tabs/multitoon/_full_layout.py:268-329` (the `_FullLayout` class)

The current `populate()` only calls `card.set_active(card._is_active)` — it doesn't re-add the toggle button, profile pills, refresh button, or status_bar (which live in the service bar's row layout). And it doesn't tell the cards to re-attach their shared widgets. Replace with a real implementation.

- [ ] **Step 1: Replace the `_FullLayout` class**

Find `class _FullLayout(QWidget):` in `/home/jaret/Projects/ToonTownMultiTool-v2/tabs/multitoon/_full_layout.py` and replace through end-of-file with:

```python
class _FullLayout(QWidget):
    """Top-level Full UI: service bar above a 2x2 toon card grid.

    Two-phase construction:
    - `_build_structure` builds the service-bar QFrame with empty row/sb layouts
      and four `_FullToonCard` shells.
    - `populate` clears the service-bar slots + each card's active view, then
      re-adds the shared widgets in correct order.
    """

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._cards = []
        self._service_row = None  # the QHBoxLayout inside service_bar
        self._service_sb_layout = None  # the QVBoxLayout that holds service_row + status_bar
        self._build_structure()
        self.populate()

    def _build_structure(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)

        # Service bar shell — empty layouts cached for populate()
        service_bar = QFrame()
        service_bar.setObjectName("full_service_bar")
        self._service_sb_layout = QVBoxLayout(service_bar)
        self._service_sb_layout.setContentsMargins(24, 18, 24, 18)
        self._service_sb_layout.setSpacing(10)

        self._service_row = QHBoxLayout()
        self._service_row.setSpacing(16)
        self._service_sb_layout.addLayout(self._service_row)

        outer.addWidget(service_bar)

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

    def populate(self):
        """(Re-)attach shared widgets into the service bar and each card."""
        from tabs.multitoon._layout_utils import clear_layout

        # Service-bar row: toggle | <stretch> | pills | spacing | refresh
        clear_layout(self._service_row)
        # status_bar lives in the parent QVBoxLayout — clear that down to just
        # the service_row, then re-add status_bar.
        # The QVBoxLayout has 2 items: [service_row (layout), status_bar (widget)].
        # We don't clear the layout-item for service_row (it's our own row).
        # Instead, take items after the row and re-add status_bar.
        # Simpler approach: clear everything and re-add row + status_bar.
        # But that would re-parent service_row away from its parent — it stays
        # the same layout object so addLayout works fine.
        # Safer: just iterate and remove only the status_bar widget item.
        for idx in range(self._service_sb_layout.count() - 1, -1, -1):
            item = self._service_sb_layout.itemAt(idx)
            w = item.widget()
            if w is self._tab.status_bar:
                self._service_sb_layout.takeAt(idx)
                w.setParent(None)

        self._tab.toggle_service_button.setMinimumWidth(180)
        self._service_row.addWidget(self._tab.toggle_service_button)
        self._service_row.addStretch()
        for pill in self._tab.profile_pills:
            self._service_row.addWidget(pill)
        self._service_row.addSpacing(8)
        self._service_row.addWidget(self._tab.refresh_button)
        self._service_sb_layout.addWidget(self._tab.status_bar)

        # Cards
        for card in self._cards:
            card.populate_active()
            # set_active forces visibility + pulse to match current state
            card.set_active(card._is_active)

    def apply_theme(self, c: dict) -> None:
        self.setStyleSheet(f"QWidget {{ background: {c['bg_app']}; }}")
        for card in self._cards:
            card.apply_theme(c)
```

- [ ] **Step 2: Run tests**

```
cd /home/jaret/Projects/ToonTownMultiTool-v2 && pytest tests/ -v
```

Expected: 70/70 pass.

- [ ] **Step 3: Smoke import**

```
python -c "from tabs.multitoon._full_layout import _FullLayout; print('ok')"
```

- [ ] **Step 4: Commit**

```bash
git add tabs/multitoon/_full_layout.py
git commit -m "fix(multitoon): _FullLayout.populate() actually re-adds shared widgets"
```

---

## Task 5: Wire `set_layout_mode` + reparent regression test

**Files:**
- Modify: `tabs/multitoon/_tab.py` (just `build_ui` and `set_layout_mode` — touching nothing else)
- Create: `tests/test_layout_reparent.py`

The Compact and Full layouts now both call `populate()` once at construction. Because `_FullLayout` is built second in `build_ui`, the Full populate runs last and steals widget ownership — Compact's items are now stale. We need to call `_compact.populate()` again after both layouts are constructed but before the user sees Compact, so Compact owns the widgets at startup.

Also: switch the construction order back to logical (Compact first, then Full) since the populate-on-swap pattern handles ownership correctly without the construction-order trick. Then call `_compact.populate()` after `_full` is constructed to re-claim ownership for the initial view.

- [ ] **Step 1: Write the failing regression test**

Create `/home/jaret/Projects/ToonTownMultiTool-v2/tests/test_layout_reparent.py`:

```python
"""Regression test for the multitoon-full-ui shared-widget reparenting bug.

The Compact and Full layouts both consume the same per-slot widget instances
(portrait, name label, enable button, etc.). When set_layout_mode swaps between
them, each layout's populate() must re-add the widgets so they end up parented
under the visible layout. If populate is broken, Full UI renders empty.

Run via pytest with QT_QPA_PLATFORM=offscreen (configured in conftest if needed)."""

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _is_descendant_of(widget, ancestor) -> bool:
    """True if `widget` is in the parent chain of `ancestor` (i.e. ancestor is
    one of widget's ancestors)."""
    cur = widget.parent() if widget is not None else None
    while cur is not None:
        if cur is ancestor:
            return True
        cur = cur.parent()
    return False


def test_compact_owns_shared_widgets_at_startup(qapp):
    from tabs.multitoon_tab import MultitoonTab

    tab = MultitoonTab()
    assert tab._mode == "compact"

    # Toggle service button should be parented somewhere under _compact
    assert _is_descendant_of(tab.toggle_service_button, tab._compact)
    # And NOT under _full (Full's items, if any, must be stale)
    assert not _is_descendant_of(tab.toggle_service_button, tab._full)

    # Each per-slot shared widget should also live under _compact
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._compact), (
            f"slot {i} toon_button should be under _compact"
        )
        assert _is_descendant_of(tab.set_selectors[i], tab._compact)


def test_swap_to_full_reparents_shared_widgets(qapp):
    from tabs.multitoon_tab import MultitoonTab

    tab = MultitoonTab()
    tab.set_layout_mode("full")
    assert tab._mode == "full"

    # toggle_service_button must move under _full (the service-bar row)
    assert _is_descendant_of(tab.toggle_service_button, tab._full)
    # And no longer under _compact
    assert not _is_descendant_of(tab.toggle_service_button, tab._compact)

    # Per-slot widgets should now live under _full
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._full), (
            f"slot {i} toon_button should be under _full after swap"
        )
        assert _is_descendant_of(tab.slot_badges[i], tab._full)


def test_swap_back_to_compact_reparents_again(qapp):
    from tabs.multitoon_tab import MultitoonTab

    tab = MultitoonTab()
    tab.set_layout_mode("full")
    tab.set_layout_mode("compact")
    assert tab._mode == "compact"

    # Widgets should now live under _compact again
    assert _is_descendant_of(tab.toggle_service_button, tab._compact)
    assert not _is_descendant_of(tab.toggle_service_button, tab._full)
    for i in range(4):
        assert _is_descendant_of(tab.toon_buttons[i], tab._compact)


def test_set_layout_mode_idempotent(qapp):
    """Calling set_layout_mode with the current mode should be a no-op
    (no exception, no widget reparenting)."""
    from tabs.multitoon_tab import MultitoonTab

    tab = MultitoonTab()
    tab.set_layout_mode("compact")  # already compact
    assert tab._mode == "compact"
    assert _is_descendant_of(tab.toggle_service_button, tab._compact)
```

- [ ] **Step 2: Run the test — expect failures**

```
cd /home/jaret/Projects/ToonTownMultiTool-v2 && pytest tests/test_layout_reparent.py -v
```

Expected: At minimum, `test_compact_owns_shared_widgets_at_startup` FAILS — because Full was built second and stole widget ownership. `test_swap_to_full_reparents_shared_widgets` may also fail or pass depending on whether populate is being called.

- [ ] **Step 3: Update `build_ui` and `set_layout_mode` in `_tab.py`**

In `/home/jaret/Projects/ToonTownMultiTool-v2/tabs/multitoon/_tab.py`, find the current `build_ui` (search `def build_ui(self):`). Replace it (and the existing `set_layout_mode`) with:

```python
    def build_ui(self):
        from tabs.multitoon._compact_layout import _CompactLayout
        from tabs.multitoon._full_layout import _FullLayout

        self._build_shared_widgets()

        # Build both layouts. Each runs populate() in its __init__, so whichever
        # is built second steals widget ownership. We then call _compact.populate()
        # one more time so Compact wins for the initial view.
        self._stack = QStackedWidget(self)
        self._compact = _CompactLayout(self)
        self._full = _FullLayout(self)
        self._compact.populate()  # re-claim ownership for the default view
        self._stack.addWidget(self._compact)
        self._stack.addWidget(self._full)
        self._stack.setCurrentWidget(self._compact)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._stack)

        self._mode = "compact"
        self.update_service_button_style()
        self.update_status_label()

    def set_layout_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        target = self._full if mode == "full" else self._compact
        # Re-attach all shared widgets to the target's slots
        target.populate()
        self._stack.setCurrentWidget(target)
        self._mode = mode
        # Re-apply theme so the new layout picks up colors (incl. game_pill etc.)
        self.refresh_theme()
```

- [ ] **Step 4: Run tests — expect all reparent tests pass**

```
pytest tests/test_layout_reparent.py -v
pytest tests/ -v
```

Expected: 4/4 reparent tests pass; 74/74 total (70 + 4 new).

- [ ] **Step 5: Manual smoke (if GUI available)**

```
python main.py
```

- Maximize: Full UI now renders with portrait, name, stats, controls all visible (not empty).
- Restore: Compact UI renders correctly.
- Re-maximize: still works.

- [ ] **Step 6: Commit**

```bash
git add tabs/multitoon/_tab.py tests/test_layout_reparent.py
git commit -m "fix(multitoon): re-populate target layout on set_layout_mode swap"
```

---

## Task 6: Replace `color: white` with `c['text_on_accent']` across tabs

**Files:**
- Modify: `tabs/multitoon/_tab.py` (4 callsites)
- Modify: `tabs/launch_tab.py` (3 callsites — `accent_blue_btn` and `accent_red` paired stylesheets)
- Modify: `tabs/keymap_tab.py:763`
- Modify: `tabs/invasions_tab.py:339`
- Modify: `tabs/settings_tab.py:253`

For every stylesheet string where `color: white` is paired with a `background:` referencing an `accent_*` token, replace `color: white` with `color: {c['text_on_accent']}`. Hardcoded saturated colors (e.g. `#F26D21`, `#4A8FE7`, `#E05252` — slot identity colors that don't change with theme) keep `color: white` since the contrast there is theme-independent.

- [ ] **Step 1: Audit each callsite**

Run:

```bash
cd /home/jaret/Projects/ToonTownMultiTool-v2 && grep -nE "color:\s*white" tabs/multitoon/_tab.py tabs/launch_tab.py tabs/keymap_tab.py tabs/invasions_tab.py tabs/settings_tab.py
```

For each match, look at the surrounding ~5 lines. Decide:
- **Replace** if `color: white` appears in the same f-string as `background:` referencing `c['accent_green']`, `c['accent_blue_btn']`, `c['accent_orange']`, `c['accent_red']`, `c['game_pill_*']`. (Theme-dependent — needs `text_on_accent` for AA.)
- **Keep** if the background is a hardcoded hex (e.g. `#F26D21`, `#4A8FE7`, `#E05252`, `#56c856` — slot identity colors not affected by light/dark mode).

- [ ] **Step 2: Apply replacements**

For each "Replace" callsite, change:

```python
f"... background: {c['accent_X']}; color: white; ..."
```

to:

```python
f"... background: {c['accent_X']}; color: {c['text_on_accent']}; ..."
```

Specific known callsites (verify line numbers haven't drifted by re-running grep first):

- `tabs/multitoon/_tab.py:1170` — toon enable button (paired with `c['accent_green']`)
- `tabs/multitoon/_tab.py:1217` — chat button (paired with `c['accent_blue_btn']`)
- `tabs/multitoon/_tab.py:1267` — KA rapid-fire (paired with `c['accent_red']`)
- `tabs/multitoon/_tab.py:1282` — KA normal (paired with `c['accent_orange']`)
- `tabs/launch_tab.py:947` — paired with `c['accent_blue_btn']`
- `tabs/launch_tab.py:1094` — paired with `c['accent_blue_btn']`
- `tabs/launch_tab.py:1138` — paired with `c['accent_blue_btn']`
- `tabs/launch_tab.py:1155` — paired with `c['accent_red']`
- `tabs/keymap_tab.py:763` — verify pairing in audit
- `tabs/invasions_tab.py:339` — verify pairing in audit
- `tabs/settings_tab.py:253` — verify pairing in audit

For lines like `tabs/multitoon/_tab.py:1114` and `:1118` (game badges with hardcoded `#F26D21` / `#4A8FE7`): **leave unchanged**. Those are saturated brand colors with adequate contrast against white, and they're not theme-dependent.

For `tabs/launch_tab.py:939` (hardcoded `#E05252`): **leave unchanged** for the same reason.

- [ ] **Step 3: Verify each callsite has access to `c` (the theme-color dict)**

Inside each `refresh_theme` method (or wherever the stylesheet is applied), there's already a local `c = get_theme_colors(...)`. The new `c['text_on_accent']` token has been part of both palettes since commit `7d5e23d`, so all callsites should resolve cleanly.

If any of the audited callsites is in a function that does NOT have `c` in scope (e.g. a one-off stylesheet outside `refresh_theme`), pass it the dict or read it inline:

```python
c = get_theme_colors(resolve_theme(self.settings_manager) == "dark")
```

This keeps the callsite self-contained.

- [ ] **Step 4: Run tests**

```
cd /home/jaret/Projects/ToonTownMultiTool-v2 && pytest tests/ -v
```

Expected: all 74 tests pass.

- [ ] **Step 5: Manual smoke (if GUI available)**

Toggle dark mode. Click an Enabled button — the "Enabled" label is now slate-900 on green-400 instead of white on green-400. Same for chat button glyph, set selector text, etc.

- [ ] **Step 6: Commit**

```bash
git add tabs/multitoon/_tab.py tabs/launch_tab.py tabs/keymap_tab.py tabs/invasions_tab.py tabs/settings_tab.py
git commit -m "fix(theme): use text_on_accent on accent buttons for AA contrast"
```

---

## Task 7: Fix `_set_layout_mode` race during fast resize drag

**Files:**
- Modify: `main.py` (just `_set_layout_mode`)

When `resizeEvent` fires repeatedly during a window-border drag, multiple `_set_layout_mode` calls can stack up because `self._layout_mode = target` is currently deferred into the fade-out callback (80 ms later). During those 80 ms, additional resize ticks see the old mode and start new fades. Fix: assign `self._layout_mode = target` synchronously at the top of the function — only the visual fade is deferred.

- [ ] **Step 1: Update `_set_layout_mode`**

In `/home/jaret/Projects/ToonTownMultiTool-v2/main.py`, find `def _set_layout_mode(self, target: str)`. Replace its body with:

```python
    def _set_layout_mode(self, target: str) -> None:
        # Commit to the new mode synchronously so concurrent resizeEvent ticks
        # during the fade don't restart the animation.
        self._layout_mode = target

        # Honor disable_animations: instant swap, no fade.
        if self.settings_manager.get("disable_animations", False):
            self.multitoon_tab.set_layout_mode(target)
            return

        # Cross-fade: 80ms fade-out -> swap -> 80ms fade-in (160ms total).
        widget = self.multitoon_tab
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        fade_out = QPropertyAnimation(effect, b"opacity")
        fade_out.setDuration(80)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.OutCubic)

        fade_in = QPropertyAnimation(effect, b"opacity")
        fade_in.setDuration(80)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)

        def _on_fade_out_done():
            self.multitoon_tab.set_layout_mode(target)
            fade_in.start()

        fade_out.finished.connect(_on_fade_out_done)
        fade_in.finished.connect(lambda: widget.setGraphicsEffect(None))

        # Keep references so they don't get GC'd mid-animation.
        self._layout_fade_out = fade_out
        self._layout_fade_in = fade_in

        fade_out.start()
```

The change: `self._layout_mode = target` moves to the top (line 1 of the body); the duplicate assignment inside `_on_fade_out_done` is removed.

- [ ] **Step 2: Run tests**

```
cd /home/jaret/Projects/ToonTownMultiTool-v2 && pytest tests/ -v
```

Expected: 74/74 pass.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "fix(layout): commit layout_mode synchronously to avoid cross-fade race"
```

---

## Self-review (after writing the plan)

**1. Spec coverage:**
- Bug 1 (Full UI empty): Tasks 1–5 — clear_layout helper, structure-vs-populate split for both layouts and `_FullToonCard`, real `_FullLayout.populate`, and a regression test that drives the swap and asserts widget parentage.
- Bug 2 (color: white in dark mode): Task 6.
- Bug 3 (cross-fade race): Task 7.

All three bugs have a dedicated task. The reparent regression test (Task 5) is the structural test the original 14-task plan was missing.

**2. Placeholder scan:** No "TBD"/"TODO"/"implement later". Every step has the exact code or command. Task 6 has one minor inline TODO ("verify pairing in audit") for lines we haven't read inline — but the audit step itself provides the decision criterion (background hex vs. accent token).

**3. Type consistency:**
- `clear_layout(layout: QLayout) -> None` defined in Task 1, used in Tasks 2, 3, 4.
- `_CompactLayout.populate()` defined in Task 2, called from Task 5.
- `_FullToonCard.populate_active()` defined in Task 3, called from `_FullLayout.populate()` in Task 4.
- `_FullLayout.populate()` defined in Task 4, called from Task 5.
- `set_layout_mode(mode: str)` signature unchanged from existing.

All consistent.

---

## Plan complete — saved to `docs/superpowers/plans/2026-04-27-multitoon-full-ui-bugfix.md`

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec then quality) per task, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.

Which approach?
