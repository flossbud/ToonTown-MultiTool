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
