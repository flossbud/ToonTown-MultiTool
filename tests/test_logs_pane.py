import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication

from utils.widgets.logs_console.model import BUFFER_CAP, LogLineModel
from utils.widgets.logs_console.pane import FOLLOW_SLOP, LogConsolePane
from utils.widgets.logs_console.proxy import LogFilterProxy
from utils.widgets.logs_console.records import make_line


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def rig(qapp):
    model = LogLineModel()
    proxy = LogFilterProxy()
    proxy.setSourceModel(model)
    pane = LogConsolePane(proxy)
    pane.resize(500, 120)          # small: content overflows quickly
    pane.show()
    QApplication.processEvents()
    return model, proxy, pane


def _fill(model, n, prefix="line"):
    now = datetime(2026, 7, 9, 12, 0, 0)
    for i in range(n):
        model.append(make_line(f"{prefix} {i}", now=now))
    QApplication.processEvents()
    QApplication.processEvents()   # second pass: deferred scrollToBottom singleShot


def test_starts_following_and_sticks_to_bottom(rig):
    model, proxy, pane = rig
    _fill(model, 60)
    assert pane.is_following()
    sb = pane.view.verticalScrollBar()
    assert sb.maximum() - sb.value() <= FOLLOW_SLOP


def test_scrolling_up_auto_pauses_and_counts_pending(rig):
    model, proxy, pane = rig
    _fill(model, 60)
    pane.view.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    assert not pane.is_following()
    _fill(model, 5, prefix="new")
    assert pane.pending_count() == 5
    assert pane.jump_pill.isVisible()
    assert "5 new lines" in pane.jump_pill.text()


def test_jump_to_live_resumes_and_clears_pending(rig):
    model, proxy, pane = rig
    _fill(model, 60)
    pane.view.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    _fill(model, 3, prefix="new")
    pane.jump_pill.click()
    QApplication.processEvents()
    assert pane.is_following()
    assert pane.pending_count() == 0
    assert not pane.jump_pill.isVisible()


def test_scrolling_back_to_bottom_resumes(rig):
    model, proxy, pane = rig
    _fill(model, 60)
    sb = pane.view.verticalScrollBar()
    sb.setValue(0)
    QApplication.processEvents()
    assert not pane.is_following()
    sb.setValue(sb.maximum())
    QApplication.processEvents()
    assert pane.is_following()


def test_set_following_forces_state(rig):
    model, proxy, pane = rig
    _fill(model, 60)
    pane.set_following(False)
    assert not pane.is_following()
    pane.set_following(True)
    assert pane.is_following()


def test_follow_changed_emits_only_on_transitions(rig):
    model, proxy, pane = rig
    _fill(model, 60)
    emitted = []
    pane.follow_changed.connect(emitted.append)
    pane.set_following(True)       # already following: no emission
    assert emitted == []
    pane.set_following(False)
    assert emitted == [False]
    pane.set_following(False)      # already paused: no emission
    assert emitted == [False]
    pane.set_following(True)
    assert emitted == [False, True]


def test_jump_pill_singular_text(rig):
    model, proxy, pane = rig
    _fill(model, 60)
    pane.view.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    assert not pane.is_following()
    _fill(model, 1, prefix="new")
    assert pane.pending_count() == 1
    assert pane.jump_pill.text() == "1 new line"


def test_ring_trim_does_not_pause_follow(rig):
    model, proxy, pane = rig
    _fill(model, BUFFER_CAP)
    assert pane.is_following()
    _fill(model, 10, prefix="over")   # each append trims the top row
    assert pane.is_following()
    assert pane.pending_count() == 0


def test_click_copies_line_in_export_format(rig, qapp):
    model, proxy, pane = rig
    _fill(model, 1)
    pane._on_clicked(proxy.index(0, 0))
    assert qapp.clipboard().text() == "[12:00:00] line 0"


def test_toast_shows_and_autohides(rig, qapp):
    from PySide6.QtTest import QTest
    model, proxy, pane = rig
    pane.show_toast("Copied 3 lines to clipboard")
    assert pane.toast.isVisible()
    QTest.qWait(2200)
    assert not pane.toast.isVisible()


def test_empty_state_label(rig):
    model, proxy, pane = rig
    proxy.set_query("zzz-no-match")
    _fill(model, 2)
    pane.set_empty_text('No matching lines for "zzz-no-match".')
    pane.refresh_empty_state()
    assert pane.empty_label.isVisible()
    proxy.set_query("")
    pane.refresh_empty_state()
    assert not pane.empty_label.isVisible()
