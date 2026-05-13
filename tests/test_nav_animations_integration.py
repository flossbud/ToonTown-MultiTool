"""End-to-end smoke test for navigation animations.

Drives rapid chip clicks and asserts the final state is correct with no
orphan proxy widgets on the stack.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

import utils.motion as motion


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture(autouse=True)
def fast_motion(monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)
    monkeypatch.setattr(motion, "_settings", None)


def test_rapid_nav_select_settles_on_last_target(qapp):
    from main import MultiToonTool
    from PySide6.QtWidgets import QStackedWidget, QWidget, QToolButton
    instance = MultiToonTool.__new__(MultiToonTool)

    class _StubSettings:
        def get(self, k, d=None): return d
        def set(self, k, v): pass
    instance.settings_manager = _StubSettings()
    instance.stack = QStackedWidget()
    for i in range(6):
        w = QWidget()
        w.setObjectName(f"page_{i}")
        instance.stack.addWidget(w)
    instance.stack.resize(400, 300)
    instance.stack.show()
    instance.stack.setCurrentIndex(0)
    instance.chip_buttons = [QToolButton() for _ in range(4)]
    for b in instance.chip_buttons:
        b.setCheckable(True)
    instance._apply_chip_styles = lambda: None
    instance._initialized_nav = True
    instance.chip_pill = None  # unused for this test

    # Override the pill call to no-op since we have no real pill mounted.
    def _safe_nav(idx):
        prev = instance.stack.currentIndex()
        instance._initialized_nav = True
        motion.push_slide_pages(instance.stack, prev, idx, axis="h")
        for i, c in enumerate(instance.chip_buttons):
            c.setChecked(i == idx)
    instance.nav_select = _safe_nav

    # Hammer 1 → 3 → 2 → 0 → 3 in quick succession.
    for idx in [1, 3, 2, 0, 3]:
        instance.nav_select(idx)

    # Drive event loop to resolve all animations.
    for _ in range(100):
        qapp.processEvents()
        in_flight = getattr(instance.stack, "_in_flight_anim", None)
        pending_timer = getattr(instance.stack, "_in_flight_timer", None)
        if in_flight is None and (pending_timer is None or not pending_timer.isActive()):
            break

    # Flush deferred deletions so deleteLater() calls from _finalize() resolve.
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()

    assert instance.stack.currentIndex() == 3
    # No orphan proxy labels.
    proxies = [c for c in instance.stack.children() if isinstance(c, QLabel)
               and c.property("is_transition_proxy") and not c.isHidden()]
    assert proxies == []
