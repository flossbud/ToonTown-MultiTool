"""Pure predicate for whether the Multitoon glow/bar repaint timers should run.
They only change pixels on the visible Multitoon page; off-page or minimized,
nothing visible changes, so they should stop. Keep-alive timing is preserved by
the monotonic _ka_cycle_start anchor, NOT by these repaint timers."""
from __future__ import annotations


def timers_should_run(*, is_current_page: bool, window_visible: bool,
                      window_minimized: bool, keep_alive_active: bool,
                      chat_glow_active: bool,
                      overlay_active: bool = False) -> tuple[bool, bool]:
    """Return (glow_should_run, bars_should_run).

    overlay_active: True while the transparent-mode cluster is up. The overlay
    minimizes the main window, so the normal on-page test would stop the timers;
    but the cluster is visible in its own surfaces, so overlay_active forces
    on-page. Defaults False -> framed-mode behavior is unchanged.
    """
    on_page = overlay_active or (
        window_visible and not window_minimized and is_current_page
    )
    if not on_page:
        return (False, False)
    glow = keep_alive_active or chat_glow_active
    bars = keep_alive_active
    return (glow, bars)
