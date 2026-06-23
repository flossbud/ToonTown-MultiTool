import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_loading_keeps_clock_running(qapp):
    from utils.overlay.radial_menu import RadialMenuWidget
    menu = RadialMenuWidget(emblem_diameter=120)
    menu._anim_enabled = True
    menu._state = "accounts"           # the spinner busy-source is ring-scoped
    menu._loading = {"a1"}
    menu._kick()
    assert menu._clock.isActive()
    menu._advance(100)                 # pending on the ring -> busy -> clock stays on
    assert menu._clock.isActive()


def test_loading_off_ring_does_not_pin_clock(qapp):
    # A leftover pending id after navigating away from the accounts ring (e.g.
    # clicked Back before the pose arrived) must NOT keep the 60fps clock alive;
    # no spinner is painted off-ring.
    from utils.overlay.radial_menu import RadialMenuWidget
    menu = RadialMenuWidget(emblem_diameter=120)
    menu._anim_enabled = True
    menu._state = "main"
    menu._loading = {"a1"}
    menu._kick()
    menu._advance(100)                 # off-ring -> busy-source quiet -> clock stops
    assert not menu._clock.isActive()


def test_clock_stops_when_nothing_pending(qapp):
    from utils.overlay.radial_menu import RadialMenuWidget
    menu = RadialMenuWidget(emblem_diameter=120)
    menu._anim_enabled = True
    menu._loading = set()
    menu._kick()
    menu._advance(100)                 # nothing busy -> clock stops
    assert not menu._clock.isActive()


def test_spinner_phase_advances_while_pending(qapp):
    from utils.overlay.radial_menu import RadialMenuWidget
    menu = RadialMenuWidget(emblem_diameter=120)
    menu._state = "accounts"
    menu._loading = {"a1"}
    menu._advance(0)
    p0 = menu._spinner_phase
    menu._advance(450)
    assert menu._spinner_phase != p0
