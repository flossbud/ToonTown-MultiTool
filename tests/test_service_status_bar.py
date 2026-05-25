"""Unit tests for ServiceStatusBar - the 3-state status widget (broadcasting,
idle, stopped) that replaces the old StatusBar + toggle_service_button + section
divider stack in the Multitoon compact layout."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def bar(qapp):
    from tabs.multitoon._service_status_bar import ServiceStatusBar
    return ServiceStatusBar()


def test_default_state_is_idle(bar):
    assert bar.state == "idle"


def test_set_state_accepts_three_values(bar):
    for state in ("broadcasting", "idle", "stopped"):
        bar.set_state(state)
        assert bar.state == state


def test_set_state_rejects_unknown_value(bar):
    with pytest.raises(ValueError):
        bar.set_state("frobnicate")


def test_set_status_text_updates_label(bar):
    bar.set_status_text("Broadcasting - 2 of 4 toons")
    assert bar.label.text() == "Broadcasting - 2 of 4 toons"


def test_set_dot_states_forwards_to_dots(bar):
    bar.set_dot_states([2, 1, 2, 0])
    assert bar.dots._states == [2, 1, 2, 0]


def test_broadcasting_state_shows_stop_button(bar):
    bar.set_state("broadcasting")
    # In broadcasting/idle the button is a stop glyph; in stopped it's
    # a play glyph. The widget stores the role on a property.
    assert bar.stop_play_button.property("role") == "stop"


def test_stopped_state_shows_play_button(bar):
    bar.set_state("stopped")
    assert bar.stop_play_button.property("role") == "play"


def test_idle_state_shows_stop_button(bar):
    bar.set_state("idle")
    assert bar.stop_play_button.property("role") == "stop"


def test_stop_play_button_emits_stop_requested_in_broadcasting(bar):
    bar.set_state("broadcasting")
    received = []
    bar.stop_requested.connect(lambda: received.append("stop"))
    bar.stop_play_button.click()
    assert received == ["stop"]


def test_stop_play_button_emits_play_requested_in_stopped(bar):
    bar.set_state("stopped")
    received = []
    bar.play_requested.connect(lambda: received.append("play"))
    bar.stop_play_button.click()
    assert received == ["play"]


def test_refresh_button_emits_refresh_requested(bar):
    received = []
    bar.refresh_requested.connect(lambda: received.append("refresh"))
    bar.refresh_button.click()
    assert received == ["refresh"]


def test_qss_state_property_updates(bar):
    """The bar exposes its state via the svc_state Qt property so QSS rules
    can target each colour scheme."""
    bar.set_state("broadcasting")
    assert bar.property("svc_state") == "broadcasting"
    bar.set_state("stopped")
    assert bar.property("svc_state") == "stopped"
    bar.set_state("idle")
    assert bar.property("svc_state") == "idle"


def test_fixed_height_36px(bar):
    assert bar.height() == 36 or bar.minimumHeight() == 36 or bar.maximumHeight() == 36
