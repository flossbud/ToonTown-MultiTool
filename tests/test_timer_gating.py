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
