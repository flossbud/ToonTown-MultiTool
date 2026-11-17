"""The launchpad window's chrome: frameless with its own controls and a
rounded card, or the system title bar when use_system_title_bar is set.

The same contract the classic window's chrome tests pinned, checked on the
real LaunchpadWindow (built offscreen: a construction check).
"""

import json
import os

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor

from tests.test_launchpad_window import _dispose


def _build(qapp, monkeypatch, tmp_path, *, native, theme="dark"):
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.json").write_text(
        json.dumps({"use_system_title_bar": native, "theme": theme}))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(config))
    monkeypatch.setenv("TTMT_SELF_CHECK", "1")
    monkeypatch.setattr("utils.update_checker.UpdateChecker.check_async",
                        lambda self, *, manual: True)
    monkeypatch.setattr("utils.launchpad_window._quit_app", lambda: None)
    from utils.launchpad_window import LaunchpadWindow
    return LaunchpadWindow()


@pytest.fixture
def frameless(qapp, monkeypatch, tmp_path):
    win = _build(qapp, monkeypatch, tmp_path, native=False)
    yield win
    _dispose(win, qapp)


@pytest.fixture
def native(qapp, monkeypatch, tmp_path):
    win = _build(qapp, monkeypatch, tmp_path, native=True)
    yield win
    _dispose(win, qapp)


def _margins(win):
    m = win.container.layout().contentsMargins()
    return (m.left(), m.top(), m.right(), m.bottom())


def test_frameless_by_default(frameless):
    from utils.widgets.window_chrome import WindowChromeController
    assert frameless.windowFlags() & Qt.FramelessWindowHint
    assert frameless.testAttribute(Qt.WA_TranslucentBackground) is True
    assert isinstance(frameless._chrome, WindowChromeController)
    assert frameless.container.objectName() == "app_card"


def test_the_system_title_bar_when_asked(native):
    assert not native.windowFlags() & Qt.FramelessWindowHint
    assert native.testAttribute(Qt.WA_TranslucentBackground) is False
    assert native._chrome is None


def test_frameless_is_a_rounded_card_with_outline_and_rim(frameless):
    from utils.widgets.window_chrome_style import BOTTOM_INSET, STROKE_INSET
    frameless._apply_window_corner_state(False, force=True)
    assert "border-radius: 16px" in frameless.container.styleSheet()
    assert "border: 1px solid rgba(255,255,255,0.14)" in frameless.container.styleSheet()
    assert "border-top: 1px solid rgba(255,255,255,0.10)" in frameless.header.styleSheet()
    assert _margins(frameless) == (STROKE_INSET, STROKE_INSET, STROKE_INSET, BOTTOM_INSET)


def test_maximized_is_square(frameless):
    frameless._apply_window_corner_state(True, force=True)
    assert "border-radius" not in frameless.container.styleSheet()
    assert "border:" not in frameless.container.styleSheet()
    assert "border-top:" not in frameless.header.styleSheet()
    assert _margins(frameless) == (0, 0, 0, 0)


def test_the_system_title_bar_is_square_and_plain(native):
    assert "border-radius" not in native.container.styleSheet()
    assert "border:" not in native.container.styleSheet()
    assert "border-top:" not in native.header.styleSheet()
    assert _margins(native) == (0, 0, 0, 0)


@pytest.mark.parametrize("maximized", [False, True])
def test_the_background_still_cascades(frameless, maximized):
    """The card rule is scoped to #app_card; the bare QWidget rule is what
    the launcher's descendants inherit their background from."""
    frameless._apply_window_corner_state(maximized, force=True)
    assert "QWidget {" in frameless.container.styleSheet()


def test_the_background_cascades_with_the_system_title_bar(native):
    assert "QWidget {" in native.container.styleSheet()


def test_a_window_state_change_restyles_the_corners(frameless, monkeypatch):
    calls = []
    monkeypatch.setattr(frameless, "_apply_window_corner_state",
                        lambda is_maximized, force=False: calls.append(is_maximized))
    frameless.changeEvent(QEvent(QEvent.WindowStateChange))
    assert calls == [frameless.isMaximized()]


def test_the_controls_get_the_theme_from_the_start(qapp, monkeypatch, tmp_path):
    """Built light, the unfocused dots use the light inactive grey, not the
    controller's dark default."""
    win = _build(qapp, monkeypatch, tmp_path, native=False, theme="light")
    try:
        assert win._chrome.btn_min._inactive_dot == QColor("#b8bcc2")
    finally:
        _dispose(win, qapp)
