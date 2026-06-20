from tabs.multitoon._timer_gating import timers_should_run


def test_off_page_stops_both():
    glow, bars = timers_should_run(
        is_current_page=False, window_visible=True, window_minimized=False,
        keep_alive_active=True, chat_glow_active=True)
    assert (glow, bars) == (False, False)


def test_minimized_stops_both():
    glow, bars = timers_should_run(
        is_current_page=True, window_visible=True, window_minimized=True,
        keep_alive_active=True, chat_glow_active=False)
    assert (glow, bars) == (False, False)


def test_on_page_matches_activity():
    # glow runs for keep-alive OR chat glow; bars only for keep-alive.
    glow, bars = timers_should_run(
        is_current_page=True, window_visible=True, window_minimized=False,
        keep_alive_active=False, chat_glow_active=True)
    assert (glow, bars) == (True, False)
    glow, bars = timers_should_run(
        is_current_page=True, window_visible=True, window_minimized=False,
        keep_alive_active=True, chat_glow_active=False)
    assert (glow, bars) == (True, True)


def test_idle_on_page_stops_both():
    glow, bars = timers_should_run(
        is_current_page=True, window_visible=True, window_minimized=False,
        keep_alive_active=False, chat_glow_active=False)
    assert (glow, bars) == (False, False)


def test_overlay_active_runs_bars_when_minimized_off_page():
    # Transparent mode: main window minimized + tab not current page, but the
    # cluster is visible in its own surfaces -> keep-alive bars/glow must run.
    glow, bars = timers_should_run(
        is_current_page=False, window_visible=False, window_minimized=True,
        keep_alive_active=True, chat_glow_active=False, overlay_active=True)
    assert (glow, bars) == (True, True)


def test_overlay_active_idle_stops_both():
    # Overlay up but nothing active -> no repaint work.
    glow, bars = timers_should_run(
        is_current_page=False, window_visible=False, window_minimized=True,
        keep_alive_active=False, chat_glow_active=False, overlay_active=True)
    assert (glow, bars) == (False, False)


def test_overlay_active_glow_for_chat_only():
    glow, bars = timers_should_run(
        is_current_page=False, window_visible=False, window_minimized=True,
        keep_alive_active=False, chat_glow_active=True, overlay_active=True)
    assert (glow, bars) == (True, False)


def test_overlay_inactive_preserves_legacy_minimized_behavior():
    # overlay_active defaults False -> minimized still stops both (unchanged).
    glow, bars = timers_should_run(
        is_current_page=True, window_visible=True, window_minimized=True,
        keep_alive_active=True, chat_glow_active=True)
    assert (glow, bars) == (False, False)
