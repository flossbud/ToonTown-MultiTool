import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.keysets.visual_keyboard import VisualKeyboard

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

def _caps(kb):
    return kb._caps

def test_builds_a_keycap_per_code(app):
    kb = VisualKeyboard()
    assert "w" in _caps(kb) and "space" in _caps(kb) and "Up" in _caps(kb)

def test_classification_states(app):
    kb = VisualKeyboard()
    kb.set_state(assign={"w": "forward", "g": "gags"}, conflict_vals=set(),
                 accent_c="#0077ff", accent_b="#3399ff", active_code=None, mac=False)
    assert _caps(kb)["w"].state == "movement"
    assert _caps(kb)["g"].state == "aux"
    assert _caps(kb)["z"].state == "unassigned"

def test_conflict_beats_assignment(app):
    kb = VisualKeyboard()
    kb.set_state(assign={"w": "forward"}, conflict_vals={"w"},
                 accent_c="#0077ff", accent_b="#3399ff", active_code=None, mac=False)
    assert _caps(kb)["w"].state == "conflict"

def test_spotlight_ring(app):
    kb = VisualKeyboard()
    kb.set_state(assign={"w": "forward"}, conflict_vals=set(),
                 accent_c="#0077ff", accent_b="#3399ff", active_code="w", mac=False)
    assert _caps(kb)["w"].spotlight is True

def test_click_emits_canonical(app):
    kb = VisualKeyboard()
    got = []
    kb.key_clicked.connect(got.append)
    _caps(kb)["w"]._emit_click()
    assert got == ["w"]

def test_mac_swaps_bottom_row(app):
    kb = VisualKeyboard()
    kb.set_state(assign={}, conflict_vals=set(), accent_c="#0077ff",
                 accent_b="#3399ff", active_code=None, mac=True)
    assert "Meta_L" in _caps(kb)
