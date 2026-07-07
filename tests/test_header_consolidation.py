import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication


class _StubSettings:
    def __init__(self, **kv): self._kv = kv
    def get(self, k, d=None): return self._kv.get(k, d)
    def set(self, k, v): self._kv[k] = v


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _bare(qapp):
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(hints_enabled=True, show_debug_tab=False)
    return inst


def test_header_has_no_app_icon(qapp):
    inst = _bare(qapp)
    header = inst._build_header()
    assert not hasattr(inst, "header_app_icon")


def test_header_hint_toggle_top_left(qapp):
    inst = _bare(qapp)
    inst.header = inst._build_header()   # hold the QFrame so its children survive GC
    assert inst.hint_btn.pos().x() == 13 and inst.hint_btn.pos().y() == 13


def test_wordmark_is_clickable_logo(qapp):
    from utils.widgets.clickable_logo import ClickableLogo
    inst = _bare(qapp)
    inst.header = inst._build_header()
    assert isinstance(inst.header_logo, ClickableLogo)


def test_wordmark_click_toggles_credits(qapp, monkeypatch):
    inst = _bare(qapp)
    called = []
    # Patch before build: _build_header connects header_logo.clicked to
    # self._on_app_icon_clicked at build time, so the patch must be in place first.
    monkeypatch.setattr(inst, "_on_app_icon_clicked", lambda: called.append(True))
    inst.header = inst._build_header()   # hold the QFrame so its children survive GC
    inst.header_logo.clicked.emit()
    assert called == [True]


def test_on_active_page_changed_drives_wordmark(qapp):
    # Migrated from test_app_header's icon_opacity coverage: the active-state
    # choke point now lights the wordmark instead of the removed app icon.
    inst = _bare(qapp)
    inst.header = inst._build_header()
    inst._on_active_page_changed(5)                 # Credits is active
    assert inst.header_logo._active is True
    inst._on_active_page_changed(0)                 # back to a dock page
    assert inst.header_logo._active is False


def test_wordmark_present_and_clickable_in_system_title_bar_mode(qapp):
    # Migrated from test_app_icon_present_in_system_title_bar_mode: the point was
    # that Credits stays reachable with the native title bar. The wordmark lives
    # in the header in BOTH frameless and system-title-bar modes, so it is present
    # and clickable regardless of the use_system_title_bar setting.
    from utils.widgets.clickable_logo import ClickableLogo
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _StubSettings(
        hints_enabled=True, theme="dark", use_system_title_bar=True
    )
    called = []
    inst._on_app_icon_clicked = lambda: called.append(True)   # patch before build
    inst.header = inst._build_header()
    logo = inst.header.findChild(ClickableLogo, "header_logo")
    assert logo is not None, "wordmark must exist even with the system title bar"
    logo.clicked.emit()
    assert called == [True]
