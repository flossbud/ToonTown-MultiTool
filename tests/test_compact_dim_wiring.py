import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)
    cell_assignment_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
        self.slot_cells = [0, 1, 2, 3]

    def get_window_ids(self): return []
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass
    def get_active_window(self): return None


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    # The dim is gated by effects_disabled(); ensure a perf-flag in the ambient
    # env can't flip the assertion.
    monkeypatch.delenv("TTMT_NO_EFFECTS", raising=False)
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    tab = MultitoonTab(
        settings_manager=SettingsManager(),
        window_manager=_FakeWindowManager(),
    )
    for _ in range(3):
        qapp.processEvents()
    return tab


def test_inactive_slot_snaps_dim_on_first_paint(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    try:
        tab.apply_visual_state(0)   # no windows -> inactive; FIRST paint -> snap to 1
        assert tab.slot_badges[0]._dim_progress == 1.0
        assert tab.set_selectors[0]._dim_progress == 1.0
        cell = tab._compact._cells[0]
        anim = cell.get("dim_anim")
        from PySide6.QtCore import QAbstractAnimation
        assert anim is None or anim.state() != QAbstractAnimation.Running
    finally:
        if hasattr(tab, "input_service") and hasattr(tab.input_service, "shutdown"):
            tab.input_service.shutdown()


def test_lit_to_dim_transition_starts_animation(qapp, tmp_path, monkeypatch):
    # The animate branch (construct + connect + start the QVariantAnimation) only
    # fires on a lit->dim transition on a VISIBLE card. The offscreen tab is never
    # shown, so force the visibility gate to exercise the real wiring.
    from PySide6.QtCore import QAbstractAnimation
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    try:
        tab.apply_visual_state(0)                  # first paint -> snap (dim_target=1.0)
        cell = tab._compact._cells[0]
        cell["cell"].isVisible = lambda: True      # force the visible gate
        cell["dim_target"] = 0.0                   # pretend it was lit -> next call transitions
        cell.pop("dim_anim", None)
        tab._compact.set_card_brand(0, None, enabled=False)   # lit(0)->dim(1) -> animate
        anim = cell.get("dim_anim")
        assert anim is not None
        assert anim.state() == QAbstractAnimation.Running
        assert cell["dim_target"] == 1.0
    finally:
        if hasattr(tab, "input_service") and hasattr(tab.input_service, "shutdown"):
            tab.input_service.shutdown()


def test_mid_fade_guard_does_not_restart_running_anim(qapp, tmp_path, monkeypatch):
    # A reconfigure while a lit->dim fade is in flight must NOT snap/restart it
    # (the `running and target == 1.0` guard).
    from PySide6.QtCore import QVariantAnimation, QAbstractAnimation
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    try:
        tab.apply_visual_state(0)            # first paint -> snaps to dim
        cell = tab._compact._cells[0]
        anim = QVariantAnimation(cell["cell"])
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(5000)
        anim.start()
        cell["dim_anim"] = anim
        cell["dim_target"] = 1.0             # simulate mid-fade-toward-dim state
        # Re-style the still-inactive slot: the guard must leave the anim running.
        tab._compact.set_card_brand(0, None, enabled=False)
        assert anim.state() == QAbstractAnimation.Running
    finally:
        if hasattr(tab, "input_service") and hasattr(tab.input_service, "shutdown"):
            tab.input_service.shutdown()


def test_effects_disabled_gate_suppresses_dim(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    try:
        monkeypatch.setenv("TTMT_NO_EFFECTS", "1")
        tab.apply_visual_state(0)
        assert tab.slot_badges[0]._dim_progress == 0.0
        assert tab.set_selectors[0]._dim_progress == 0.0
    finally:
        if hasattr(tab, "input_service") and hasattr(tab.input_service, "shutdown"):
            tab.input_service.shutdown()
