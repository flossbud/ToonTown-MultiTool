"""Where the launchpad window opens: the first show, and a show after the
lifecycle hid it, keep the whole window inside the usable area of its
screen, unless the user has moved it themselves.

Built offscreen with a stand-in screen, so these are construction checks of
the placement; how a real taskbar and window manager treat it is for a live
run. The numbers are a Windows 11 laptop's: 1920x1200 at 150%, 1280x752
usable logical pixels, UI scale 0.80, which Qt reports as 1600x940.
"""

import os

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication

from tests.test_launchpad_window import _dispose, isolated  # noqa: F401 (fixture)

LAPTOP_USABLE = QRect(0, 0, 1600, 940)
LARGE_USABLE = QRect(0, 0, 1920, 1032)
KEPT = "[NextUI] window kept on screen"


class _Screen:
    """The one QScreen call the placement makes."""

    def __init__(self, area):
        self.area = QRect(area)

    def availableGeometry(self):
        return QRect(self.area)


@pytest.fixture
def placed(isolated, qapp, monkeypatch):
    """The window, built and not shown yet, on a stand-in screen, at the
    default geometry the laptop gives it: (100, 100), 880x860."""
    from utils.launchpad_window import LaunchpadWindow
    win = LaunchpadWindow()
    screen = _Screen(LAPTOP_USABLE)
    monkeypatch.setattr(win, "screen", lambda: screen)
    win.setGeometry(QRect(100, 100, 880, 860))
    yield win, screen
    _dispose(win, qapp)


def _show_for_after_hide(win, qapp):
    from utils.widgets.launchpad import lifecycle
    win.hide()
    qapp.processEvents()
    win.show_for(lifecycle.LAUNCHER)
    qapp.processEvents()


def test_the_first_show_keeps_the_window_above_the_laptop_taskbar(placed, qapp, capsys):
    win, screen = placed
    win.show()
    qapp.processEvents()
    frame = win.frameGeometry()
    assert screen.area.contains(frame)
    assert frame.bottom() == screen.area.bottom()      # lifted just enough
    assert win.geometry().x() == 100                   # not moved sideways
    assert win.size().height() == 860                  # moved, never resized
    assert KEPT in capsys.readouterr().out


def test_a_window_that_fits_opens_where_it_always_did(placed, qapp, capsys):
    win, screen = placed
    screen.area = QRect(LARGE_USABLE)
    win.show()
    qapp.processEvents()
    assert win.geometry().topLeft() == QPoint(100, 100)
    assert KEPT not in capsys.readouterr().out


def test_show_for_after_a_hide_refits_a_window_it_placed(placed, qapp):
    win, screen = placed
    screen.area = QRect(LARGE_USABLE)
    win.show()
    qapp.processEvents()
    assert win.geometry().topLeft() == QPoint(100, 100)
    screen.area = QRect(LAPTOP_USABLE)                 # the usable area shrank
    _show_for_after_hide(win, qapp)
    assert win.isVisible()
    assert screen.area.contains(win.frameGeometry())


def test_show_for_after_a_hide_leaves_a_window_the_user_moved(placed, qapp, capsys):
    win, screen = placed
    win.show()
    qapp.processEvents()
    win.move(300, 150)                                 # dragged by the user,
    qapp.processEvents()                               # partly under the taskbar
    capsys.readouterr()
    _show_for_after_hide(win, qapp)
    assert win.isVisible()
    assert win.pos() == QPoint(300, 150)
    assert KEPT not in capsys.readouterr().out


def test_wayland_placement_is_left_to_the_compositor(placed, qapp, monkeypatch):
    win, _screen = placed
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "wayland"))
    win.show()
    qapp.processEvents()
    assert win.geometry().topLeft() == QPoint(100, 100)


def test_a_maximized_window_is_not_moved(placed, qapp, capsys):
    win, screen = placed
    screen.area = QRect(300, 300, 600, 600)            # would move any other window
    win.showMaximized()
    qapp.processEvents()
    assert win.isMaximized()
    assert KEPT not in capsys.readouterr().out
