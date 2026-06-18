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


def test_live_color_updates_current_and_emits(qapp):
    """color_live from the picker must update current() and emit color_picked
    with the live hex while the picker is still open."""
    from utils.widgets.color_well import ColorWell
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.color_picker_overlay import ColorPickerOverlay

    parent = QWidget(); parent.show()
    w = ColorWell(current="#ff0000", saved_store=SavedColorsStore(_FakeSettings()), parent=parent)
    picks = []
    w.color_picked.connect(picks.append)

    # Open the picker and capture the overlay instance.
    w._open_picker()
    picker = parent.findChild(ColorPickerOverlay)
    assert picker is not None

    # Simulate a live drag event.
    picker.color_live.emit("#00ff00")
    assert w.current() == "#00ff00"
    assert picks == ["#00ff00"]


def test_cancelled_reverts_to_original(qapp):
    """Cancelling the picker must revert current() to the value when the
    picker was opened and emit color_picked with the original hex."""
    from utils.widgets.color_well import ColorWell
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.color_picker_overlay import ColorPickerOverlay

    parent = QWidget(); parent.show()
    w = ColorWell(current="#ff0000", saved_store=SavedColorsStore(_FakeSettings()), parent=parent)
    picks = []
    w.color_picked.connect(picks.append)

    w._open_picker()
    picker = parent.findChild(ColorPickerOverlay)
    assert picker is not None

    # Simulate a live drag then a cancel.
    picker.color_live.emit("#123456")
    assert w.current() == "#123456"

    picker.cancelled.emit()
    assert w.current() == "#ff0000"
    assert picks[-1] == "#ff0000"


def test_committed_finalizes_color(qapp):
    """color_committed must finalize current() to the committed hex and emit."""
    from utils.widgets.color_well import ColorWell
    from utils.saved_colors import SavedColorsStore
    from utils.widgets.color_picker_overlay import ColorPickerOverlay

    parent = QWidget(); parent.show()
    w = ColorWell(current="#ff0000", saved_store=SavedColorsStore(_FakeSettings()), parent=parent)
    picks = []
    w.color_picked.connect(picks.append)

    w._open_picker()
    picker = parent.findChild(ColorPickerOverlay)
    assert picker is not None

    picker.color_live.emit("#abcdef")
    picker.color_committed.emit("#abcdef")
    assert w.current() == "#abcdef"
    assert "#abcdef" in picks


def test_well_none_store_opens_picker_without_crash(qapp):
    """ColorWell(saved_store=None) must coerce None to an in-memory store and
    open the picker without raising."""
    from utils.widgets.color_well import ColorWell
    from utils.widgets.color_picker_overlay import ColorPickerOverlay
    parent = QWidget(); parent.show()
    w = ColorWell(current="#ff0000", saved_store=None, parent=parent)
    # Store must be a live SavedColorsStore, not None.
    from utils.saved_colors import SavedColorsStore
    assert isinstance(w._store, SavedColorsStore)
    # Opening the picker must not raise; a ColorPickerOverlay child is created.
    w._open_picker()
    overlays = [c for c in parent.findChildren(ColorPickerOverlay)]
    assert len(overlays) >= 1
