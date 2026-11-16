"""The launcher's pencil opens the customizer by toon identity, and a saved
look reaches both tabs whichever one opened it."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _window(names=(None, None, None, None), games=("ttr", "ttr", "ttr", "ttr")):
    """A MultiToonTool with only the attributes the customizer wiring reads."""
    from main import MultiToonTool
    win = MultiToonTool.__new__(MultiToonTool)
    win.customization_overlay = None
    win._customization_toon = (None, None)
    win.multitoon_tab = SimpleNamespace(
        toon_names=list(names),
        slot_badges=[SimpleNamespace(game=g) for g in games],
        customizations=object(),
        settings_manager=object(),
        _on_customization_saved=MagicMock(),
    )
    win.launch_tab = SimpleNamespace(on_customization_changed=MagicMock())
    overlay = MagicMock()
    overlay.isVisible.return_value = False
    win._ensure_customization_overlay = lambda: overlay
    return win, overlay


def test_the_launcher_opens_the_customizer_by_toon_identity(qapp):
    win, overlay = _window()
    win.open_customization_for_toon("ttr", "Flossbud", "7400", "cat")
    overlay.open_for.assert_called_once()
    kw = overlay.open_for.call_args.kwargs
    assert kw["slot"] == win.LAUNCHER_SLOT == -1
    assert (kw["game"], kw["toon_name"], kw["dna"]) == ("ttr", "Flossbud", "7400")
    assert kw["manager"] is win.multitoon_tab.customizations
    assert kw["auto_stem"] is None                       # TTR draws a render


def test_a_clash_toon_opens_with_its_species_icon(qapp):
    from utils import cc_race_assets
    win, overlay = _window()
    win.open_customization_for_toon("cc", "Salty", "", "duck")
    kw = overlay.open_for.call_args.kwargs
    assert kw["dna"] is None
    assert kw["auto_stem"] == cc_race_assets.asset_stem_for_species("duck")


@pytest.mark.parametrize("game,name", [("ttr", ""), ("ttr", None), ("pp", "X")])
def test_nothing_opens_without_a_toon_or_a_known_game(qapp, game, name):
    win, overlay = _window()
    win.open_customization_for_toon(game, name)
    overlay.open_for.assert_not_called()


def test_nothing_reopens_while_the_overlay_is_showing(qapp):
    win, overlay = _window()
    win.customization_overlay = overlay
    overlay.isVisible.return_value = True
    win.open_customization_for_toon("ttr", "Flossbud", "7400", "cat")
    overlay.open_for.assert_not_called()


def test_a_look_saved_from_the_launcher_reaches_the_slots_playing_that_toon(qapp):
    """-1 must never reach _on_customization_saved: it indexes lists by slot
    and Python would quietly restyle the LAST slot."""
    win, _overlay = _window(
        names=("Hiro", "Flossbud", None, "Flossbud"),
        games=("ttr", "ttr", "ttr", "cc"))
    win.open_customization_for_toon("ttr", "Flossbud", "7400", "cat")
    win._on_customization_changed(win.LAUNCHER_SLOT, "ttr")
    saved = win.multitoon_tab._on_customization_saved
    # Slot 1 plays Flossbud on TTR. Slot 3 is a Clash toon of the same name:
    # looks key on game::name, so it is a different look.
    assert [c.args for c in saved.call_args_list] == [(1, "ttr")]
    win.launch_tab.on_customization_changed.assert_called_once_with("ttr")


def test_a_look_saved_from_the_launcher_with_the_toon_not_running(qapp):
    win, _overlay = _window(names=("Hiro", None, None, None))
    win.open_customization_for_toon("ttr", "Flossbud", "7400", "cat")
    win._on_customization_changed(win.LAUNCHER_SLOT, "ttr")
    win.multitoon_tab._on_customization_saved.assert_not_called()
    win.launch_tab.on_customization_changed.assert_called_once_with("ttr")


def test_a_look_saved_from_a_multitoon_slot_also_repaints_the_launcher(qapp):
    win, _overlay = _window(names=("Hiro", "Flossbud", None, None))
    win._on_customization_changed(1, "ttr")
    win.multitoon_tab._on_customization_saved.assert_called_once_with(1, "ttr")
    win.launch_tab.on_customization_changed.assert_called_once_with("ttr")
