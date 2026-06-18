from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
import pytest
from PySide6.QtWidgets import QApplication, QWidget

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app

class _FakeSettings:
    def __init__(self, d=None): self._d = dict(d or {})
    def get(self, k, default=None): return self._d.get(k, default)
    def set(self, k, v): self._d[k] = v


def test_well_mirrors_swatchrow_api(qapp):
    from utils.widgets.color_well import ColorWell
    from utils.saved_colors import SavedColorsStore
    parent = QWidget(); parent.show()
    w = ColorWell(current="#4a7cff", saved_store=SavedColorsStore(_FakeSettings()), parent=parent)
    assert w.current() == "#4a7cff"
    picks = []; w.color_picked.connect(picks.append)
    w._apply_committed("#11ee22")          # simulate picker commit
    assert picks == ["#11ee22"] and w.current() == "#11ee22"
    w._apply_committed(None)                # Auto / default
    assert picks[-1] is None and w.current() is None
    w.set_current("#abcdef")                # programmatic: no emit
    assert w.current() == "#abcdef" and picks[-1] is None   # still the prior emit
