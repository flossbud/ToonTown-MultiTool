"""The emblem broadcast pulse is gated on game-window occupancy: the endless
loop(-1) pulse animation runs ONLY while the service is running AND at least
one cell holds a game window. With no game windows there is nothing to
broadcast to - and in float mode each ~60Hz pulse tick dirtied the whole
proxied host, which FullViewportUpdate escalated to a full-window ARGB
repaint (~38% idle CPU measured live, 2026-07-05). The gate makes the idle
cost zero by construction.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen HOME=$(mktemp -d) \
      TTMT_CONFIG_DIR=$(mktemp -d) PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
      ./venv/bin/python -m pytest tests/test_emblem_pulse_gate.py -q
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtCore import QAbstractAnimation, QObject, Signal
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWM(QObject):
    window_ids_updated = Signal(list)
    cell_assignment_changed = Signal(list)
    window_geometry_updated = Signal()
    active_window_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []
        self.slot_cells = [0, 1, 2, 3]

    def get_window_ids(self):
        return []

    def get_active_window(self):
        return None

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass

    def count_for_game(self, game):
        return 0

    def get_window_geometry(self, wid):
        return None


def _build_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager

    tab = MultitoonTab(settings_manager=SettingsManager(), window_manager=_FakeWM())
    for _ in range(3):
        qapp.processEvents()
    return tab


def _pulse_running(emblem) -> bool:
    return emblem._anim.state() == QAbstractAnimation.State.Running


def test_no_pulse_while_idle_even_with_service_running(qapp, tmp_path, monkeypatch):
    """Service on + zero occupied cells -> the pulse animation must NOT run."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    try:
        c = tab._compact
        tab.service_running = True
        c._refresh_emblem()
        assert not c._emblem_pulse_active()
        assert not _pulse_running(c._emblem)
        # The gate stops ONLY the animation: a running service must still
        # LOOK armed (colored icon + lit ring at pulse 1.0) - the first gate
        # greyed the emblem ("darker and less saturated", 2026-07-05).
        assert c._emblem._broadcasting is True
        assert c._emblem._pulse == 1.0
    finally:
        tab.input_service.shutdown()


def test_no_pulse_with_occupancy_but_service_off(qapp, tmp_path, monkeypatch):
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    try:
        c = tab._compact
        tab.service_running = False
        monkeypatch.setattr(c, "occupied_cells", lambda: frozenset({0}))
        c._refresh_emblem()
        assert not _pulse_running(c._emblem)
        assert c._emblem._broadcasting is False   # service off -> grey is right
    finally:
        tab.input_service.shutdown()


def test_pulse_starts_and_stops_with_occupancy(qapp, tmp_path, monkeypatch):
    """The occupancy notifier drives the gate both ways: first game window ->
    pulse starts; last game window gone -> pulse stops and settles at 1.0."""
    tab = _build_tab(qapp, tmp_path, monkeypatch)
    try:
        c = tab._compact
        tab.service_running = True
        assert not _pulse_running(c._emblem)

        monkeypatch.setattr(c, "occupied_cells", lambda: frozenset({0}))
        c._notify_occupancy()
        assert _pulse_running(c._emblem)

        monkeypatch.setattr(c, "occupied_cells", lambda: frozenset())
        c._notify_occupancy()
        assert not _pulse_running(c._emblem)
        assert c._emblem._pulse == 1.0
    finally:
        tab.input_service.shutdown()
