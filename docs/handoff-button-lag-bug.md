# Handoff: Intermittent button-click lag in Multitoon tab

> **For the next LLM:** I (the previous Claude session) failed to fix this bug. The user explicitly cut me off after multiple unsuccessful attempts. **Take everything in the "What I believe is the issue" section with a grain of salt** — my track record on this issue is poor. I formed several hypotheses, each looked compelling, each fix made other things better but did not solve the symptom the user is reporting. The data I gathered is reliable; my interpretation of it is what kept being wrong.

## The bug, exactly as reported

> "the first time you hit the Enable button to disable a toon (after starting the service), the button visually flips to the disabled state instantly, but the UI then freezes for ~2 seconds before you can click it again. After that first click, every subsequent toggle is instant. Only happens once service is running."

Reproducer:
1. Launch app from terminal: `python main.py` (so `print` instrumentation is visible).
2. App starts in compact mode, ~575×740.
3. Have at least one TTR or Corporate Clash window open. (User has 2 windows in their reproducer logs.)
4. Click "Start Service" — service starts, both toons auto-enable, "Enabled" green buttons.
5. Click the green "Enabled" button on slot 0 to disable. **Visual updates instantly** to gray "Enable", **but the app freezes for ~2 seconds**. During the freeze, clicks on other widgets do not register.
6. After the freeze, clicks are instant. Subsequent toggle-on / toggle-off cycles run in single-digit milliseconds.

Repro is reliable: every fresh launch shows the freeze on the first disable, never on subsequent.

User's environment: Fedora 44, Linux 6.19.14-300, KDE on **Wayland** (xwayland for X11 apps). PySide6 / Qt 6, Python 3.14.

## What the data clearly shows (this part is reliable)

`toggle_toon` itself is fast. With instrumentation in place:

```
[PERF] toggle_toon ENTER  index=0  new_state=False
[PERF] toggle_toon EXIT   func=7ms  drain=9ms  total=15ms      ← function returns in 15ms total
[PERF] assign_windows  thread=poll  ids=2  took=92ms
[STALL] event loop blocked for 2094ms                          ← ~2s freeze AFTER function returns
[PERF] toggle_toon ENTER  index=0  new_state=True              ← user finally clicks again
```

The `drain` field above is `QApplication.processEvents()` called at the end of `toggle_toon`. Drain returns in 9ms, so all events queued by `toggle_toon` are processed quickly. But Qt re-blocks the main thread for ~2 seconds *after* the function returns and after that one drain.

The freeze persists even when `apply_visual_state(index)` is **commented out** of `toggle_toon` (test run; see "Tried 5" below). Function ran in 1ms, drain in 1ms, still got `[STALL] event loop blocked for 2032ms`. So the cost is **not** in the toon-button stylesheet cascade.

The freeze is on the main thread holding the **Python GIL**. We know this because the `window_manager._poll_loop` thread (a separate Python thread that prints `[PERF] assign_windows  thread=poll ...`) was unable to print *during* the stall — its prints came out only after the stall ended. Python threads can't print while another holds the GIL.

So: during the 2s freeze, **some Python code is running on the main thread**. Nothing my instrumentation logged. It's something Qt is invoking via a slot/event handler that I haven't yet wrapped with timing.

The freeze fires once per session. Subsequent identical actions are sub-frame. Strong "first-time setup cost" signature.

## What I believe is the issue (low confidence — my hypotheses kept being wrong)

The most likely candidates given the GIL-held-on-main signature, and the "fires once, then everything is fast" pattern:

1. **A queued-connection signal handler that does heavy first-time work.** Qt cross-thread signals are queued; the handler runs on the next event-loop cycle. If a signal fires from a service-side thread shortly after the user's click, its handler runs on main, holds the GIL, and freezes the UI. Candidates connected on `_tab.py`:
   - `input_service.chat_state_changed` → `_on_chat_state_changed` (calls `apply_visual_state` on **all 4 toons**, plus `setGraphicsEffect(None)` on chat buttons)
   - `input_service.input_log` → `_on_input_log`
   - `window_manager.window_ids_updated` → `update_toon_controls` (heavy; iterates 4 slots, sets multiple stylesheets per slot, kicks off TTR API fetches)
   - `_toon_data_merge_ready` → `_apply_merged_toon_data` (sets DNA on slot badges → spawns portrait fetch threads)
   - `_image_ready` on each `SlotBadge` → `_on_image_ready` (does **`QPixmap.loadFromData`**, which decodes PNGs synchronously on main thread — this is a known slow operation for first-time-decode of a non-trivial image, and the four portrait fetches are running threads at exactly this point in the lifecycle)

   The `_on_image_ready` path is my **strongest specific suspicion** but I never confirmed it. Subsequent `set_dna` calls with the same DNA string short-circuit (early return at `if dna == self._dna: return`), so the cost is paid exactly once per session. That fits the "first time only" pattern perfectly.

2. **First-time stylesheet polish on a widget tree I haven't profiled.** Qt's CSS engine compiles + polishes lazily. The first apply of a particular variant is expensive. I bisected away `apply_visual_state` and the freeze remained, but there are other paths that call `setStyleSheet` (notably the per-toon styling inside `update_toon_controls` and the chat-button styling in `_on_chat_state_changed`).

3. **Compositor / Wayland sync.** Less likely given the GIL-held signature. KWin on Wayland adds latency for some operations, but that wouldn't explain Python threads being unable to print.

## What I tried (in order, with why each one was wrong)

### Tried 1 — Removed cross-fade `QGraphicsOpacityEffect` from layout swaps
**Code:** `main.py:_set_layout_mode` rewritten to instant-snap.
**Why I thought it would work:** the `QGraphicsOpacityEffect` forces software-render of the whole multitoon-tab subtree on every swap. First application is multi-second slow. Per-swap cost was real and measurable.
**Result:** Fixed a *different* bug (titlebar drag was laggy). Didn't fix this one.

### Tried 2 — Stopped re-applying `apply_all_visual_states` on every layout swap
**Code:** `tabs/multitoon/_tab.py:set_layout_mode` no longer calls `apply_all_visual_states`. Replaced with targeted `_full.apply_theme(c) + _sync_full_cards_to_state()` only when entering Full mode.
**Why I thought it would work:** `apply_visual_state` is ~10× slower with service running because it sets more stylesheets. Saved 30ms per swap.
**Result:** Compact↔full swaps are now fast. Did not fix the Enable-button freeze.

### Tried 3 — Removed `service_running` from `_update_glow_timer`'s "needs glow" condition
**Code:** `tabs/multitoon/_tab.py:_update_glow_timer`. The 50ms glow timer used to fire whenever the service was on, even with no keep-alive enabled, scheduling `update()`s on all 4 keep-alive buttons every tick.
**Why I thought it would work:** ~80 paintEvents/sec scheduled while service was running.
**Result:** Helped in isolation; did not fix the Enable-button freeze.

### Tried 4 — Made `KeepAliveBtn.set_progress` and `SmoothProgressBar.set_progress` idempotent
**Code:** `tabs/multitoon/_tab.py` and `utils/shared_widgets.py`. Both now early-return if value didn't change.
**Why I thought it would work:** Reduces unnecessary `update()` calls.
**Result:** Defensive improvement; did not fix the freeze.

### Tried 5 — Removed `assign_windows()` from main-thread call sites
**Code:** Three places now no longer run `assign_windows()` on the main thread:
- `_auto_refresh` (was running every 5s on the GUI thread, calling `xdotool` subprocesses synchronously)
- `enable_detection` (was synchronous on the caller's thread on service start)
- `manual_refresh` (was synchronous on click)
The `window_manager._poll_loop` thread keeps assigning windows every 2s in its own thread.
**Why I thought it would work:** xdotool subprocesses on Wayland can take seconds. Confirmed via `[PERF] assign_windows thread=MAIN took=120ms+` lines in instrumentation.
**Result:** Layout swaps are now instant. **User reported `compact↔full lag is fixed`.** Did not fix the Enable-button freeze.

### Tried 6 — Bisected by removing `apply_visual_state` from `toggle_toon`
**Code:** Commented out `self.apply_visual_state(index)` inside `toggle_toon`.
**Result:** **Freeze persisted (`[STALL] 2032ms`).** This rules out the toon button's stylesheet cascade as the cause. (Restored after the test.)

### Tried 7 — `faulthandler.dump_traceback_later` to capture the main-thread stack DURING the freeze
**Code:** `tabs/multitoon/_tab.py:toggle_toon` calls `faulthandler.dump_traceback_later(0.8, repeat=True, file=sys.stderr)` at function entry.
**Why this should have worked:** `faulthandler` runs in a watchdog thread at the C level — it can dump the main thread's Python stack even while the main thread holds the GIL. If main thread is busy 0.8s after click, we see exactly what function is running.
**Result:** **The user reported "same behavior".** I do not have the dump output — either the user did not capture it / it did not appear in their paste, or it did fire and they cut the conversation before sharing.

> **This is the next thing to try.** Verify the `faulthandler.dump_traceback_later` call is actually in place (it currently is, inside `toggle_toon` at the top of the function — see "Current code state" below). Then capture stderr output during the click. The dumps will print Python stack frames showing which function is running on the main thread at 0.8s, 1.6s, 2.4s past the click. That points directly at the cause.

## Current code state (instrumentation that's still live and needs cleanup once fixed)

The branch is `multitoon-full-ui`. Working-tree changes from `main` include real fixes mixed with diagnostic instrumentation. **Before merging, the diagnostic instrumentation needs to be removed.**

### Diagnostic instrumentation currently in place (remove when done)

`tabs/multitoon/_tab.py`:
- **`toggle_toon` (~line 1709)**: timing wrapper, `faulthandler.dump_traceback_later(0.8, repeat=True, file=sys.stderr)` at entry, `QApplication.processEvents()` and timing print at exit. **The dump is the next diagnostic step — keep it active until the cause is found.**
- **`update_toon_controls` (~line 1781)**: timing wrapper, prints `[PERF] update_toon_controls  ids=…  changed=…  enabled_before=…` at entry and `enabled_after=…  took=…ms` at exit.
- **`_stall_timer` (~line 715)**: 100ms QTimer that logs `[STALL] event loop blocked for Nms` whenever its tick gap exceeded 150ms. Genuinely useful — keep it during diagnosis.

`services/window_manager.py`:
- **`assign_windows` (~line 121)**: timing wrapper, prints `[PERF] assign_windows  thread=MAIN|poll  ids=N  took=Nms` either when the thread is main (any duration) or duration > 50ms.

### Real fixes that should stay (these resolved separate bugs)

`main.py`:
- `_set_layout_mode` no longer animates — instant snap. Keep.
- Removed `_layout_swap_animated_once`, `_prewarm_paint_caches` related code from earlier; current state has a simple `_set_layout_mode`. (Earlier in the session a `QTimer.singleShot(150, self._prewarm_paint_caches)` lived in `__init__` for first-paint warming — verify whether that's still relevant. Consider keeping if the launch→full-UI lag returns.)

`tabs/multitoon/_tab.py`:
- `set_layout_mode` no longer calls global `refresh_theme`. Replaced with `_full.apply_theme(c) + _sync_full_cards_to_state()` for Full mode. Keep.
- `_sync_full_cards_to_state` (new method, ~line 880): mirrors active-window state into the Full UI cards without the stylesheet cascade. Keep.
- `_update_glow_timer`: removed `service_running` from `needs_glow`. Keep.
- `_tick_glow`: only touches `keep_alive_enabled` buttons (skips disabled ones each tick). Keep.
- `toggle_keep_alive`: now clears progress + graphics effect on the just-disabled button. Keep.
- `toggle_keep_alive`: also calls `apply_visual_state(index)` at end (was a separate regression I fixed). Keep.
- `_auto_refresh`: no longer calls main-thread `assign_windows`. Keep.
- `toggle_service` start path: no redundant `assign_windows` call. Keep.
- `manual_refresh`: no main-thread `assign_windows`. Keep — but UX implication: window list refreshes within ~2s instead of immediately.

`tabs/multitoon/_full_layout.py`:
- `_FullToonCard._STATE_COLORS` and `set_status_state` / `_apply_status_state`: 4-state model for Full UI status indicator (`active` / `keep_alive` / `disabled` / `off`) matching compact's PulsingDot. Keep.
- `_StatusIndicator.set_dot_color` helper. Keep.
- `_FullToonCard.set_active(True)` calls `_layout_active_content` (fix for "card content tiny when activating after maximize"). Keep.
- `_GridContainer.resizeEvent` skips `_position_cards()` when not visible. Keep.

`services/window_manager.py`:
- `enable_detection` no longer calls `assign_windows()` synchronously. Keep.

`utils/shared_widgets.py`:
- `SmoothProgressBar.set_progress` is idempotent. Keep.

`tests/test_layout_reparent.py`:
- New regression tests for Full UI status state, card layout activation, and keep-alive dot. Keep.

### Version bump
`main.py:104` `APP_VERSION = "2.1"` (deliberately two-part — user wants `2.1` not `2.1.0`). `services/cc_login_service.py` and `services/ttr_login_service.py` have `User-Agent: ToontownMultiTool/2.1`. Keep.

## Suggested next steps for the next LLM

1. **Capture faulthandler output.** Have the user run `python main.py 2>&1 | tee click-trace.log`, click Enable to disable once after starting service, paste the file contents (especially anything after `[PERF] toggle_toon ENTER`). Look for `Thread 0x...` blocks — the one for the main thread will name the function holding the GIL.

2. **If faulthandler shows `_apply_merged_toon_data` or `_on_image_ready`:** The fix is to move PNG decoding off the main thread. `QPixmap.loadFromData` on a multi-KB PNG is several hundred ms. With 4 portraits decoding in sequence on main, you get 1-2s. Decode in the worker thread; emit the already-decoded `QImage` (which is thread-safe to construct) and convert to QPixmap on main (cheap).

3. **If faulthandler shows `update_toon_controls` or `apply_visual_state`:** Bisect inside the function with intermediate timing. Look for setStyleSheet calls on rarely-applied variants.

4. **If faulthandler shows `_on_chat_state_changed`:** That handler calls `apply_visual_state` on all 4 toons, plus `setGraphicsEffect(None)` on every chat button. First-time work × 4. The trigger is the input service detecting chat state — possibly a spurious emission on toon-disable.

5. **If faulthandler shows nothing useful (idle / Qt internal):** Then the freeze is in C code, not Python. Likely Wayland/KWin compositor issue or Qt's deferred polish. Try `QT_LOGGING_RULES="qt.qpa.*=true"` to see Wayland events. Also try `QT_QPA_PLATFORM=xcb` to force X11 — if the freeze disappears on X11, the issue is xwayland/Wayland-specific.

6. **Don't trust my optimizations blindly.** Specifically: I removed `assign_windows()` from `enable_detection()` and from `toggle_service` start-path on the theory the poll thread covers it within 2s. The user accepted this, but it does mean a 1-2s delay before windows show after starting the service. Verify this isn't causing other UX regressions.

## Honest self-assessment

I had clear, reliable instrumentation data (timestamps, thread IDs, GIL-held signature) and still picked the wrong target three times in a row before the user lost patience. The pattern of my failure: I jumped to fixes from each piece of evidence without finishing the diagnostic loop. The right next step (faulthandler dumps) was the seventh thing I tried, when it should have been earlier — once we knew main-thread Python code was running but no instrumented function was logging, the conclusion "I haven't instrumented enough places" should have come immediately.

If you're picking this up: do step 1 above before changing any code. Get the stack dump. Then there's only one place to look.
