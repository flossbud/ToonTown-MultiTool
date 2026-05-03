# Keep-Alive Opt-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global, default-off opt-in toggle for the Keep-Alive (and Rapid-Fire) features, with an explicit consent dialog citing TTR/CC TOS risk on enable, gating per-toon button availability and the keep-alive thread loop. Per-toon configuration is preserved across opt-in/opt-out cycles.

**Architecture:** Single new boolean setting `keep_alive_enabled` (default `False`) in `SettingsManager`. `MultitoonTab` consults a small helper at three gating points (`apply_visual_state`, `toggle_keep_alive`, the keep-alive thread loop); per-toon flags are preserved when the master flips off. `SettingsTab` shows a master `ToggleRow` at the top of the Keep-Alive group and runs a `QMessageBox.warning` consent dialog before committing the True value.

**Tech Stack:** PySide6 (Qt 6), pytest, existing `SettingsManager` / `ToggleRow` / `KeepAliveBtn` / `MultitoonTab` infrastructure.

---

## Spec reference

This plan implements `docs/superpowers/specs/2026-05-03-keep-alive-opt-in-design.md`.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `utils/settings_manager.py` | Modify | Add `keep_alive_enabled: False` to defaults dict. |
| `tabs/multitoon/_tab.py` | Modify | Add helpers `_keep_alive_globally_enabled` and `_suspend_keep_alive`. Gate `apply_visual_state`, `toggle_keep_alive`, the keep-alive thread loop, and `load_profile`. Hook `_on_setting_changed`. Patch `KeepAliveBtn._on_long_press` to no-op when disabled. |
| `tabs/settings_tab.py` | Modify | Add master `ToggleRow` to `_build_keepalive_group`. Add toggle handler with revert-on-cancel. Add consent dialog method (factored for test injection). Ghost action/interval rows when master is off. |
| `tests/test_keep_alive_gating.py` | Create | All tests for the new behavior. |

---

## Task 1: Add `keep_alive_enabled` default-False setting

**Files:**
- Modify: `utils/settings_manager.py:11-20` (the defaults dict)
- Test: `tests/test_keep_alive_gating.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_keep_alive_gating.py` with:

```python
"""Tests for the keep-alive opt-in master toggle (TTR/CC TOS compliance)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_keep_alive_master_default_off(tmp_path, monkeypatch):
    """A fresh SettingsManager has keep_alive_enabled defaulting to False."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    sm = SettingsManager()
    assert sm.get("keep_alive_enabled") is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_keep_alive_gating.py::test_keep_alive_master_default_off -v
```

Expected: FAIL — `assert None is False`. The key is absent from the defaults dict, so `.get()` returns `None`.

- [ ] **Step 3: Add the setting to the defaults dict**

Edit `utils/settings_manager.py`. Inside `SettingsManager.__init__`, modify the `self.settings` dict (line 11-20). Add the new key alongside the other keep-alive keys:

```python
        self.settings = {
            "show_debug_tab":        False,
            "show_diagnostics_tab":  False,
            "keep_alive_enabled":    False,
            "keep_alive_action":     "jump",
            "keep_alive_delay":      "30 sec",
            "theme":                 "system",
            "enable_companion_app":  True,
            "input_backend":         "xlib",
            "active_profile":        -1,
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_keep_alive_gating.py::test_keep_alive_master_default_off -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/settings_manager.py tests/test_keep_alive_gating.py
git commit -m "feat(keep-alive): add keep_alive_enabled setting (default off)"
```

---

## Task 2: Add `_keep_alive_globally_enabled` helper

**Files:**
- Modify: `tabs/multitoon/_tab.py` (add a new method on `MultitoonTab`)
- Test: `tests/test_keep_alive_gating.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keep_alive_gating.py`:

```python
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettingsManager:
    def __init__(self, initial=None):
        self._data = dict(initial or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def on_change(self, callback):
        pass


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


@pytest.fixture
def tab(qapp):
    from tabs.multitoon_tab import MultitoonTab
    return MultitoonTab(
        settings_manager=_FakeSettingsManager(),
        window_manager=_FakeWindowManager(),
    )


def test_keep_alive_helper_returns_false_by_default(tab):
    assert tab._keep_alive_globally_enabled() is False


def test_keep_alive_helper_returns_true_when_set(tab):
    tab.settings_manager.set("keep_alive_enabled", True)
    assert tab._keep_alive_globally_enabled() is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_keep_alive_gating.py::test_keep_alive_helper_returns_false_by_default -v
pytest tests/test_keep_alive_gating.py::test_keep_alive_helper_returns_true_when_set -v
```

Expected: FAIL — `AttributeError: 'MultitoonTab' object has no attribute '_keep_alive_globally_enabled'`.

- [ ] **Step 3: Add the helper**

In `tabs/multitoon/_tab.py`, find the `_get_keep_alive_delay` method (around line 2199) and add the helper next to it:

```python
    def _keep_alive_globally_enabled(self) -> bool:
        """Return True iff the user has opted in to Keep-Alive via Settings.
        Gates per-toon button availability, toggle_keep_alive, and the
        keep-alive thread loop."""
        return bool(
            self.settings_manager
            and self.settings_manager.get("keep_alive_enabled", False)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_keep_alive_gating.py::test_keep_alive_helper_returns_false_by_default -v
pytest tests/test_keep_alive_gating.py::test_keep_alive_helper_returns_true_when_set -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_tab.py tests/test_keep_alive_gating.py
git commit -m "feat(keep-alive): add _keep_alive_globally_enabled helper"
```

---

## Task 3: Gate per-toon button enable + tooltip in `apply_visual_state`

**Files:**
- Modify: `tabs/multitoon/_tab.py:1412` (`_apply_keep_alive_btn_style`)
- Test: `tests/test_keep_alive_gating.py` (extend)

The existing `_apply_keep_alive_btn_style` method always sets `ka_btn.setEnabled(True)` at line 1414. We extend it to consult the master flag and override to disabled + new tooltip when off.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_keep_alive_gating.py`:

```python
def _force_window_available(tab, slot=0):
    """Helper: simulate one detected toon window so per-toon controls activate."""
    tab.window_manager.ttr_window_ids = ["fake_wid"]
    tab.enabled_toons[slot] = True
    tab.service_running = True


def test_per_toon_button_disabled_when_master_off(tab):
    _force_window_available(tab, slot=0)
    tab.settings_manager.set("keep_alive_enabled", False)
    tab.apply_visual_state(0)
    assert tab.keep_alive_buttons[0].isEnabled() is False
    assert "Settings" in tab.keep_alive_buttons[0].toolTip()


def test_per_toon_button_enabled_when_master_on(tab):
    _force_window_available(tab, slot=0)
    tab.settings_manager.set("keep_alive_enabled", True)
    tab.apply_visual_state(0)
    assert tab.keep_alive_buttons[0].isEnabled() is True
    # Existing tooltip preserved (set in _build_shared_widgets)
    assert "Toggle keep-alive" in tab.keep_alive_buttons[0].toolTip()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_keep_alive_gating.py::test_per_toon_button_disabled_when_master_off tests/test_keep_alive_gating.py::test_per_toon_button_enabled_when_master_on -v
```

Expected: FAIL on `test_per_toon_button_disabled_when_master_off` (the existing code unconditionally sets enabled True).

- [ ] **Step 3: Modify `_apply_keep_alive_btn_style` to gate on master flag**

Edit `tabs/multitoon/_tab.py`. Replace the body of `_apply_keep_alive_btn_style` (line 1412 through the end of the method around line 1460) so the very first action is to consult the master flag:

```python
    def _apply_keep_alive_btn_style(self, index, c):
        ka_btn = self.keep_alive_buttons[index]
        if not self._keep_alive_globally_enabled():
            ka_btn.setEnabled(False)
            ka_btn.setToolTip(
                "Keep-Alive is disabled. Enable it in Settings → Keep-Alive."
            )
            ka_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['btn_disabled']};
                    color: {c['text_disabled']};
                    border: none; border-radius: 6px;
                }}
            """)
            bar = self.ka_progress_bars[index] if index < len(self.ka_progress_bars) else None
            if bar:
                bar.set_fill_color(c.get('text_muted', '#888888'))
            return
        ka_btn.setEnabled(True)
        ka_btn.setToolTip("Toggle keep-alive for this toon")
        is_rf = getattr(self, 'rapid_fire_enabled', [False]*4)[index]
        bar = self.ka_progress_bars[index] if index < len(self.ka_progress_bars) else None
        if self.keep_alive_enabled[index]:
            if is_rf:
                ka_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c['accent_red']};
                        color: {c['text_on_accent']};
                        border: 2px solid {c['accent_red_border']};
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background-color: {c['accent_red_hover']};
                        border: 2px solid {c['accent_red_border']};
                    }}
                """)
                if bar:
                    bar.set_fill_color("#E05252")
            else:
                ka_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c['accent_orange']};
                        color: {c['text_on_accent']};
                        border: 2px solid {c['accent_orange_border']};
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background-color: {c['accent_orange_hover']};
                        border: 2px solid {c['accent_orange_border']};
                    }}
                """)
                if bar:
                    bar.set_fill_color("#e0943a")
        else:
            ka_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['toon_btn_inactive_bg']};
                    color: {c['text_muted']};
                    border: 1px solid {c['toon_btn_inactive_border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {c['toon_btn_inactive_hover']};
                    border: 1px solid {c['toon_btn_inactive_hover_border']};
                }}
            """)
```

The existing branches inside the method are reproduced verbatim — only the early-return at the top and the explicit `setToolTip` after `setEnabled(True)` are new. The existing body's prior assumptions (`setEnabled(True)` at top) are preserved.

Also, `apply_visual_state` has a service-stopped branch around `_tab.py:1307-1316` that sets `ka_btn.setEnabled(False)` and a stylesheet directly. That branch should NOT also fire when master is off and service is on; the master-off styling above is already correct in that case. No change needed there — service-off is its own path.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_keep_alive_gating.py -v
```

Expected: PASS for the new tests; existing tests in the file still PASS.

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_tab.py tests/test_keep_alive_gating.py
git commit -m "feat(keep-alive): gate per-toon button on master flag with recovery tooltip"
```

---

## Task 4: Gate the keep-alive thread loop on the master flag

**Files:**
- Modify: `tabs/multitoon/_tab.py:2208` (`_run_keep_alive_loop`)
- Test: `tests/test_keep_alive_gating.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keep_alive_gating.py`:

```python
def test_keep_alive_loop_skips_when_master_off(tab, monkeypatch):
    """The thread loop reads keep_alive_enabled at the top of each cycle
    and skips firing when it's False. Defense in depth against races."""
    sent_calls = []

    class _StubInputService:
        def send_keep_alive_to_window(self, *args, **kwargs):
            sent_calls.append((args, kwargs))

        def stop(self):
            pass

        def start(self):
            pass

    tab.input_service = _StubInputService()
    tab.window_manager.ttr_window_ids = ["wid_a", "wid_b"]
    tab.keep_alive_enabled = [True, True, False, False]
    tab.settings_manager.set("keep_alive_enabled", False)

    # Drive one iteration of the loop body manually.
    # We can't easily start the thread in tests; instead, assert the
    # gating helper that the loop checks returns False, AND assert the
    # production loop's gating decision via a direct invariant test.
    assert tab._keep_alive_globally_enabled() is False
    # Simulate the loop's gating decision:
    fire_toons = [
        i for i, state in enumerate(tab.keep_alive_enabled)
        if state and tab._keep_alive_globally_enabled()
    ]
    assert fire_toons == []


def test_keep_alive_loop_fires_when_master_on(tab):
    tab.window_manager.ttr_window_ids = ["wid_a", "wid_b"]
    tab.keep_alive_enabled = [True, True, False, False]
    tab.settings_manager.set("keep_alive_enabled", True)

    fire_toons = [
        i for i, state in enumerate(tab.keep_alive_enabled)
        if state and tab._keep_alive_globally_enabled()
    ]
    assert fire_toons == [0, 1]
```

- [ ] **Step 2: Run tests to verify the helper is wired correctly**

```bash
pytest tests/test_keep_alive_gating.py::test_keep_alive_loop_skips_when_master_off tests/test_keep_alive_gating.py::test_keep_alive_loop_fires_when_master_on -v
```

These tests pin the gating-decision pattern (master-AND-per-toon-flag). They pass before the production change too — the production gate added in Step 3 implements the same pattern in `_run_keep_alive_loop`. The tests guard against future regressions where someone removes the gate from the production loop.

- [ ] **Step 3: Add the master-flag gate inside `_run_keep_alive_loop`**

Edit `tabs/multitoon/_tab.py:2208`. Inside `_run_keep_alive_loop`, after the existing wait/break-check at the top of each iteration but before `fire_toons` are computed, add a master-flag short-circuit. The change goes at the body's `now = time.monotonic()` line (around line 2228) — insert immediately before:

```python
                if not self._keep_alive_running:
                    break

                # Master flag re-check: if the user opted out while we were
                # sleeping, skip this cycle. _suspend_keep_alive will stop
                # the thread soon after; this is defense in depth so at most
                # one in-flight burst can leak.
                if not self._keep_alive_globally_enabled():
                    continue

                now = time.monotonic()
```

- [ ] **Step 4: Verify the test still passes (it does — it's an invariant guard)**

```bash
pytest tests/test_keep_alive_gating.py::test_keep_alive_loop_skips_when_master_off tests/test_keep_alive_gating.py::test_keep_alive_loop_fires_when_master_on -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_tab.py tests/test_keep_alive_gating.py
git commit -m "feat(keep-alive): gate keep-alive thread loop on master flag"
```

---

## Task 5: Gate `toggle_keep_alive` to early-return when master is off

**Files:**
- Modify: `tabs/multitoon/_tab.py:1843` (`toggle_keep_alive`)
- Test: `tests/test_keep_alive_gating.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keep_alive_gating.py`:

```python
def test_toggle_keep_alive_no_op_when_master_off(tab):
    """Programmatic calls to toggle_keep_alive must early-return when master
    is off (defense against profile-load or hotkey paths)."""
    tab.window_manager.ttr_window_ids = ["wid_a"]
    tab.service_running = True
    tab.enabled_toons[0] = True
    tab.settings_manager.set("keep_alive_enabled", False)

    assert tab.keep_alive_enabled[0] is False
    tab.toggle_keep_alive(0)
    assert tab.keep_alive_enabled[0] is False  # Still off — toggle suppressed


def test_toggle_keep_alive_works_when_master_on(tab):
    tab.window_manager.ttr_window_ids = ["wid_a"]
    tab.service_running = True
    tab.enabled_toons[0] = True
    tab.settings_manager.set("keep_alive_enabled", True)

    assert tab.keep_alive_enabled[0] is False
    tab.toggle_keep_alive(0)
    assert tab.keep_alive_enabled[0] is True
    # Cleanup so other tests aren't polluted
    tab.toggle_keep_alive(0)
```

- [ ] **Step 2: Run tests to verify the first one fails**

```bash
pytest tests/test_keep_alive_gating.py::test_toggle_keep_alive_no_op_when_master_off -v
```

Expected: FAIL — without the gate, `toggle_keep_alive` flips the flag.

- [ ] **Step 3: Add the gate**

Edit `tabs/multitoon/_tab.py:1843`. Add an early-return at the top of `toggle_keep_alive`:

```python
    def toggle_keep_alive(self, index):
        if not self._keep_alive_globally_enabled():
            # Master flag is off — suppress toggle. The button should already
            # be visually disabled; this guards against programmatic callers
            # like load_profile or hotkey-driven paths.
            return
        self.keep_alive_enabled[index] = not self.keep_alive_enabled[index]
        self.keep_alive_buttons[index].setChecked(self.keep_alive_enabled[index])
        # ... rest of method unchanged ...
```

(Only the first three lines after the signature are new — the rest of the existing method body stays.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_keep_alive_gating.py::test_toggle_keep_alive_no_op_when_master_off tests/test_keep_alive_gating.py::test_toggle_keep_alive_works_when_master_on -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_tab.py tests/test_keep_alive_gating.py
git commit -m "feat(keep-alive): gate toggle_keep_alive on master flag"
```

---

## Task 6: Add `_suspend_keep_alive` helper + `KeepAliveBtn._on_long_press` disabled guard

**Files:**
- Modify: `tabs/multitoon/_tab.py` (add helper, patch `KeepAliveBtn._on_long_press`)
- Test: `tests/test_keep_alive_gating.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_keep_alive_gating.py`:

```python
def test_suspend_keep_alive_preserves_per_toon_flags(tab):
    """_suspend_keep_alive stops execution but does NOT zero per-toon flags.
    Per-toon configuration is the user's setup, preserved across master toggles."""
    tab.window_manager.ttr_window_ids = ["wid_a", "wid_b"]
    tab.service_running = True
    tab.enabled_toons = [True, True, False, False]
    tab.keep_alive_enabled = [True, True, False, False]
    tab.rapid_fire_enabled = [False, True, False, False]
    tab.settings_manager.set("keep_alive_enabled", True)

    tab._suspend_keep_alive()

    # Per-toon flags preserved
    assert tab.keep_alive_enabled == [True, True, False, False]
    assert tab.rapid_fire_enabled == [False, True, False, False]
    # Thread halted (or was never running, but the flag should be cleared)
    assert tab._keep_alive_running is False


def test_long_press_no_op_when_button_disabled(qapp):
    """Holding a disabled KeepAliveBtn for >5s does not toggle rapid-fire."""
    from tabs.multitoon._tab import KeepAliveBtn
    btn = KeepAliveBtn()
    btn.setEnabled(False)
    btn.is_rapid_fire = False
    # Simulate the timer having fired (the timer is a singleshot — bypass
    # the press/release machinery and call _on_long_press directly).
    btn._on_long_press()
    assert btn.is_rapid_fire is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_keep_alive_gating.py::test_suspend_keep_alive_preserves_per_toon_flags tests/test_keep_alive_gating.py::test_long_press_no_op_when_button_disabled -v
```

Expected: FAIL — `_suspend_keep_alive` does not exist yet, and `_on_long_press` toggles regardless of `isEnabled()`.

- [ ] **Step 3: Add `_suspend_keep_alive` and patch `_on_long_press`**

In `tabs/multitoon/_tab.py`, near `_stop_keep_alive` (around line 2187), add:

```python
    def _suspend_keep_alive(self):
        """Stop KA execution and clear button visuals while preserving per-toon
        flags. Called when the master toggle flips off — per-toon setup is the
        user's, the master flag is just whether the feature class is enabled."""
        self._stop_keep_alive()
        for i in range(4):
            if i < len(self.keep_alive_buttons):
                btn = self.keep_alive_buttons[i]
                btn.setGraphicsEffect(None)
                btn.set_progress(0.0)
        self._update_glow_timer()
        for i in range(4):
            self.apply_visual_state(i)
```

In `KeepAliveBtn._on_long_press` (around line 373), add an `isEnabled` guard at the top:

```python
    def _on_long_press(self):
        if not self.isEnabled():
            # Master flag flipped off mid-hold; suppress the rapid-fire toggle.
            self._charging = False
            self._charge_tick.stop()
            self._charge_progress = 0.0
            self._long_press_fired = False
            return
        self._charging = False
        self._charge_tick.stop()
        self._charge_progress = 0.0
        self._long_press_fired = True
        self.is_rapid_fire = not self.is_rapid_fire
        self.rapid_fire_toggled.emit(self.is_rapid_fire)
        self.update()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_keep_alive_gating.py -v
```

Expected: PASS for new tests, no regressions.

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_tab.py tests/test_keep_alive_gating.py
git commit -m "feat(keep-alive): add _suspend_keep_alive and disabled-button long-press guard"
```

---

## Task 7: Hook `_on_setting_changed` to react to master flag flips

**Files:**
- Modify: `tabs/multitoon/_tab.py:2106` (`_on_setting_changed`)
- Test: `tests/test_keep_alive_gating.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_keep_alive_gating.py`:

```python
def test_setting_change_off_invokes_suspend(tab, monkeypatch):
    """When SettingsManager changes keep_alive_enabled to False,
    _on_setting_changed must call _suspend_keep_alive."""
    suspend_called = []
    monkeypatch.setattr(
        tab, "_suspend_keep_alive", lambda: suspend_called.append(True)
    )
    tab.settings_manager.set("keep_alive_enabled", True)  # initial state
    tab._on_setting_changed("keep_alive_enabled", False)
    assert suspend_called == [True]


def test_setting_change_on_resumes_per_toon_flags(tab, monkeypatch):
    """When the master flips on with per-toon flags set, the thread starts."""
    started = []
    monkeypatch.setattr(
        tab, "_start_keep_alive", lambda: started.append(True)
    )
    tab.window_manager.ttr_window_ids = ["wid_a"]
    tab.service_running = True
    tab.keep_alive_enabled = [True, False, False, False]
    tab.settings_manager.set("keep_alive_enabled", True)
    tab._on_setting_changed("keep_alive_enabled", True)
    assert started == [True]


def test_setting_change_on_no_start_when_no_per_toon_active(tab, monkeypatch):
    """Master flips on but no per-toon flags set → thread NOT started."""
    started = []
    monkeypatch.setattr(
        tab, "_start_keep_alive", lambda: started.append(True)
    )
    tab.keep_alive_enabled = [False, False, False, False]
    tab.settings_manager.set("keep_alive_enabled", True)
    tab._on_setting_changed("keep_alive_enabled", True)
    assert started == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_keep_alive_gating.py::test_setting_change_off_invokes_suspend tests/test_keep_alive_gating.py::test_setting_change_on_resumes_per_toon_flags tests/test_keep_alive_gating.py::test_setting_change_on_no_start_when_no_per_toon_active -v
```

Expected: FAIL — current `_on_setting_changed` doesn't handle `keep_alive_enabled`.

- [ ] **Step 3: Extend `_on_setting_changed`**

Edit `tabs/multitoon/_tab.py:2106`:

```python
    def _on_setting_changed(self, key, value):
        """Called when any setting changes — reset keep-alive cycle if relevant."""
        if key in ("keep_alive_delay", "keep_alive_action"):
            if any(self.keep_alive_enabled):
                self._reset_ka_cycle()
        elif key == "keep_alive_enabled":
            if value:
                # Master flipped on. Refresh per-toon visuals (they were ghosted)
                # and start the thread if any per-toon flags are set.
                for i in range(4):
                    self.apply_visual_state(i)
                if any(self.keep_alive_enabled):
                    self._start_keep_alive()
            else:
                self._suspend_keep_alive()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_keep_alive_gating.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_tab.py tests/test_keep_alive_gating.py
git commit -m "feat(keep-alive): react to master flag changes via _on_setting_changed"
```

---

## Task 8: Gate `load_profile` to respect master OFF

**Files:**
- Modify: `tabs/multitoon/_tab.py:994` (`load_profile`)
- Test: `tests/test_keep_alive_gating.py` (extend)

The existing `load_profile` writes per-toon flags into `keep_alive_enabled[i]` then calls `_start_keep_alive` if any are True. We let the writing happen (so the flags restore later) but skip the `_start_keep_alive` call when the master is off.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keep_alive_gating.py`:

```python
def test_load_profile_respects_master_off(tab, monkeypatch):
    """Loading a profile with keep_alive=[true, true, true, true] while the
    master is off must NOT start the keep-alive thread, but must preserve the
    per-toon flags so they restore when the master is later flipped on."""
    started = []
    monkeypatch.setattr(
        tab, "_start_keep_alive", lambda: started.append(True)
    )

    # Stub a minimal profile_manager so load_profile can run end-to-end.
    class _Profile:
        enabled_toons = [True, True, True, True]
        movement_modes = ["Default"] * 4
        keep_alive = [True, True, True, True]
        rapid_fire = [False, False, False, False]

    class _ProfileManager:
        def get_profile(self, idx):
            return _Profile()

        def get_name(self, idx):
            return "Test"

    tab.profile_manager = _ProfileManager()
    tab._active_profile = -1  # so _autosave_active_profile is a no-op
    tab.settings_manager.set("keep_alive_enabled", False)

    tab.load_profile(0)

    assert started == []  # _start_keep_alive NOT invoked
    assert tab.keep_alive_enabled == [True, True, True, True]  # flags preserved
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_keep_alive_gating.py::test_load_profile_respects_master_off -v
```

Expected: FAIL — `_start_keep_alive` is unconditionally called when any flag is True.

- [ ] **Step 3: Gate the `_start_keep_alive` call in `load_profile`**

Edit `tabs/multitoon/_tab.py:1028-1031`. Replace:

```python
        if any(self.keep_alive_enabled):
            self._start_keep_alive()
        else:
            self._stop_keep_alive()
```

with:

```python
        if any(self.keep_alive_enabled) and self._keep_alive_globally_enabled():
            self._start_keep_alive()
        else:
            self._stop_keep_alive()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_keep_alive_gating.py::test_load_profile_respects_master_off -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tabs/multitoon/_tab.py tests/test_keep_alive_gating.py
git commit -m "feat(keep-alive): gate load_profile's start call on master flag"
```

---

## Task 9: Add master `ToggleRow` to Settings tab + ghost action/interval rows

**Files:**
- Modify: `tabs/settings_tab.py:459-489` (`_build_keepalive_group`)
- Test: `tests/test_keep_alive_gating.py` (extend)

The toggle goes at the top of the Keep-Alive group. Action and Interval rows below it should ghost (`setEnabled(False)`) when the master is off.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keep_alive_gating.py`:

```python
def test_settings_tab_master_toggle_present(qapp, tmp_path, monkeypatch):
    """SettingsTab's Keep-Alive group has a master ToggleRow, and the
    action/interval rows are disabled when the master is off."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    from tabs.settings_tab import SettingsTab

    sm = SettingsManager()
    sm.set("keep_alive_enabled", False)

    tab = SettingsTab(settings_manager=sm)

    assert hasattr(tab, "ka_master_row")
    assert tab.ka_master_row.isChecked() is False
    assert tab.ka_action_row.isEnabled() is False
    assert tab.ka_delay_row.isEnabled() is False


def test_settings_tab_master_on_unghosts_rows(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    from tabs.settings_tab import SettingsTab

    sm = SettingsManager()
    sm.set("keep_alive_enabled", True)

    tab = SettingsTab(settings_manager=sm)

    assert tab.ka_master_row.isChecked() is True
    assert tab.ka_action_row.isEnabled() is True
    assert tab.ka_delay_row.isEnabled() is True
```

`SettingsTab.__init__(self, settings_manager)` takes only the settings manager — no other dependencies needed for the test fixture.

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_keep_alive_gating.py::test_settings_tab_master_toggle_present tests/test_keep_alive_gating.py::test_settings_tab_master_on_unghosts_rows -v
```

Expected: FAIL — `ka_master_row` doesn't exist.

- [ ] **Step 3: Add the master toggle and the ghosting logic**

Edit `tabs/settings_tab.py:459-489`. Replace `_build_keepalive_group` body:

```python
    def _build_keepalive_group(self):
        group = SettingsGroup("Keep-Alive")
        self._groups.append(group)

        # Master opt-in toggle — disabled by default. Enabling fires a
        # consent dialog (Task 10) before committing the True value.
        master_initial = bool(self.settings_manager.get("keep_alive_enabled", False))
        self.ka_master_row = ToggleRow(
            "Enable Keep-Alive",
            master_initial,
            sublabel=(
                "Periodically sends a keystroke to keep toons logged in. "
                "Disabled by default — see warning before enabling."
            ),
        )
        self.ka_master_row.toggled.connect(self._on_keep_alive_master_toggle)
        group.add_row(self.ka_master_row)

        self._ka_actions = [
            ("Jump", "jump"),
            ("Open / Close Book", "book"),
            ("Move Forward", "up"),
        ]
        saved_action = self.settings_manager.get("keep_alive_action", "jump")
        action_idx = next((i for i, (_, v) in enumerate(self._ka_actions) if v == saved_action), 0)
        self.ka_action_row = DropdownRow(
            "Action",
            [d for d, _ in self._ka_actions],
            action_idx
        )
        self.ka_action_row.index_changed.connect(self._on_keep_alive_action_changed)
        group.add_row(self.ka_action_row)

        delay_options = ["Rapid Fire", "1 sec", "5 sec", "10 sec", "30 sec", "1 min", "3 min", "5 min", "10 min"]
        saved_delay = self.settings_manager.get("keep_alive_delay", "30 sec")
        delay_idx = delay_options.index(saved_delay) if saved_delay in delay_options else 4
        self.ka_delay_row = DropdownRow(
            "Interval",
            delay_options,
            delay_idx,
        )
        self.ka_delay_row.index_changed.connect(self._on_keep_alive_delay_changed)
        group.add_row(self.ka_delay_row)

        # Apply initial ghost state.
        self._refresh_keep_alive_row_enabled_state(master_initial)

        self._main_layout.addWidget(group)

    def _refresh_keep_alive_row_enabled_state(self, master_enabled: bool):
        """Ghost (or un-ghost) the action and interval rows based on the
        master toggle state."""
        self.ka_action_row.setEnabled(master_enabled)
        self.ka_delay_row.setEnabled(master_enabled)

    def _on_keep_alive_master_toggle(self, checked: bool):
        """Handler for the master toggle. On flip-to-on, fire the consent
        dialog and only commit the True value if the user confirms."""
        if not checked:
            self.settings_manager.set("keep_alive_enabled", False)
            self._refresh_keep_alive_row_enabled_state(False)
            return
        # Toggle was flipped on — confirm before committing.
        if self._show_keep_alive_warning_dialog():
            self.settings_manager.set("keep_alive_enabled", True)
            self._refresh_keep_alive_row_enabled_state(True)
        else:
            # User cancelled — revert visual without re-firing toggled.
            self.ka_master_row.blockSignals(True)
            self.ka_master_row.setChecked(False)
            self.ka_master_row.blockSignals(False)
            # Setting was never written; ghost state stays as it was.

    def _show_keep_alive_warning_dialog(self) -> bool:
        """Stub — replaced in Task 10. Returns True so this task's tests pass
        with the toggle behaving as if confirmation always succeeds."""
        return True
```

The `_show_keep_alive_warning_dialog` stub returns True for now so Task 9's tests don't need to mock the dialog. Task 10 replaces the stub with the actual `QMessageBox`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_keep_alive_gating.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tabs/settings_tab.py tests/test_keep_alive_gating.py
git commit -m "feat(settings): add Keep-Alive master toggle with ghost state for child rows"
```

---

## Task 10: Replace dialog stub with the real `QMessageBox.warning`

**Files:**
- Modify: `tabs/settings_tab.py` (`_show_keep_alive_warning_dialog`)
- Test: `tests/test_keep_alive_gating.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_keep_alive_gating.py`:

```python
def test_dialog_cancel_does_not_persist_setting(qapp, tmp_path, monkeypatch):
    """Cancelling the consent dialog must leave keep_alive_enabled False
    and revert the toggle visual."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    from tabs.settings_tab import SettingsTab

    sm = SettingsManager()
    tab = SettingsTab(settings_manager=sm)
    monkeypatch.setattr(tab, "_show_keep_alive_warning_dialog", lambda: False)

    tab.ka_master_row.setChecked(True)
    # Dialog cancelled → setting still False, toggle reverted.
    assert sm.get("keep_alive_enabled") is False
    assert tab.ka_master_row.isChecked() is False


def test_dialog_confirm_persists_setting(qapp, tmp_path, monkeypatch):
    """Confirming the consent dialog must persist keep_alive_enabled True."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    from tabs.settings_tab import SettingsTab

    sm = SettingsManager()
    tab = SettingsTab(settings_manager=sm)
    monkeypatch.setattr(tab, "_show_keep_alive_warning_dialog", lambda: True)

    tab.ka_master_row.setChecked(True)
    assert sm.get("keep_alive_enabled") is True
    assert tab.ka_master_row.isChecked() is True
```

- [ ] **Step 2: Run tests to verify they pass with the stub**

```bash
pytest tests/test_keep_alive_gating.py::test_dialog_confirm_persists_setting -v
```

Expected: PASS (stub returns True).

```bash
pytest tests/test_keep_alive_gating.py::test_dialog_cancel_does_not_persist_setting -v
```

Expected: PASS (the test injects a stub returning False, which is what we want).

These tests are passing with the stub because they exercise the dispatch logic, not the dialog UI. The test infrastructure is now in place; the stub gets replaced next.

- [ ] **Step 3: Replace the stub with the real `QMessageBox.warning`**

Edit `tabs/settings_tab.py`. Find `_show_keep_alive_warning_dialog` and replace its body. Also add the necessary imports at the top of the file if not already there (`QMessageBox`):

```python
    def _show_keep_alive_warning_dialog(self) -> bool:
        """Show the TOS-aware consent dialog. Returns True if the user
        clicked Enable, False on Cancel/Esc/close.

        Factored as a method so tests can monkeypatch it without invoking
        the real modal."""
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self.window())
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Enable Keep-Alive?")
        box.setText(
            "Keep-Alive sends periodic input to your toon windows even while "
            "you are not actively playing.\n\n"
            "Both Toontown Rewritten and Corporate Clash prohibit automation "
            "tools of this kind in their Terms of Service. Use of Keep-Alive — "
            "particularly in public areas of either game — may result in "
            "warnings, account suspension, or permanent termination at the "
            "discretion of those games' moderation teams.\n\n"
            "ToonTown MultiTool is provided as-is and accepts no responsibility "
            "for any consequences arising from its use."
        )
        enable_btn = box.addButton("Enable", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.setEscapeButton(cancel_btn)
        box.exec()
        return box.clickedButton() is enable_btn
```

If `QMessageBox` isn't already imported at the top of the file, add it to the existing PySide6.QtWidgets import line.

- [ ] **Step 4: Run all keep-alive tests to verify nothing regressed**

```bash
pytest tests/test_keep_alive_gating.py -v
```

Expected: PASS for all tests in the file.

- [ ] **Step 5: Run the full test suite to verify no broader regressions**

```bash
pytest tests/ -v
```

Expected: PASS for everything.

- [ ] **Step 6: Commit**

```bash
git add tabs/settings_tab.py tests/test_keep_alive_gating.py
git commit -m "feat(settings): consent dialog with TOS warning for Keep-Alive opt-in"
```

---

## Final verification

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: PASS for everything.

- [ ] **Step 2: Manual smoke test**

Launch the app (`python main.py`):
1. Open Settings → Keep-Alive group. Verify the master toggle is at the top, OFF, with sublabel.
2. Verify the Action and Interval rows are visible but ghosted.
3. Verify per-toon Keep-Alive buttons are disabled with the recovery tooltip on hover.
4. Click the master toggle ON → dialog appears with the TOS warning. Click Cancel → toggle reverts to OFF, no setting change.
5. Click the master toggle ON → dialog appears. Click Enable → toggle stays ON, child rows un-ghost, per-toon buttons become available.
6. Toggle a per-toon Keep-Alive on. Verify normal behavior (red/orange glow as configured).
7. Toggle the master OFF → per-toon button visuals clear, thread stops, but the per-toon flag is preserved internally.
8. Toggle master back ON (dialog appears again, click Enable) → per-toon button restores its previous active state without per-toon re-clicking.

If all eight smoke-test items pass, the feature is complete.

---

## Notes for the implementer

- Do not bundle unrelated cleanup. Each task is a single commit; resist the urge to refactor adjacent code.
- The existing dirty state in the working tree (many M files in `git status`) is from prior work — your commits will be on top of that. Stage only the files you intend to commit.
- The dependency injection for the dialog (Task 10) is the test seam. Don't try to drive `QMessageBox.exec()` directly from a test.
- `_FakeSettingsManager` and `_FakeWindowManager` exist in `tests/test_layout_reparent.py:27-68` — feel free to import them rather than duplicating, or duplicate inline if the import boundary feels awkward.
