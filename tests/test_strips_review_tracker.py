"""Cancellation and queued samples across tracker lifetimes."""
import threading
from PySide6.QtCore import Qt
from utils.strips.tracker import StripTracker

RECT = (100, 50, 800, 600)


def test_restart_does_not_revive_a_sample_that_outlived_stop(qapp):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def geometry(_):
        calls.append(threading.get_ident())
        if len(calls) == 1:
            entered.set()
            release.wait(5)
        return RECT

    tracker = StripTracker(geometry, interval_s=.01)
    tracker.set_windows(['1'])
    tracker.start()
    assert entered.wait(2)
    old = tracker._thread
    try:
        tracker.stop()  # bounded join expires while the query is still running
        tracker.start()
        release.set()
        old.join(.5)
        assert not old.is_alive()
    finally:
        release.set()
        tracker.stop()
        old.join(2)


def test_queued_worker_sample_is_ignored_after_stop(qapp):
    tracker = StripTracker(lambda _: RECT, interval_s=30)
    tracker.set_windows(['1'])
    tracker.sample_now()  # one sample short of presenting
    received = threading.Event()
    tracker._sampled.connect(lambda _: received.set(), Qt.DirectConnection)
    placed = []
    tracker.place.connect(lambda *a: placed.append(a))
    tracker.start()
    assert received.wait(2)  # emission has happened; GUI queue is not drained
    tracker.stop()
    qapp.processEvents()
    assert placed == []


def test_old_membership_sample_cannot_seed_a_readded_window(qapp):
    tracker = StripTracker(lambda _: RECT, interval_s=30)
    tracker.set_windows(['1'])
    received = threading.Event()
    tracker._sampled.connect(lambda _: received.set(), Qt.DirectConnection)
    placed = []
    tracker.place.connect(lambda *a: placed.append(a))
    tracker.start()
    try:
        assert received.wait(2)
        tracker.set_windows([])
        tracker.set_windows(['1'])
        qapp.processEvents()
        tracker.sample_now()
        assert placed == []  # only one sample belongs to this membership
    finally:
        tracker.stop()
