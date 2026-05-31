import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Stub:
    def get(self, key, default=None):
        return default
    def on_change(self, cb):
        pass


def _app(qapp, monkeypatch):
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)   # snap, deterministic
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _Stub()
    inst.stack = QStackedWidget()
    for _ in range(6):
        inst.stack.addWidget(QWidget())
    inst.stack.setCurrentIndex(0)
    inst.credits_tab = type("C", (), {
        "_calls": [],
        "set_backdrop_source": lambda self, pix: type(self)._calls.append(pix),
        "clear_backdrop": lambda self: None,
    })()
    inst.chip_buttons = []
    inst._apply_chip_styles = lambda: None
    return inst


def test_entry_sets_backdrop_before_switch(qapp, monkeypatch):
    inst = _app(qapp, monkeypatch)
    inst._initialized_nav = True
    inst.nav_select_credits()
    assert inst.credits_tab._calls, "backdrop source must be set on entry"
    assert inst.stack.currentIndex() == 5
    assert inst._pre_credits_index == 0
    assert inst._credits_open is True
    assert inst._credits_transitioning is False   # reduced motion clears immediately


def test_entry_noop_when_already_on_credits(qapp, monkeypatch):
    inst = _app(qapp, monkeypatch)
    inst._initialized_nav = True
    inst.stack.setCurrentIndex(5)
    inst.credits_tab._calls.clear()
    inst.nav_select_credits()
    assert inst.credits_tab._calls == []           # no capture, no-op


def test_entry_captures_backdrop_before_slide(qapp, monkeypatch):
    import utils.motion as motion
    inst = _app(qapp, monkeypatch)
    inst._initialized_nav = True
    order = []
    inst.credits_tab.set_backdrop_source = lambda pix: order.append("backdrop")

    def spy_push(stack, frm, to, axis="h", reverse=False):
        order.append("push")
        stack.setCurrentIndex(to)
        return None

    monkeypatch.setattr(motion, "push_slide_pages", spy_push)
    inst.nav_select_credits()
    assert order == ["backdrop", "push"]
