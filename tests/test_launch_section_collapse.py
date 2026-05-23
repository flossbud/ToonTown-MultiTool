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


def test_chevron_text_reflects_state(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    assert sec._chev.text() == "▾"  # ▾
    sec.set_collapsed(True, animate=False)
    assert sec._chev.text() == "▸"  # ▸
    sec.set_collapsed(False, animate=False)
    assert sec._chev.text() == "▾"


def test_header_click_toggles_state_and_emits_signal(qapp):
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QMouseEvent

    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.show()
    received = []
    sec.collapsed_changed.connect(lambda v: received.append(v))

    # Simulate a left-click on the header frame itself (not on a child).
    # Click well to the left of where the launcher button sits so the
    # event resolves to the QFrame, not the QToolButton.
    pos = QPoint(80, sec._header_frame.height() // 2)
    press = QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(sec._header_frame, press)

    assert sec.is_collapsed is True
    assert received == [True]

    # Second click toggles back.
    QApplication.sendEvent(sec._header_frame, QMouseEvent(
        QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))
    assert sec.is_collapsed is False
    assert received == [True, False]


def test_launcher_button_click_does_not_toggle(qapp):
    """The QToolButton absorbs its click before the header frame sees it."""
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.show()
    launcher_received = []
    sec.launcher_clicked.connect(lambda: launcher_received.append(True))
    section_received = []
    sec.collapsed_changed.connect(lambda v: section_received.append(v))

    sec.launcher_btn.click()
    assert launcher_received == [True]
    assert section_received == []
    assert sec.is_collapsed is False


def test_right_click_does_not_toggle(qapp):
    """Only left-click toggles. Right-click is ignored (Qt context-menu
    convention)."""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QMouseEvent

    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.show()
    received = []
    sec.collapsed_changed.connect(lambda v: received.append(v))
    pos = QPoint(80, sec._header_frame.height() // 2)
    QApplication.sendEvent(sec._header_frame, QMouseEvent(
        QEvent.MouseButtonPress, pos, Qt.RightButton, Qt.RightButton,
        Qt.NoModifier))
    assert sec.is_collapsed is False
    assert received == []
