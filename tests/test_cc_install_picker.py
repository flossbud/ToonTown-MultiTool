"""Tests for the CCInstallPickerDialog."""

import os
import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.wine_runtimes import WineInstall, install_signature


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _installs():
    return [
        WineInstall("/a/CorporateClash.exe", "bottles", "/a",
                    "Bottles · A", {"bottle_name": "A"}),
        WineInstall("/b/CorporateClash.exe", "lutris", "/b",
                    "Lutris · B", {}),
        WineInstall("/c/CorporateClash.exe", "faugus", "/c",
                    "Faugus · C", {"faugus_install_kind": "flatpak",
                                   "faugus_runner": "Proton-CachyOS Latest"}),
    ]


def test_picker_shows_all_installs(qapp):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    dlg = CCInstallPickerDialog(_installs())
    assert dlg.list_widget.count() == 3


def test_picker_returns_selected_install(qapp):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    installs = _installs()
    dlg = CCInstallPickerDialog(installs)
    dlg.select_index(1)
    assert dlg.selected_install() is installs[1]


def test_picker_no_selection_until_user_picks(qapp):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    dlg = CCInstallPickerDialog(_installs())
    assert dlg.selected_install() is None


def test_picker_renders_faugus_chip(qapp):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    dlg = CCInstallPickerDialog(_installs())
    text = dlg.list_widget.item(2).text()
    assert "[FAUGUS]" in text
    assert "Faugus · C" in text


def test_picker_active_signature_marks_row_and_preselects(qapp):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    installs = _installs()
    active_sig = install_signature(installs[1])
    dlg = CCInstallPickerDialog(installs, active_signature=active_sig)
    assert "(currently active)" in dlg.list_widget.item(1).text()
    assert dlg.list_widget.currentRow() == 1
    assert dlg.selected_install() is installs[1]


def test_picker_active_signature_no_match_renders_clean(qapp):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    dlg = CCInstallPickerDialog(_installs(), active_signature="orphan-sig")
    for i in range(dlg.list_widget.count()):
        assert "(currently active)" not in dlg.list_widget.item(i).text()
    assert dlg.list_widget.currentRow() in (-1, 0)
    assert dlg.selected_install() is None


def test_picker_confirm_label_flips(qapp):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    installs = _installs()
    active_sig = install_signature(installs[0])
    dlg = CCInstallPickerDialog(installs, active_signature=active_sig)
    assert dlg.confirm_btn.text() == "Keep this install"
    dlg.list_widget.setCurrentRow(1)
    assert dlg.confirm_btn.text() == "Use this install"
    dlg.list_widget.setCurrentRow(0)
    assert dlg.confirm_btn.text() == "Keep this install"
