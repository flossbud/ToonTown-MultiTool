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


from PySide6.QtGui import QColor

def _picker(qapp, store, start="#4a7cff"):
    from utils.widgets.color_picker_overlay import ColorPickerOverlay
    parent = QWidget(); parent.resize(560, 560); parent.show()
    p = ColorPickerOverlay(parent, saved_store=store)
    p.open_for(start)
    return p, parent

def test_hex_edit_emits_live_and_commit(qapp):
    from utils.saved_colors import SavedColorsStore
    store = SavedColorsStore(_FakeSettings())
    p, parent = _picker(qapp, store)
    live = []; p.color_live.connect(live.append)
    p.set_hex("#11ee22")                 # programmatic edit == dialing in
    assert live and live[-1].upper() == "#11EE22"
    committed = []; p.color_committed.connect(committed.append)
    p.commit()
    assert committed == ["#11ee22"]

def test_auto_preset_commits_none(qapp):
    from utils.saved_colors import SavedColorsStore
    p, parent = _picker(qapp, SavedColorsStore(_FakeSettings()))
    out = []; p.color_committed.connect(out.append)
    p.choose_auto()                      # the "Auto" preset
    assert out == [None]

def test_saved_row_add_and_use(qapp):
    from utils.saved_colors import SavedColorsStore
    store = SavedColorsStore(_FakeSettings())
    p, parent = _picker(qapp, store, start="#abcdef")
    p.save_current()                     # '+' slot saves the dialed-in color
    assert store.get() == ["#abcdef"]
    assert any(s.objectName() == "savedSlot" for s in p.findChildren(QWidget))
