"""Theme-aware KA glass capsule, recessed power chip, white track and
feature-pill ink family are wired from the CardPalette by the style-writer."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)
    window_geometry_updated = Signal(int)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = [101]
        self.window_games = {101: "ttr"}

    def get_window_ids(self): return list(self.ttr_window_ids)
    def get_window_geometry(self, wid): return (0, 0, 800, 600)
    def get_active_window(self): return None
    def clear_window_ids(self): pass
    def assign_windows(self): pass
    def enable_detection(self): pass
    def disable_detection(self): pass


@pytest.fixture()
def make_tab(qapp, tmp_path, monkeypatch):
    # LAW: isolate config BEFORE importing MultitoonTab; never touch real config.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    import services.wine_runtimes as wr
    monkeypatch.setattr(wr, "discover_cc_installs", lambda *a, **k: [])
    created = []

    def _make(theme):
        from tabs.multitoon._tab import MultitoonTab
        from utils.settings_manager import SettingsManager
        sm = SettingsManager()
        sm.set("theme", theme)
        tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWindowManager())
        created.append(tab)
        for _ in range(3):
            qapp.processEvents()
        return tab

    yield _make
    for tab in created:
        try:
            tab.input_service.shutdown()   # LAW: non-daemon InputService leaks
        except Exception:
            pass
        tab.deleteLater()
    qapp.processEvents()


def test_light_ka_capsule_uses_glass_tokens(make_tab):
    tab = make_tab("light")
    layout = tab._compact
    layout.set_card_brand(0, "ttr", enabled=False)
    cell_idx = layout._slot_to_cell[0]
    qss = layout._cells[cell_idx]["ka_pill"].styleSheet()
    assert "rgba(0,0,0,0.06)" in qss and "rgba(0,0,0,0.13)" in qss


def test_dark_ka_capsule_unchanged(make_tab):
    tab = make_tab("dark")
    layout = tab._compact
    layout.set_card_brand(0, "ttr", enabled=False)
    cell_idx = layout._slot_to_cell[0]
    qss = layout._cells[cell_idx]["ka_pill"].styleSheet()
    assert "rgba(0,0,0,0.24)" in qss and "rgba(0,0,0,0.30)" in qss


def test_light_power_chip_off_uses_solid_tokens(make_tab):
    tab = make_tab("light")
    # The power chip's OFF styling is driven by apply_visual_state's live
    # state, not set_card_brand; the fixture auto-starts the service (button
    # ON), so force the card OFF to exercise the neutral-chip path.
    tab.service_running = False
    tab.apply_visual_state(0)
    qss = tab.toon_buttons[0].styleSheet()
    assert "#e2e8f0" in qss and "#cbd5e1" in qss


def test_dark_power_chip_off_unchanged(make_tab):
    tab = make_tab("dark")
    tab.service_running = False
    tab.apply_visual_state(0)
    qss = tab.toon_buttons[0].styleSheet()
    assert "rgba(0,0,0,0.24)" in qss


def test_light_track_color_is_white(make_tab):
    from utils.theme_manager import get_theme_colors
    from PySide6.QtGui import QColor
    tab = make_tab("light")
    tab._compact.set_card_brand(0, "ttr", enabled=False)
    c = get_theme_colors(False)
    # Light mode: the unfilled track is WHITE (bg_card), lit or off.
    assert tab.ka_progress_bars[0].bg_color() == QColor(c["bg_card"])


def test_feature_pill_light_chrome_flag(make_tab):
    tab = make_tab("light")
    tab._compact.set_card_brand(0, "ttr", enabled=False)
    assert tab.feature_pills[0]._light_chrome is True
    tab2 = make_tab("dark")
    tab2._compact.set_card_brand(0, "ttr", enabled=False)
    assert tab2.feature_pills[0]._light_chrome is False
