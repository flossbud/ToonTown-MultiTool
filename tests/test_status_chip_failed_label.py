"""StatusChip on FAILED state shows the static label, not the raw message."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_failed_state_shows_static_label_and_full_tooltip(qapp):
    from services.cc_login_service import LoginState
    from tabs.launch_tab import StatusChip, STATUS_LABELS

    long_msg = (
        "We've noticed that you're logging in from a new device/IP, "
        "please check your email and activate this session before "
        "continuing."
    )
    chip = StatusChip()
    chip.set_status(LoginState.FAILED, long_msg)

    assert chip.text() == STATUS_LABELS[LoginState.FAILED]
    assert chip.toolTip() == long_msg
    assert chip.isVisible()


def test_non_failed_state_unchanged(qapp):
    from services.cc_login_service import LoginState
    from tabs.launch_tab import StatusChip

    chip = StatusChip()
    chip.set_status(LoginState.LOGGING_IN, "Logging in…")
    assert chip.text() == "Logging in…"
    assert chip.toolTip() == "Logging in…"


def test_idle_state_hides_chip(qapp):
    from services.cc_login_service import LoginState
    from tabs.launch_tab import StatusChip

    chip = StatusChip()
    chip.set_status(LoginState.LOGGING_IN, "Logging in…")
    assert chip.isVisible()
    chip.set_status(LoginState.IDLE, "")
    assert not chip.isVisible()
