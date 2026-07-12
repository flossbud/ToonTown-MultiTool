"""set_card_brand builds a CardPalette and the dim fan-out uses its ink."""
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


def test_light_off_card_paints_paper_and_dark_ink(make_tab):
    tab = make_tab("light")
    layout = tab._compact
    layout.set_card_brand(0, "ttr", enabled=False)
    cell = layout._cells[layout._slot_to_cell[0]]
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(False)
    top, bot, border = cell["bg"]._resolved_colors()
    assert top == QColor(c["bg_card_inner"])
    assert bot == QColor(c["bg_card_inner_hover"])
    name_qss = tab.toon_labels[0][0].styleSheet()
    assert "rgba(71,85,105,1.000)" in name_qss          # text_muted, opaque
    stat_qss = tab.laff_labels[0].styleSheet()
    assert "rgba(100,116,139,1.000)" in stat_qss        # text_disabled


def test_dark_off_card_stylesheets_are_byte_identical_to_legacy(make_tab):
    tab = make_tab("dark")
    layout = tab._compact
    layout.set_card_brand(0, "ttr", enabled=False)
    name_qss = tab.toon_labels[0][0].styleSheet()
    assert "rgba(255,255,255,0.620)" in name_qss
    stat_qss = tab.laff_labels[0].styleSheet()
    assert "rgba(255,255,255,0.500)" in stat_qss


def test_light_lit_card_paints_vivid(make_tab):
    tab = make_tab("light")
    tab.service_running = True
    layout = tab._compact
    layout.set_card_brand(0, "ttr", enabled=True)
    cell = layout._cells[layout._slot_to_cell[0]]
    from utils.color_math import lighten_rgb
    from utils.theme_manager import get_theme_colors
    ttr = QColor(get_theme_colors(False)["game_pill_ttr"])
    top, _, border = cell["bg"]._resolved_colors()
    assert top == lighten_rgb(ttr, 0.58)
    assert border == ttr
