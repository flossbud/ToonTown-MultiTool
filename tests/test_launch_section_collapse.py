"""LaunchSection collapse state, click handling, and animation behavior."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from utils.widgets.launch_section import LaunchSection


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_default_state_is_expanded(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    assert sec.is_collapsed is False
    assert sec._body_wrap.isVisibleTo(sec) or not sec._body_wrap.isHidden()


def test_set_collapsed_true_hides_body_wrap(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.show()
    sec.set_collapsed(True, animate=False)
    assert sec.is_collapsed is True
    assert sec._body_wrap.isHidden()
    assert sec.minimumHeight() == 0


def test_set_collapsed_false_shows_body_wrap(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.show()
    sec.set_collapsed(True, animate=False)
    sec.set_collapsed(False, animate=False)
    assert sec.is_collapsed is False
    assert not sec._body_wrap.isHidden()
    assert sec.minimumHeight() == 380


def test_set_collapsed_redundant_call_is_noop(qapp):
    """Calling set_collapsed(False) on an already-expanded section must not
    twiddle visibility or min-height (which would clobber height-sync from
    LaunchTab)."""
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.setMinimumHeight(500)  # simulate a height-sync override
    sec.set_collapsed(False, animate=False)
    assert sec.minimumHeight() == 500  # not overwritten


def test_set_collapsed_does_not_emit_signal(qapp):
    """Programmatic set_collapsed must NOT emit collapsed_changed.
    Only user header clicks do (tested in a later task)."""
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    received = []
    sec.collapsed_changed.connect(lambda v: received.append(v))
    sec.set_collapsed(True, animate=False)
    sec.set_collapsed(False, animate=False)
    assert received == []
