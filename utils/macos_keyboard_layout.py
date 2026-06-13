"""Keep pynput's macOS keyboard listener off the Text-Input-Source (TIS) APIs.

macOS requires Text-Input-Source / TSM input-source APIs to be called on the
MAIN thread in a GUI app. pynput's keyboard listener (`Listener._run`) fetches
the current keyboard layout via `keycode_context()` ON ITS BACKGROUND LISTENER
THREAD; on macOS that traps fatally (SIGTRAP via
`dispatch_assert_queue` -> `islGetInputSourceListWithAdditions`) around
input-source / window-focus transitions (the same crash class fixed by moving
TIS work to the main thread in XQuartz #40 and input-leap #2275).

Fix: fetch the layout ONCE on the main thread and replace
`pynput.keyboard._darwin.keycode_context` with a no-TIS context manager that
yields the cached layout. The listener thread then enters the shim instead of
calling TIS. This is safe because the listener's per-event character conversion
uses `CGEventKeyboardGetUnicodeString` (CoreGraphics, thread-safe) and does NOT
read the cached `keycode_context` value; the shim only prevents the off-main TIS
call without changing key/char detection.

Limitation: the layout is captured once at install time. A keyboard-layout
change mid-session would leave the (unused-by-the-listener) cached value stale;
this does not affect key routing today and can be refreshed on the main thread
via an input-source-changed notification in a future increment.
"""
from __future__ import annotations

import contextlib
import sys

_installed = False


def install_main_thread_keycode_context() -> bool:
    """Idempotent, darwin-only. MUST be called on the MAIN thread (it performs a
    one-time TIS layout fetch, which is only safe on the main thread). Installs
    a no-TIS shim over pynput's keyboard `keycode_context` so the listener thread
    never calls TIS.

    Returns True if the shim is active, False if skipped (non-darwin, or the
    installed pynput's structure is not recognized -> fail-safe no-op; never
    raises, so a pynput upgrade cannot break app startup)."""
    global _installed
    if _installed:
        return True
    if sys.platform != "darwin":
        return False
    try:
        # Resolve the GENUINE fetch from _util.darwin (not the keyboard-module
        # alias, which a prior install may already have shimmed).
        from pynput._util import darwin as _pyd
        from pynput.keyboard import _darwin as _kbd

        real_keycode_context = _pyd.keycode_context

        # One-time fetch on the (main) calling thread -- safe; the off-main call
        # is what traps.
        with real_keycode_context() as cached_layout:
            layout = cached_layout

        @contextlib.contextmanager
        def _cached_keycode_context():
            # No TIS call: yield the main-thread-precomputed layout. pynput's
            # listener bg thread enters this in place of the real TIS fetch.
            yield layout

        # _run resolves keycode_context as a module global of keyboard._darwin,
        # so shadowing it there is what the listener thread will use.
        _kbd.keycode_context = _cached_keycode_context
        _installed = True
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[macos_keyboard_layout] keycode_context main-thread shim not "
              f"installed ({type(e).__name__}: {e}); keyboard capture may be "
              f"unstable on macOS.")
        return False
