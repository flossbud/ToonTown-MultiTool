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
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from main import MultiToonTool
    inst = MultiToonTool.__new__(MultiToonTool)
    inst.settings_manager = _Stub()
    inst.stack = QStackedWidget()
    for _ in range(6):
        inst.stack.addWidget(QWidget())
    inst.stack.setCurrentIndex(0)
    inst.credits_tab = type("C", (), {
        "set_backdrop_source": lambda self, pix: None,
        "cleared": [],
        "clear_backdrop": lambda self: type(self).cleared.append(True),
    })()
    inst.chip_buttons = []
    inst._apply_chip_styles = lambda: None
    inst._initialized_nav = True
    return inst


def test_icon_enters_then_returns(qapp, monkeypatch):
    inst = _app(qapp, monkeypatch)
    inst._on_app_icon_clicked()                 # from tab 0 -> credits
    assert inst.stack.currentIndex() == 5
    assert inst._credits_open is True
    assert inst._credits_transitioning is False   # reduced motion cleared the guard
    inst._on_app_icon_clicked()                 # toggle back -> tab 0
    assert inst.stack.currentIndex() == 0
    assert inst._credits_open is False
    assert inst._credits_transitioning is False


def test_icon_ignored_while_transitioning(qapp, monkeypatch):
    inst = _app(qapp, monkeypatch)
    inst._credits_open = False
    inst._credits_transitioning = True
    inst._on_app_icon_clicked()                 # ignored
    assert inst.stack.currentIndex() == 0


def test_pre_credits_index_fallback_multitoon(qapp, monkeypatch):
    inst = _app(qapp, monkeypatch)
    inst._credits_open = True
    inst._credits_transitioning = False
    inst._pre_credits_index = 99                # invalid
    inst.stack.setCurrentIndex(5)
    inst._nav_return_from_credits()
    assert inst.stack.currentIndex() == 0       # fell back to Multitoon


def test_return_uses_reverse_vertical_and_reselects_dock_tab(qapp, monkeypatch):
    import utils.motion as motion
    inst = _app(qapp, monkeypatch)

    # Returning from Credits reverse-slides to the pre-Credits tab and drives
    # the glass dock's selected segment back to it (the chip rail is retired).
    selected = []
    inst.nav_dock = type("D", (), {
        "segments": [object()] * 4,
        "select": lambda self, i, animate=True: selected.append(i),
    })()
    called = {}

    def spy_push(stack, frm, to, axis="h", reverse=False):
        called.update(axis=axis, reverse=reverse, to=to)
        stack.setCurrentIndex(to)
        return None

    monkeypatch.setattr(motion, "push_slide_pages", spy_push)
    inst._credits_open = True
    inst._credits_transitioning = False
    inst._pre_credits_index = 2
    inst.stack.setCurrentIndex(5)
    inst._nav_return_from_credits()
    assert called["axis"] == "v" and called["reverse"] is True and called["to"] == 2
    assert selected == [2]


def test_active_page_change_clears_backdrop(qapp, monkeypatch):
    inst = _app(qapp, monkeypatch)
    inst.header_app_icon = type("I", (), {"set_active": lambda self, v: None})()
    inst._credits_open = True
    inst.credits_tab.__class__.cleared.clear()
    inst._on_active_page_changed(0)             # left credits
    assert inst._credits_open is False
    assert inst.credits_tab.__class__.cleared == [True]


def test_active_page_change_self_heals_stuck_transitioning(qapp, monkeypatch):
    # Regression (final-review Important): a chip nav cancels a Credits slide via
    # push_slide_pages' stop(), which does NOT emit `finished`, so
    # _begin_credits_transition's lambda never fires. _on_active_page_changed —
    # which DOES fire via the cancelling nav's currentChanged — must clear the
    # guard, else the header icon toggle is permanently disabled.
    inst = _app(qapp, monkeypatch)
    inst.header_app_icon = type("I", (), {"set_active": lambda self, v: None})()
    inst._credits_transitioning = True          # simulate the stuck guard
    inst._credits_open = True
    inst._on_active_page_changed(1)             # settled on a chip page
    assert inst._credits_transitioning is False
    assert inst._credits_open is False
