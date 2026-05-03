# UI Polish Batch (Items 9, 10, 11, 12) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land four small UI polish improvements for v2.0.5: a semantic typography scale (with header migrated as proof), removal of the header byline duplication, a subtle light-mode background gradient, and a fix for the launch animation `RuntimeWarning`.

**Architecture:** Each item is independent and ships as its own commit. Typography roles are added as a centralized helper in `utils/theme_manager.py`; the header is the only call site migrated this round (other inline font-sizes are left for future passes to keep the diff focused). Light-mode background gradient is applied via the existing `LIGHT_THEME` stylesheet. The animation fix is a code deletion — the disconnect block is dead code that fires a Qt warning.

**Tech Stack:** PySide6 / Qt, Python 3.12, pytest.

---

## File Structure

- **Modify** `utils/theme_manager.py` — add `TYPOGRAPHY` dict + `font_role()` helper (Task 1); change `LIGHT_THEME` to use a vertical gradient on the QWidget background (Task 3)
- **Modify** `main.py` — remove byline label from `_build_header` and its style block (Task 2); delete the `_launch_anim.finished.disconnect()` block (Task 4); use `font_role("title")` and `font_role("body")` in `refresh_theme`'s header section (Task 1)
- **Create** `tests/test_theme_manager.py` — unit tests for `font_role` and assertions about `LIGHT_THEME` stylesheet content
- **Touch nothing** in `tabs/credits_tab.py` — it already has its own "Created by flossbud" label; we just stop duplicating in the header

---

## Task 1: Typography Scale (Item 9)

**Files:**
- Modify: `utils/theme_manager.py` (add TYPOGRAPHY + font_role at module top, after imports)
- Create: `tests/test_theme_manager.py`
- Modify: `main.py:434,437,440` (header re-style call site)

- [ ] **Step 1.1: Write the failing tests for `font_role`**

Create `tests/test_theme_manager.py`:

```python
"""Tests for utils.theme_manager typography helpers."""

import pytest
from utils.theme_manager import font_role, TYPOGRAPHY, LIGHT_THEME


def test_font_role_known_roles_return_ints():
    for role in ("display", "title", "body", "label", "caption"):
        size = font_role(role)
        assert isinstance(size, int)
        assert 8 <= size <= 32, f"role={role} size={size} out of plausible range"


def test_font_role_scale_is_monotonic():
    # display > title > body > label > caption
    sizes = [font_role(r) for r in ("display", "title", "body", "label", "caption")]
    assert sizes == sorted(sizes, reverse=True), f"non-monotonic scale: {sizes}"


def test_font_role_unknown_falls_back_to_body():
    assert font_role("nonexistent") == font_role("body")


def test_typography_dict_has_canonical_roles():
    assert {"display", "title", "body", "label", "caption"} <= set(TYPOGRAPHY.keys())
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `pytest tests/test_theme_manager.py -v`
Expected: ImportError or NameError on `font_role` / `TYPOGRAPHY` (not yet defined).

- [ ] **Step 1.3: Add the typography helper**

Edit `utils/theme_manager.py` — add this block after the existing imports (around line 11, after the `from utils.shared_widgets import SmoothProgressBar` line):

```python
# ── Typography Scale ──────────────────────────────────────────────────────
# Semantic font-size roles. Use font_role(name) instead of inline px values.
# Sizes chosen to match the existing visual hierarchy used in the header,
# tab content, and small badges; tweak here to rescale globally.

TYPOGRAPHY = {
    "display": 22,   # large, attention-grabbing (e.g. empty-state headlines)
    "title":   17,   # section titles, the app header title
    "body":    13,   # default content text
    "label":   11,   # small labels, version badge, byline
    "caption": 10,   # micro labels, status pills, footnotes
}


def font_role(role: str) -> int:
    """Return the px size for a semantic typography role.

    Unknown roles fall back to "body" so a typo never produces 0px text.
    """
    return TYPOGRAPHY.get(role, TYPOGRAPHY["body"])
```

- [ ] **Step 1.4: Run tests to verify font_role passes (LIGHT_THEME assertion will be added in Task 3)**

Run: `pytest tests/test_theme_manager.py -v -k "font_role or typography_dict"`
Expected: 4 passed.

- [ ] **Step 1.5: Migrate the header to use roles**

In `main.py`, find the `refresh_theme` block at line 434 and replace the three hardcoded font-size lines:

Before (around line 434-440):
```python
self.title_label.setStyleSheet("font-size: 17px; font-weight: bold; background: transparent;")
self.title_label.setText(
    f'<span style="color:{tc}">ToonTown MultiTool</span>'
    f' <span style="color:{vc}; font-size:11px; font-weight:bold;">v{self.APP_VERSION}</span>'
)
self.byline_label.setStyleSheet(f"""
    font-size: 11px; color: {c['header_sub']}; background: transparent;
""")
```

After:
```python
self.title_label.setStyleSheet(
    f"font-size: {font_role('title')}px; font-weight: bold; background: transparent;"
)
self.title_label.setText(
    f'<span style="color:{tc}">ToonTown MultiTool</span>'
    f' <span style="color:{vc}; font-size:{font_role("label")}px; font-weight:bold;">'
    f'v{self.APP_VERSION}</span>'
)
self.byline_label.setStyleSheet(f"""
    font-size: {font_role('label')}px; color: {c['header_sub']}; background: transparent;
""")
```

(The byline edit will be undone in Task 2 when the byline is removed entirely. We touch it here only because the role migration sweep is the focus of this task; leaving it as `font-size: 11px` would defeat the demo.)

Also at the top of `main.py`, in the existing `from utils.theme_manager import (...)` block (around line 37-42), add `font_role` to the import list:

```python
from utils.theme_manager import (
    apply_theme, resolve_theme, get_theme_colors, apply_card_shadow,
    make_nav_gamepad, make_nav_power,
    make_nav_keyboard, make_nav_gear, make_nav_terminal, make_nav_bookmark,
    make_hint_icon, make_info_icon, font_role,
)
```

- [ ] **Step 1.6: Run app from source and confirm header renders unchanged**

Run: `cd /home/jaret/Projects/ToonTownMultiTool-v2 && QT_QPA_PLATFORM=xcb python3 main.py`
Expected: header looks visually identical to before (title 17px, version 11px, byline 11px).
Kill with Ctrl+C after visual check.

- [ ] **Step 1.7: Commit**

```bash
git add utils/theme_manager.py main.py tests/test_theme_manager.py
git commit -m "feat(theme): add font_role typography scale and migrate header"
```

---

## Task 2: Remove Header Byline (Item 10)

**Files:**
- Modify: `main.py:276-279` (header construction)
- Modify: `main.py:439-441` (header re-style — remove the byline_label.setStyleSheet block)

The Credits tab already has its own "Created by flossbud" label (`tabs/credits_tab.py:48`), so the header byline is redundant.

- [ ] **Step 2.1: Remove the byline widget from `_build_header`**

In `main.py`, around lines 274-279, delete the byline section. Before:

```python
        layout.addStretch()

        # Byline
        self.byline_label = QLabel("by flossbud")
        self.byline_label.setObjectName("header_byline")
        layout.addWidget(self.byline_label)

        return header
```

After:

```python
        layout.addStretch()

        return header
```

- [ ] **Step 2.2: Remove the byline style application from `refresh_theme`**

In `main.py`, around lines 439-441, delete the `self.byline_label.setStyleSheet(...)` call. Before:

```python
self.byline_label.setStyleSheet(f"""
    font-size: {font_role('label')}px; color: {c['header_sub']}; background: transparent;
""")
# Accent stripe
```

After:

```python
# Accent stripe
```

- [ ] **Step 2.3: Run app and visually confirm**

Run: `cd /home/jaret/Projects/ToonTownMultiTool-v2 && QT_QPA_PLATFORM=xcb python3 main.py`
Expected: header shows the title and version only, with empty stretch on the right where the byline was. Open the Credits tab and confirm "Created by flossbud 🐾" still renders there.
Kill with Ctrl+C.

- [ ] **Step 2.4: Run existing tests to confirm no regression**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add main.py
git commit -m "refactor(ui): remove redundant header byline (kept in Credits tab)"
```

---

## Task 3: Subtle Light-Mode Background Gradient (Item 11)

**Files:**
- Modify: `utils/theme_manager.py` — `LIGHT_THEME` stylesheet
- Modify: `tests/test_theme_manager.py` — add gradient assertion

The current light-mode app background is the flat color `#f0f0f0`. A 4-5% lightness vertical gradient adds depth without being noticeable as a gradient.

- [ ] **Step 3.1: Locate the LIGHT_THEME QWidget rule**

Read `utils/theme_manager.py` around line 340 (where `LIGHT_THEME = """` starts). Find the top-level `QWidget` rule that sets `background-color: #f0f0f0` (or similar). The exact line number depends on the file's current state — search for `LIGHT_THEME` and locate the first `QWidget` block inside the triple-quoted string.

- [ ] **Step 3.2: Write the failing assertion**

Append to `tests/test_theme_manager.py`:

```python
def test_light_theme_uses_gradient_background():
    """The flat #f0f0f0 background was replaced with a subtle gradient."""
    assert "qlineargradient" in LIGHT_THEME, (
        "LIGHT_THEME should use qlineargradient for app background depth"
    )
```

- [ ] **Step 3.3: Run test to verify it fails**

Run: `pytest tests/test_theme_manager.py::test_light_theme_uses_gradient_background -v`
Expected: FAIL — `qlineargradient` not in LIGHT_THEME.

- [ ] **Step 3.4: Replace the flat background with a gradient**

In `utils/theme_manager.py`, inside the `LIGHT_THEME = """ ... """` block, find the top-level `QWidget` rule (the one that sets `background-color`). Replace the `background-color` line with a `qlineargradient`:

Before (the QWidget rule will look approximately like this — your exact stylesheet may differ):
```css
QWidget {
    font-family: 'Inter', 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif;
    font-size: 12pt;
    background-color: #f0f0f0;
    color: #111111;
}
```

After:
```css
QWidget {
    font-family: 'Inter', 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif;
    font-size: 12pt;
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #f6f6f6, stop:1 #ebebeb);
    color: #111111;
}
```

The gradient runs top→bottom, brighter at the top (#f6f6f6) and slightly darker at the bottom (#ebebeb). The midpoint (#f0f0f0) matches the previous flat color, so all child widgets that already use `bg_app` continue to compose visually.

- [ ] **Step 3.5: Run tests**

Run: `pytest tests/test_theme_manager.py -v`
Expected: all tests pass (5 total).

- [ ] **Step 3.6: Visual sanity check**

Run: `cd /home/jaret/Projects/ToonTownMultiTool-v2 && QT_QPA_PLATFORM=xcb python3 main.py`
Expected: in light mode, the app background has subtle top-to-bottom shading. It should be visible only when looking for it; the cards and sidebar still read clearly.
If the gradient is *too* visible, narrow the stops (e.g. `#f4f4f4` → `#ededed`); if invisible, widen them.
Kill with Ctrl+C.

- [ ] **Step 3.7: Commit**

```bash
git add utils/theme_manager.py tests/test_theme_manager.py
git commit -m "feat(theme): subtle vertical gradient on light-mode app background"
```

---

## Task 4: Fix Launch-Animation RuntimeWarning (Item 12)

**Files:**
- Modify: `main.py:204-208` (delete the dead disconnect block)

**Why this fix:** `_animate_launch` creates a fresh `QPropertyAnimation` on every call (line 198). The disconnect on line 206 runs on the *just-constructed* animation, which has nothing connected — Qt prints `RuntimeWarning: Failed to disconnect (None) from signal "finished()"`. The `try/except RuntimeError` handler catches the Python exception, but the warning is emitted separately by PySide6's binding layer. Old animations from prior calls are garbage-collected when `self._launch_anim` is reassigned, so there is nothing to disconnect — the block is dead code.

- [ ] **Step 4.1: Delete the disconnect block**

In `main.py`, around lines 203-208, delete this block:

```python
        # Disconnect any previous signal to prevent accumulation
        try:
            self._launch_anim.finished.disconnect()
        except RuntimeError:
            pass
```

So that `_animate_launch` reads:

```python
def _animate_launch(self):
    # Prevent word filtering from causing layout jumps while width is small
    self.title_label.setWordWrap(False)
    self.title_label.setMaximumWidth(0)

    self._launch_anim = QPropertyAnimation(self.title_label, b"maximumWidth")
    self._launch_anim.setDuration(TITLE_ANIM_DURATION_MS)
    self._launch_anim.setStartValue(0)
    self._launch_anim.setEndValue(TITLE_ANIM_MAX_WIDTH)
    self._launch_anim.setEasingCurve(QEasingCurve.OutCubic)

    # After animation, remove the maximum width constraint
    self._launch_anim.finished.connect(lambda: self.title_label.setMaximumWidth(16777215))
    self._launch_anim.start()
```

- [ ] **Step 4.2: Run app and check stderr for the warning**

Run: `cd /home/jaret/Projects/ToonTownMultiTool-v2 && QT_QPA_PLATFORM=xcb python3 main.py 2>&1 | tee /tmp/ttm-anim-test.log`
Wait until the title-label animation completes (≈1 second), then close the window.

Then verify the warning is gone:

```bash
grep -E "Failed to disconnect|RuntimeWarning" /tmp/ttm-anim-test.log && echo "STILL WARNING" || echo "CLEAN"
```

Expected: `CLEAN`.

- [ ] **Step 4.3: Run existing tests**

Run: `pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 4.4: Commit**

```bash
git add main.py
git commit -m "fix(ui): remove dead disconnect that caused launch-anim RuntimeWarning"
```

---

## Self-Review Checklist (run after Task 4)

- [ ] **All four items addressed:** typography scale (T1), header byline removal (T2), bg gradient (T3), animation warning (T4) — yes
- [ ] **No placeholders:** every step has concrete code, exact paths, exact commands — yes
- [ ] **Type consistency:** `font_role` used the same way in T1 step 1.5 and the typography helper definition in step 1.3 — yes
- [ ] **Spec coverage:** every item in the user's "9/10/11/12" request has at least one task — yes
- [ ] **Independent commits:** each task ends with a commit, so any one can be reverted without disturbing the others — yes

---

## Verification before push

After all four tasks are committed:

- [ ] `pytest tests/ -q` — all pass
- [ ] `python3 main.py` (host) — visually confirm: header has no byline, light-mode bg has subtle gradient, no `RuntimeWarning` in stderr
- [ ] `git log --oneline v2.0.4..HEAD` — confirm 4 new commits with `feat(theme):`, `refactor(ui):`, `feat(theme):`, `fix(ui):` prefixes (in addition to the prior commits already on `main`)

Push with `git push origin main`. These will ride into v2.0.5 along with the earlier post-v2.0.4 fixes.
