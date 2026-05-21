"""Tests for the CCInstallPickerDialog."""

import os
import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.wine_runtimes import WineInstall, install_signature


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _installs(tmp_path):
    """Create three installs whose exe_paths all exist on disk."""
    paths = []
    for sub in ("a", "b", "c"):
        d = tmp_path / sub
        d.mkdir()
        exe = d / "CorporateClash.exe"
        exe.write_text("stub")
        paths.append(str(exe))
    return [
        WineInstall(paths[0], "bottles", str(tmp_path / "a"),
                    "Bottles · A", {"bottle_name": "A"}),
        WineInstall(paths[1], "lutris", str(tmp_path / "b"),
                    "Lutris · B", {}),
        WineInstall(paths[2], "faugus", str(tmp_path / "c"),
                    "Faugus · C", {"faugus_runner": "Proton"}),
    ]


def test_picker_shows_all_installs(qapp, tmp_path):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    dlg = CCInstallPickerDialog(_installs(tmp_path))
    assert len(dlg.cards()) == 3


def test_picker_returns_selected_install(qapp, tmp_path):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    installs = _installs(tmp_path)
    dlg = CCInstallPickerDialog(installs)
    dlg.select_index(1)
    assert dlg.selected_install() is installs[1]


def test_picker_no_selection_until_user_picks(qapp, tmp_path):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    dlg = CCInstallPickerDialog(_installs(tmp_path))
    assert dlg.selected_install() is None


def test_picker_renders_faugus_chip_label(qapp, tmp_path):
    """The Faugus row's PickerCard exposes 'FAUGUS' as its chip label."""
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    from utils.widgets.picker_card import PickerChip
    dlg = CCInstallPickerDialog(_installs(tmp_path))
    faugus_card = dlg.cards()[2]
    chip_label = faugus_card.findChild(type(faugus_card._name_label), "picker_chip")
    assert chip_label is not None
    assert chip_label.text() == PickerChip.label_for("faugus")


def test_picker_active_signature_marks_and_preselects(qapp, tmp_path):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    installs = _installs(tmp_path)
    active_sig = install_signature(installs[1])
    dlg = CCInstallPickerDialog(installs, active_signature=active_sig)
    cards = dlg.cards()
    assert cards[1].property("active") == "true"
    assert cards[1].property("selected") == "true"
    assert dlg.selected_install() is installs[1]


def test_picker_active_signature_no_match_renders_clean(qapp, tmp_path):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    dlg = CCInstallPickerDialog(_installs(tmp_path), active_signature="orphan")
    for c in dlg.cards():
        assert c.property("active") == "false"
    assert dlg.selected_install() is None


def test_picker_confirm_label_flips(qapp, tmp_path):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    installs = _installs(tmp_path)
    active_sig = install_signature(installs[0])
    dlg = CCInstallPickerDialog(installs, active_signature=active_sig)
    assert dlg.confirm_btn.text() == "Keep this install"
    dlg.select_index(1)
    assert dlg.confirm_btn.text() == "Use this install"
    dlg.select_index(0)
    assert dlg.confirm_btn.text() == "Keep this install"


def test_stale_install_filtered_when_not_active(qapp, tmp_path):
    """A stale install whose signature does NOT match active_signature is
    dropped from the rendered card list entirely."""
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    installs = _installs(tmp_path)
    # Mutate installs[2] to point at a non-existent path.
    installs[2] = WineInstall(
        "/nonexistent/CorporateClash.exe", "faugus",
        "/nonexistent", "Faugus · gone", {},
    )
    dlg = CCInstallPickerDialog(installs)
    assert len(dlg.cards()) == 2
    # The remaining cards correspond to installs[0] and installs[1] only.


def test_stale_install_kept_when_matches_active(qapp, tmp_path):
    """A stale install whose signature DOES match active_signature is rendered
    with stale=True so the user can see why their last pick is broken."""
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    installs = _installs(tmp_path)
    stale = WineInstall(
        "/nonexistent/CorporateClash.exe", "wine",
        "/nonexistent", "Plain Wine · gone", {},
    )
    installs.append(stale)
    sig = install_signature(stale)
    dlg = CCInstallPickerDialog(installs, active_signature=sig)
    cards = dlg.cards()
    assert len(cards) == 4
    # The stale card is rendered as stale and is not pickable.
    stale_card = cards[-1]
    assert stale_card.property("stale") == "true"


def test_stale_card_does_not_become_selected_on_click(qapp, tmp_path):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    installs = _installs(tmp_path)
    stale = WineInstall(
        "/nonexistent/CorporateClash.exe", "wine",
        "/nonexistent", "Stale", {},
    )
    installs.append(stale)
    sig = install_signature(stale)
    dlg = CCInstallPickerDialog(installs, active_signature=sig)
    # selected_install starts None (stale row doesn't preselect even though
    # active_signature matches it).
    assert dlg.selected_install() is None


def test_short_path_does_not_collapse_strict_prefix(qapp, monkeypatch, tmp_path):
    """If $HOME is /home/jaret, a path under /home/jaret2 must NOT be
    rendered as ~2/... - only $HOME-rooted paths get the ~ collapse."""
    from utils.widgets.cc_install_picker import _short_path
    monkeypatch.setenv("HOME", "/home/jaret")
    assert _short_path("/home/jaret2/CorporateClash.exe") == "/home/jaret2/CorporateClash.exe"
    assert _short_path("/home/jaret/CorporateClash.exe") == "~/CorporateClash.exe"
    assert _short_path("/home/jaret") == "~"
    assert _short_path("/var/other/CorporateClash.exe") == "/var/other/CorporateClash.exe"
