# Keep-Alive Opt-In — Design

**Date:** 2026-05-03
**Status:** Spec — pending implementation
**Scope:** TOS-compliance gating for the Keep-Alive (and Rapid-Fire) features.

## Background

The MultiTool currently runs Keep-Alive (a periodic keystroke that prevents toons from being logged out for inactivity) by default whenever a user toggles it on per-slot. Both Toontown Rewritten and Corporate Clash forbid automation tools of this kind in their Terms of Service:

- **TTR TOS (Version 6, June 25 2025):** *"Using automation systems, tools, or third-party software to control the game. You may, however, use programs to provide 'multi-Toon' control functionality, provided it has no other tools or functions included in the program, or if the extra prohibited functions are able to be disabled."* — multi-toon control is allowed; auto-fired automation is allowed only if it's disable-able.
- **Corporate Clash In-Game Rules:** *"The use of third-party software is prohibited, with the exception of multi-toon controllers. This includes, but is not limited to, fishing macros, keyboard macro software, **and Keep Alive**."* — Keep-Alive is named as prohibited.

Pure user-driven multi-toon mirroring (relaying live keystrokes across windows) is the explicit allowed carve-out for both games. Keep-Alive and Rapid-Fire are the only features in this app that fire input without a corresponding live user keystroke; nothing else needs TOS gating.

## Goals

1. Make Keep-Alive opt-in. Default off for all users on every install.
2. When the user opts in, present an explicit informed-consent warning dialog citing the TOS risk before committing the setting.
3. While opted out, the per-toon Keep-Alive buttons must be visibly disabled and incapable of starting Keep-Alive cycles.
4. Apply the gate uniformly across both TTR and CC slots — the user accepts the CC risk explicitly via the consent dialog.
5. Cleanly stop any in-flight Keep-Alive when the user opts back out.
6. Preserve users' previously-saved per-toon Keep-Alive selections so they don't have to re-configure when they re-enable.

## Non-goals

- No per-game opt-in (single global toggle covers both games).
- No per-toon consent flow (the global toggle is the consent gate).
- No "don't show this again" checkbox in the dialog (each opt-in re-shows the warning by design).
- No proactive onboarding prompt at first launch — the feature is invisible until the user goes looking for it in Settings.
- No changes to the existing tooltip pattern on other per-toon buttons (a separate UX cleanup pass if desired).

## UX flow

### Settings → Keep-Alive group

The existing `SettingsTab._build_keepalive_group` adds a master toggle at the top of the group. Layout:

```
┌──────────────────────────────────────────────────────────────┐
│  Keep-Alive                                                  │
├──────────────────────────────────────────────────────────────┤
│  Enable Keep-Alive                                    [ ⏵ ]  │
│  Periodically sends a keystroke to keep toons logged in.     │
│  Disabled by default — see warning before enabling.          │
│  ─────────────────────────────────────────────────────────   │
│  Action                          [ Jump          ▾ ]         │   ◄ ghosted when toggle off
│  Interval                        [ 30 sec        ▾ ]         │   ◄ ghosted when toggle off
└──────────────────────────────────────────────────────────────┘
```

- Master toggle uses the existing `ToggleRow` widget with a multi-line sub-label.
- Action and Interval `DropdownRow`s remain visible at all times but call `setEnabled(False)` (Qt's default ~50% opacity disabled treatment) when the master toggle is off.
- The toggle visually flips immediately on click (optimistic). If the confirmation dialog is cancelled, the toggle reverts via `setValue(False)` with signals blocked to avoid recursion.

### Confirmation dialog (toggle OFF → ON only)

Fires after the optimistic flip, before the setting is committed. `QMessageBox.warning` parented to the main window.

- **Title:** `Enable Keep-Alive?`
- **Body** (three short paragraphs, separated by blank lines):

  > Keep-Alive sends periodic input to your toon windows even while you are not actively playing.
  >
  > Both Toontown Rewritten and Corporate Clash prohibit automation tools of this kind in their Terms of Service. Use of Keep-Alive — particularly in public areas of either game — may result in warnings, account suspension, or permanent termination at the discretion of those games' moderation teams.
  >
  > ToonTown MultiTool is provided as-is and accepts no responsibility for any consequences arising from its use.

- **Buttons:** `Cancel` (default focus, Esc key, `RejectRole`) and `Enable` (`DestructiveRole`).
- Window-close (X) and Esc behave the same as Cancel.

### Per-toon Keep-Alive button

| Conditions | Button state |
|---|---|
| `keep_alive_enabled` setting is `False` | `setEnabled(False)`. Tooltip: *"Keep-Alive is disabled. Enable it in Settings → Keep-Alive."* Existing pressed-feedback animation suppressed by Qt's disabled handling. |
| Setting `True`, service running, window detected, KA off for this toon | Existing idle styling, tooltip: *"Toggle keep-alive for this toon"* (unchanged). |
| Setting `True`, service running, window detected, KA on for this toon | Existing active styling (red glow + progress bar). |
| Setting `True`, rapid-fire on for this toon | Existing rapid-fire styling. |

The disabled-state tooltip is the only new tooltip added by this work. The existing enabled-state tooltip on `KeepAliveBtn` is preserved for consistency with all other per-toon buttons in the row.

## Architecture

### State

| State | Storage | Default | Notes |
|---|---|---|---|
| `keep_alive_enabled` (master toggle) | `SettingsManager` → `~/.config/toontown_multitool/settings.json` | `False` | New key. Added to `SettingsManager.__init__` defaults dict. |
| `keep_alive_enabled[i]` (per-toon) | `MultiToonTab` runtime + `ProfileManager` per-profile | unchanged | Existing. Preserved across opt-out/opt-in cycles. |
| `rapid_fire_enabled[i]` (per-toon) | `MultiToonTab` runtime + `ProfileManager` per-profile | unchanged | Existing. Cleared together with `keep_alive_enabled[i]` on opt-out. |
| `keep_alive_action`, `keep_alive_delay` | `SettingsManager` | unchanged | Existing. UI rows ghost when master is off. |

### Gating points

The new master flag is consulted in three places:

1. **`MultiToonTab.toggle_keep_alive(index)`** — early-return if the master flag is `False`. Defensive against programmatic calls (e.g. from `load_profile`).
2. **`MultiToonTab.apply_visual_state(index)`** — the per-toon button's `setEnabled(...)` call AND-s in `self._keep_alive_globally_enabled()`. Tooltip selection priority (first match wins):
   - Master flag is `False` → *"Keep-Alive is disabled. Enable it in Settings → Keep-Alive."*
   - Otherwise → existing tooltip behavior (the generic *"Toggle keep-alive for this toon"* and any state-specific overrides currently in `_apply_keep_alive_btn_style`).

   Service-stopped or no-window disables fall through to the existing tooltip — the user already knows the service is off because the master service button reflects it; the master-flag tooltip is the only new addition.
3. **Keep-alive thread loop** — checks `self.settings_manager.get("keep_alive_enabled")` at the top of each burst cycle. Defense-in-depth against race conditions where the master flag flips while the thread is mid-iteration. Worst case is one in-flight keystroke completes after the toggle flips — not user-visible, not exploitable.

### Helpers

A small new helper on `MultiToonTab`:

```python
def _keep_alive_globally_enabled(self) -> bool:
    return bool(self.settings_manager and self.settings_manager.get("keep_alive_enabled", False))
```

A new helper for opt-out that **stops the thread and clears visuals but preserves per-toon flags**:

```python
def _suspend_keep_alive(self):
    """Stop KA execution and clear button visuals while preserving per-toon flags.
    Called when the master toggle flips off — per-toon setup is the user's, the
    master flag is just whether the feature class is enabled at all."""
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

`keep_alive_enabled[i]` and `rapid_fire_enabled[i]` are deliberately *not* zeroed. They represent the user's per-toon configuration; the master flag's job is to gate execution and visuals, not to discard configuration. When the master flips back on, `apply_visual_state` re-renders the buttons with their preserved per-toon state and `_start_keep_alive` runs naturally if any are True.

`apply_visual_state` checks the master flag first and forces `setEnabled(False)` + neutral styling when off, regardless of `keep_alive_enabled[i]`. This gives a single source of truth: master flag controls availability, per-toon flag controls preference within available state.

The existing `disable_all_toon_controls()` (called on service stop, line ~1782) keeps its current behavior — it intentionally clears per-toon flags because the service stopping is a stronger signal than the master toggle (windows are gone, the previous setup may not match the next service-start state).

### Settings → MultiToonTab wiring

`MultiToonTab._on_setting_changed` is already registered as a callback on `SettingsManager.on_change` at `_tab.py:738`. We add a branch:

```python
def _on_setting_changed(self, key, value):
    # ... existing branches ...
    if key == "keep_alive_enabled":
        if value:
            # Master flipped on. Per-toon flags (preserved across the off period
            # or restored from a freshly-loaded profile) drive the visual state
            # and execution naturally via apply_visual_state.
            for i in range(4):
                self.apply_visual_state(i)
            if any(self.keep_alive_enabled):
                self._start_keep_alive()
        else:
            self._suspend_keep_alive()
```

The settings tab handles its own ghosting of the action/interval rows via the same callback (or a local listener).

### Dialog placement

In `SettingsTab`:

```python
def _on_keep_alive_master_toggle(self, checked: bool):
    if not checked:
        self.settings_manager.set("keep_alive_enabled", False)
        return
    if self._show_keep_alive_warning_dialog():
        self.settings_manager.set("keep_alive_enabled", True)
    else:
        # Cancelled — revert visual without re-firing toggled signal.
        self.ka_master_row.blockSignals(True)
        self.ka_master_row.set_value(False)
        self.ka_master_row.blockSignals(False)

def _show_keep_alive_warning_dialog(self) -> bool:
    """Return True if the user clicked Enable, False if they cancelled."""
    box = QMessageBox(self.window())
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Enable Keep-Alive?")
    box.setText(...)  # body string from microcopy table
    enable_btn = box.addButton("Enable", QMessageBox.DestructiveRole)
    cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(cancel_btn)
    box.setEscapeButton(cancel_btn)
    box.exec()
    return box.clickedButton() is enable_btn
```

The dialog method is kept as its own function so tests can monkeypatch / inject a stub.

## Migration

### Existing users

- `keep_alive_enabled` is absent from existing `settings.json` files. The default `False` from `SettingsManager.__init__` applies — feature is off after upgrade.
- Saved per-profile `keep_alive: [true, ...]` arrays remain on disk untouched. They are suppressed at runtime while the master flag is off.
- When the user goes to Settings, accepts the dialog, and the master flag flips to `True`, the per-toon flags from the active profile resume taking effect. The user's previous configuration is restored without per-toon re-clicking.

This restoration is not a one-time migration step — it's the steady-state behavior. Per-toon flags are sacred; the master flag only gates whether they execute. Returning users on upgrade and current users toggling the master off-then-on both go through the same code path.

### Profile load while master is off

`MultiToonTab.load_profile` currently writes per-toon flags onto `keep_alive_enabled[i]` and calls `_start_keep_alive()` if any are `True`. After the change:

- The per-toon flags are still written internally so they restore correctly when the master flag is re-enabled.
- `_start_keep_alive()` and the calls into `apply_visual_state` see the master flag is `False` and gate accordingly. No keystrokes are sent.

### Downgrade

Older builds (pre-change) ignore `keep_alive_enabled` and read per-profile flags directly. This restores the old always-on behavior. Not actively handled — out of scope.

## Edge cases

| Case | Behavior |
|---|---|
| Master flipped OFF mid-burst | Thread checks the flag at the top of each burst; subsequent bursts are skipped. At most one in-flight keystroke completes. |
| Master flipped OFF mid-long-press on a per-toon button | `KeepAliveBtn._on_long_press` early-returns if `not self.isEnabled()`. The press timer / tick timer run to completion harmlessly. |
| User Cancels the dialog | Toggle reverts via `setValue(False)` with signals blocked; setting is never written. |
| User Esc / closes the dialog window | Same as Cancel (mapped via `setEscapeButton`). |
| Profile load tries to restore `keep_alive: [true, true, true, true]` while master is OFF | Per-toon flags are set internally but `_start_keep_alive` is skipped because the master gate returns False. Buttons render disabled. |
| Service stopped while master is ON | Per-toon buttons disable due to existing `service_running` gate. Master toggle stays as-is; re-starting the service re-enables them. |
| Master flag set externally (manual `settings.json` edit) | `SettingsManager._load` populates the value at startup. Initial `apply_visual_state` calls see the value. No special handling. |
| Two toons with KA active when user disables master | `_suspend_keep_alive()` stops the thread and clears button visuals. Per-toon flags remain in memory and in the saved profile so the user's setup is preserved on the next opt-in. |

## Testing

All tests live under `tests/`. PySide6's `QApplication` is already initialized for the existing test suite.

| Test | Verifies |
|---|---|
| `test_keep_alive_master_default_off` | Fresh `SettingsManager` returns `False` for `keep_alive_enabled`. |
| `test_per_toon_button_disabled_when_master_off` | After service start + window detected, KA button has `isEnabled() == False` and tooltip contains "Settings". |
| `test_per_toon_button_enabled_when_master_on` | Master flag True + service running + window present → KA button is enabled. |
| `test_master_off_preserves_per_toon_flags` | Set per-toon `keep_alive_enabled[i]=True`, flip master OFF, assert thread is stopped AND per-toon flags are still True (preserved for next opt-in). |
| `test_master_on_after_off_resumes_per_toon_state` | After the previous test's setup, flip master ON. Assert `_start_keep_alive` is running and per-toon flags drive the buttons' active visual state. |
| `test_master_off_stops_running_thread` | Start KA cycle on a toon, flip master OFF, assert thread terminates within bounded time (event-driven, not sleep-based). |
| `test_dialog_cancel_does_not_persist_setting` | Stub `_show_keep_alive_warning_dialog` to return False, simulate toggle click → assert setting still False, toggle visual reverted. |
| `test_dialog_confirm_persists_setting` | Stub returns True → assert setting True, toggle visual stays on. |
| `test_profile_load_respects_master_off` | Load a profile with `keep_alive: [true, true, true, true]` while master is OFF. Assert `_start_keep_alive` not invoked, buttons disabled, but per-toon flags preserved. |
| `test_keep_alive_thread_checks_master_each_cycle` | Mock keystroke send. Master ON, thread sends. Flip master OFF mid-cycle. Assert subsequent cycles don't send. |
| `test_long_press_no_op_when_button_disabled` | Programmatically simulate the press/release timing on a disabled `KeepAliveBtn`. Assert `is_rapid_fire` stays False. |
| `test_first_opt_in_after_upgrade_restores_profile_flags` | Simulate an upgrade scenario: settings.json missing the master key (defaults False); profiles.json has `keep_alive: [true, true, true, true]` for the active profile. After app start, flip master to True via the dialog. Assert per-toon flags from the profile are honored and `_start_keep_alive` is running. |
| `test_action_interval_rows_ghost_when_master_off` | Settings tab: master OFF → action and interval `DropdownRow`s have `isEnabled() == False`. |

The dialog tests use dependency injection (stub `_show_keep_alive_warning_dialog`) rather than `QTest`-driven modal interaction. Less flaky.

## Files changed (summary)

| File | Change |
|---|---|
| `utils/settings_manager.py` | Add `"keep_alive_enabled": False` to defaults dict. |
| `tabs/settings_tab.py` | Add master `ToggleRow` to `_build_keepalive_group`, the toggle handler, the dialog method, the ghosting of action/interval rows. |
| `tabs/multitoon/_tab.py` | Add `_keep_alive_globally_enabled()` helper, `_suspend_keep_alive()` helper. Gate `toggle_keep_alive`, `apply_visual_state`'s KA-button enable/tooltip, and the keep-alive thread loop. Hook the new setting into `_on_setting_changed`. Update `KeepAliveBtn._on_long_press` to no-op when disabled. |
| `tests/test_keep_alive_gating.py` (new) | All tests listed above. |

No widget-level visual changes other than ghosting and one new tooltip string — no theme work, no layout changes.
