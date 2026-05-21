"""Tests for the compatibility-runtime picker dialog."""

import os
import pytest
from PySide6.QtWidgets import QApplication

from services.steam_proton_tools import ProtonTool

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _tool(name, display, source="compatibilitytools.d", version=(9, 0),
          nickname=None):
    return ProtonTool(
        name=name, display_name=display,
        nickname=nickname if nickname is not None else display,
        proton_dir=f"/fake/{name}",
        source=source, steam_root="/fake", version_key=version,
    )


def test_dialog_shows_auto_card_first(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    dlg = CCCompatPickerDialog(
        tools=[_tool("proton-cachyos", "Proton-CachyOS")],
        current_override="",
        steam_default_display="Proton-CachyOS",
    )
    cards = dlg.cards()
    assert len(cards) >= 1
    # Auto card is index 0 and is selected by default when current_override is empty.
    assert cards[0].property("selected") == "true"


def test_dialog_includes_one_card_per_tool_plus_auto(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    dlg = CCCompatPickerDialog(
        tools=[
            _tool("proton-cachyos", "Proton-CachyOS"),
            _tool("ge-proton9-26", "GE-Proton9-26"),
        ],
        current_override="",
        steam_default_display="Proton-CachyOS",
    )
    # 1 AUTO + 2 PROTONs = 3 cards.
    assert len(dlg.cards()) == 3


def test_dialog_reflects_existing_override(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    dlg = CCCompatPickerDialog(
        tools=[
            _tool("proton-cachyos", "Proton-CachyOS"),
            _tool("ge-proton9-26", "GE-Proton9-26"),
        ],
        current_override="/fake/ge-proton9-26",
        steam_default_display="Proton-CachyOS",
    )
    cards = dlg.cards()
    # Card index 0 = AUTO, 1 = Proton-CachyOS, 2 = GE-Proton9-26.
    assert cards[2].property("selected") == "true"


def test_save_with_auto_selected_returns_empty_string(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    dlg = CCCompatPickerDialog(
        tools=[_tool("proton-cachyos", "Proton-CachyOS")],
        current_override="",
        steam_default_display="Proton-CachyOS",
    )
    dlg._on_save()
    assert dlg.chosen_override() == ""


def test_save_with_specific_proton_returns_proton_dir(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    dlg = CCCompatPickerDialog(
        tools=[_tool("ge-proton9-26", "GE-Proton9-26")],
        current_override="/fake/ge-proton9-26",
        steam_default_display="Proton-CachyOS",
    )
    dlg._on_save()
    assert dlg.chosen_override() == "/fake/ge-proton9-26"


def test_dialog_renders_section_label(qapp):
    """The 'OR PICK A SPECIFIC PROTON VERSION' divider must be present when
    there is at least one specific Proton tool."""
    from PySide6.QtWidgets import QLabel
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    dlg = CCCompatPickerDialog(
        tools=[_tool("proton-cachyos", "Proton-CachyOS")],
        current_override="",
        steam_default_display="Proton-CachyOS",
    )
    labels = dlg.findChildren(QLabel, "picker_section_label")
    texts = [lbl.text() for lbl in labels]
    assert any("PICK A SPECIFIC PROTON" in t.upper() for t in texts)


def test_dialog_omits_section_label_when_no_tools(qapp):
    """Edge case: zero Proton tools -> no divider (auto-mode alone)."""
    from PySide6.QtWidgets import QLabel
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    dlg = CCCompatPickerDialog(
        tools=[],
        current_override="",
        steam_default_display="Proton-CachyOS",
    )
    labels = dlg.findChildren(QLabel, "picker_section_label")
    assert labels == []
