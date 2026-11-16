"""The tracker: a strip is never shown while its window is moving."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

from utils.strips.tracker import HIDE, PLACE, StripTracker, WindowTrack

A = (100, 50, 800, 600)
B = (130, 50, 800, 600)
C = (160, 50, 800, 600)


def test_first_sample_shows_nothing_second_identical_places():
    t = WindowTrack()
    assert t.feed(A) is None
    assert t.feed(A) == (PLACE, A)
    assert t.placed == A
    assert t.feed(A) is None            # resting: nothing more to say


def test_any_change_hides_at_once():
    t = WindowTrack()
    t.feed(A), t.feed(A)
    assert t.feed(B) == (HIDE, None)
    assert t.placed is None


def test_stays_hidden_for_the_whole_move_and_hides_only_once():
    t = WindowTrack()
    t.feed(A), t.feed(A)
    assert t.feed(B) == (HIDE, None)
    assert t.feed(C) is None            # still moving: no second hide
    assert t.feed(B) is None
    assert t.placed is None


def test_placed_after_two_identical_samples_once_the_window_rests():
    t = WindowTrack()
    t.feed(A), t.feed(A)
    t.feed(B)
    assert t.feed(C) is None            # one sample at C is not rest
    assert t.feed(C) == (PLACE, C)


def test_a_resize_is_a_change_too():
    t = WindowTrack()
    t.feed(A), t.feed(A)
    assert t.feed((100, 50, 640, 480)) == (HIDE, None)


def test_gone_minimized_or_empty_hides():
    for gone in (None, (0, 0, 0, 0), (10, 10, 800, 0)):
        t = WindowTrack()
        t.feed(A), t.feed(A)
        assert t.feed(gone) == (HIDE, None)
        assert t.feed(gone) is None
        # Back where it was: two samples again before it shows.
        assert t.feed(A) is None
        assert t.feed(A) == (PLACE, A)


def test_a_window_that_never_appears_says_nothing():
    t = WindowTrack()
    assert t.feed(None) is None and t.feed(None) is None


def test_reset_places_again_without_a_move():
    t = WindowTrack()
    t.feed(A), t.feed(A)
    t.reset()
    assert t.feed(A) is None
    assert t.feed(A) == (PLACE, A)


def test_float_rects_are_compared_as_pixels():
    t = WindowTrack()
    t.feed((100.0, 50.0, 800.0, 600.0))
    assert t.feed(A) == (PLACE, A)


def _collect(tracker):
    events = []
    tracker.place.connect(lambda wid, rect: events.append(("place", wid, tuple(rect))))
    tracker.hide.connect(lambda wid: events.append(("hide", wid)))
    return events


def test_tracker_reports_per_window(qapp):
    rects = {"1": A, "2": B}
    tracker = StripTracker(lambda wid: rects.get(wid))
    events = _collect(tracker)
    tracker.set_windows(["1", "2"])
    tracker.sample_now()
    assert events == []
    tracker.sample_now()
    assert events == [("place", "1", A), ("place", "2", B)]
    rects["2"] = C                      # only window 2 moves
    tracker.sample_now()
    assert events[2:] == [("hide", "2")]
    assert tracker.placed_rect("1") == A and tracker.placed_rect("2") is None
    tracker.sample_now()
    assert events[3:] == [("place", "2", C)]


def test_untracked_windows_are_dropped(qapp):
    rects = {"1": A, "2": B}
    tracker = StripTracker(lambda wid: rects.get(wid))
    events = _collect(tracker)
    tracker.set_windows(["1", "2"])
    tracker.sample_now(), tracker.sample_now()
    tracker.set_windows(["1"])
    assert tracker.windows() == ("1",)
    # A sample taken before the change still names window 2: ignored.
    tracker._on_sampled({"2": C, "1": A})
    assert events == [("place", "1", A), ("place", "2", B)]


def test_a_failing_geometry_query_counts_as_gone(qapp):
    calls = {"n": 0}

    def geometry(_wid):
        calls["n"] += 1
        if calls["n"] > 2:
            raise OSError("window server went away")
        return A

    tracker = StripTracker(geometry)
    events = _collect(tracker)
    tracker.set_windows(["1"])
    tracker.sample_now(), tracker.sample_now(), tracker.sample_now()
    assert events == [("place", "1", A), ("hide", "1")]


def test_batch_query_answers_for_every_window(qapp):
    asked = []

    def batch(wids):
        asked.append(wids)
        return {"1": A}                 # window 2 is not on screen

    tracker = StripTracker(batch_fn=batch)
    events = _collect(tracker)
    tracker.set_windows(["1", "2"])
    tracker.sample_now(), tracker.sample_now()
    assert asked == [("1", "2"), ("1", "2")]
    assert events == [("place", "1", A)]


def test_invalidate_places_again(qapp):
    tracker = StripTracker(lambda _wid: A)
    events = _collect(tracker)
    tracker.set_windows(["1"])
    tracker.sample_now(), tracker.sample_now()
    tracker.invalidate("1")
    tracker.sample_now(), tracker.sample_now()
    assert events == [("place", "1", A), ("place", "1", A)]


def test_sampling_thread_reports_on_the_gui_thread(qapp):
    import threading
    gui = threading.get_ident()
    seen = []
    tracker = StripTracker(lambda _wid: A, interval_s=0.01)
    tracker.place.connect(lambda wid, rect: seen.append(threading.get_ident()))
    tracker.set_windows(["1"])
    tracker.start()
    try:
        deadline = time.monotonic() + 3.0
        while not seen and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
    finally:
        tracker.stop()
    assert seen == [gui]
