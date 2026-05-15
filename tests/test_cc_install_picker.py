"""Tests for the CCInstallPickerDialog."""

import os
import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.wine_runtimes import WineInstall


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _installs():
    return [
        WineInstall("/a/CorporateClash.exe", "bottles", "/a",
                    "Bottles · A", {"bottle_name": "A"}),
        WineInstall("/b/CorporateClash.exe", "lutris", "/b",
                    "Lutris · B", {}),
    ]


def test_picker_shows_all_installs(qapp):
    from utils.widgets.cc_install_picker import CCInstallPickerDialog
    dlg = CCInstallPickerDialog(_installs())
    rows = dlg.list_widget.count() if hasattr(dlg, "list_widget") else len(dlg._rows)
    assert rows == 2


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
