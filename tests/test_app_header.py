"""Tests for header construction in MultiToonTool.

We bypass MultiToonTool.__init__ (which starts background threads and reads
$HOME-rooted settings) by constructing via __new__ and calling the
_build_header method directly. The method only writes attributes onto self,
so the uninitialized instance is fine for this scope.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


class _StubSettings:
    """Minimal settings_manager stub for header / chip-rail construction tests.
    `get` returns whatever kwargs were passed in (e.g. hints_enabled,
    show_debug_tab, use_system_title_bar), else the provided default."""
    def __init__(self, **kv):
        self._kv = kv

    def get(self, key, default=None):
        return self._kv.get(key, default)

    def set(self, key, value):
        self._kv[key] = value


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def header(qapp):
    """Build a header without running MultiToonTool.__init__."""
    from main import MultiToonTool
    instance = MultiToonTool.__new__(MultiToonTool)
    instance.settings_manager = _StubSettings(hints_enabled=True)
    return instance._build_header()


def test_header_min_height_is_112(header):
    assert header.minimumHeight() == 112


def test_header_has_centered_logo_label(header):
    from PySide6.QtWidgets import QLabel
    logo = header.findChild(QLabel, "header_logo")
    assert logo is not None, "header must contain a 'header_logo' QLabel"
    assert not logo.pixmap().isNull(), "logo pixmap must be loaded"


def test_header_no_longer_has_old_brand_widgets(header):
    from PySide6.QtWidgets import QLabel, QWidget
    assert header.findChild(QLabel, "header_icon") is None
    assert header.findChild(QLabel, "header_session_status") is None
    assert header.findChild(QWidget, "header_brand_link") is None
    assert header.findChild(QWidget, "header_accent") is None


def test_header_hint_button_not_in_header(header):
    from PySide6.QtWidgets import QToolButton
    assert header.findChild(QToolButton, "hint_toggle") is None


def test_logo_asset_swaps_with_theme(qapp, monkeypatch):
    """Dark theme uses the plain wordmark; light uses the shadow variant.
    The two assets have different aspect ratios (2.909 vs 2.675), so the
    scaled logo width differs by theme — proving _refresh_header_logo swaps
    the asset rather than reusing one."""
    import utils.theme_manager as tm
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings()
    inst.header = inst._build_header()

    monkeypatch.setattr(tm, "resolve_theme", lambda _sm: "dark")
    inst._refresh_header_logo(header_width=575)
    dark_w = inst.header_logo.pixmap().width()

    monkeypatch.setattr(tm, "resolve_theme", lambda _sm: "light")
    inst._refresh_header_logo(header_width=575)
    light_w = inst.header_logo.pixmap().width()

    assert dark_w != light_w, (
        f"logo should swap per theme; got dark={dark_w} light={light_w}"
    )


def test_header_has_app_icon_at_corner(header):
    from utils.widgets.window_chrome import _HeaderAppIcon
    icon = header.findChild(_HeaderAppIcon)
    assert icon is not None, "header must contain a _HeaderAppIcon"
    assert icon.pos().x() == 13 and icon.pos().y() == 13   # equal 13px corner margins
    assert icon.size().width() == 36 and icon.size().height() == 36
    assert icon.toolTip() == "About / Credits"
    assert icon.icon_opacity == 0.75                        # subdued at rest


def test_header_app_icon_click_opens_credits(qapp):
    # The icon's clicked signal binds to _on_app_icon_clicked at build time, and
    # from a non-Credits page that calls self.nav_select_credits(). Patch
    # nav_select_credits on the instance BEFORE building the header to exercise
    # the credits-open path.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from main import MultiToonTool
    from utils.widgets.window_chrome import _HeaderAppIcon
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(hints_enabled=True)
    called = []
    inst.nav_select_credits = lambda: called.append(True)
    inst.header = inst._build_header()
    icon = inst.header.findChild(_HeaderAppIcon)
    QTest.mouseClick(icon, Qt.LeftButton)
    assert called == [True]


def test_on_active_page_changed_drives_icon(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from main import MultiToonTool
    from utils.widgets.window_chrome import _HeaderAppIcon
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(hints_enabled=True)
    inst.header = inst._build_header()
    inst._on_active_page_changed(5)                 # Credits is active
    assert inst.header_app_icon.icon_opacity == 1.0
    inst._on_active_page_changed(0)                 # back to a chip page
    assert inst.header_app_icon.icon_opacity == 0.75


def test_currentchanged_hook_and_initial_sync(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from PySide6.QtWidgets import QStackedWidget, QWidget
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(hints_enabled=True)
    inst.header = inst._build_header()
    inst.stack = QStackedWidget()
    for _ in range(6):                              # indices 0..5 (5 = credits)
        inst.stack.addWidget(QWidget())
    inst.stack.setCurrentIndex(5)                   # start ON credits
    inst._wire_header_icon_active_state()
    assert inst.header_app_icon.icon_opacity == 1.0   # initial sync caught it
    inst.stack.setCurrentIndex(0)                     # via the signal
    assert inst.header_app_icon.icon_opacity == 0.75


def test_theme_refresh_reraises_app_icon(qapp):
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(hints_enabled=True)
    inst.header = inst._build_header()        # build-time refresh: no crash
    calls = []
    inst.header_app_icon.raise_ = lambda: calls.append(True)
    inst._refresh_header_logo(header_width=575)
    assert calls == [True]


def test_chip_rail_no_longer_has_app_icon(qapp):
    from PySide6.QtWidgets import QToolButton
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(show_debug_tab=False)
    inst.chip_rail = inst._build_chip_rail()
    assert inst.chip_rail.findChild(QToolButton, "rail_app_icon") is None
    assert not hasattr(inst, "rail_app_icon")


def test_chip_phantom_balances_with_no_left_cluster(qapp):
    # Left end is empty (icon moved to header). The left phantom = right cluster
    # (hint 34) + one layout-spacing gap (4) = 38. There is no right phantom.
    # (Actual centering is asserted in tests/test_chip_rail.py.)
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(show_debug_tab=False)
    inst.chip_rail = inst._build_chip_rail()
    inst._update_chip_rail_phantom_width()
    assert inst.chip_rail_left_phantom.sizeHint().width() == 38
    assert not hasattr(inst, "chip_rail_right_phantom")


def test_chip_phantom_with_debug_tab(qapp):
    # Debug visible -> right cluster = overflow(34) + spacing(4) + hint(34) = 72;
    # left phantom = 72 + one layout-spacing gap (4) = 76.
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(show_debug_tab=True)
    inst.chip_rail = inst._build_chip_rail()
    inst._update_chip_rail_phantom_width()
    assert inst.chip_rail_left_phantom.sizeHint().width() == 76
    assert not hasattr(inst, "chip_rail_right_phantom")


def test_app_icon_present_in_system_title_bar_mode(qapp):
    """The app icon is header-owned (built in _build_header), NOT owned by the
    frameless-only WindowChromeController. With the 'use system title bar'
    escape hatch on, _apply_window_chrome creates no controller (self._chrome is
    None) — but the header icon must still exist, be positioned, and open
    Credits, so that mode never loses the About/Credits entry point."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMainWindow, QWidget
    from main import MultiToonTool
    from utils.widgets.window_chrome import _HeaderAppIcon
    inst = MultiToonTool.__new__(MultiToonTool)
    QMainWindow.__init__(inst)
    inst.settings_manager = _StubSettings(
        hints_enabled=True, theme="dark", use_system_title_bar=True
    )
    called = []
    inst.nav_select_credits = lambda: called.append(True)
    inst.header = inst._build_header()
    inst.container = QWidget()
    inst._apply_window_chrome()
    assert inst._chrome is None        # native title bar: no traffic-light controller
    icon = inst.header.findChild(_HeaderAppIcon)
    assert icon is not None, "icon must exist even with the system title bar"
    assert icon.pos().x() == 13 and icon.pos().y() == 13
    QTest.mouseClick(icon, Qt.LeftButton)
    assert called == [True]
