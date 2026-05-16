"""Tests for the compatibility-runtime picker dialog."""

import os
import pytest
from PySide6.QtWidgets import QApplication

from services.steam_proton_tools import ProtonTool

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _tool(name, display, source="compatibilitytools.d", version=(9, 0),
          nickname=None):
    return ProtonTool(
        name=name, display_name=display,
        nickname=nickname if nickname is not None else display,
        proton_dir=f"/fake/{name}",
        source=source, steam_root="/fake", version_key=version,
    )


def test_dialog_shows_use_steam_default_first(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    tools = [_tool("proton-cachyos", "Proton-CachyOS")]
    dlg = CCCompatPickerDialog(
        tools=tools,
        current_override="",
        steam_default_display="Proton-CachyOS",
    )
    assert dlg.use_steam_radio.isChecked()
    assert not dlg.use_specific_radio.isChecked()


def test_dialog_reflects_existing_override(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    tools = [
        _tool("proton-cachyos", "Proton-CachyOS"),
        _tool("ge-proton9-26", "GE-Proton9-26"),
    ]
    dlg = CCCompatPickerDialog(
        tools=tools,
        current_override="/fake/ge-proton9-26",
        steam_default_display="Proton-CachyOS",
    )
    assert dlg.use_specific_radio.isChecked()
    row = dlg.list_widget.currentRow()
    assert dlg.list_widget.item(row).text().startswith("GE-Proton9-26")


def test_save_with_steam_default_returns_empty_string(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    tools = [_tool("proton-cachyos", "Proton-CachyOS")]
    dlg = CCCompatPickerDialog(
        tools=tools, current_override="", steam_default_display="Proton-CachyOS",
    )
    dlg.use_steam_radio.setChecked(True)
    dlg._on_save()
    assert dlg.chosen_override() == ""


def test_save_with_specific_proton_returns_proton_dir(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    tools = [_tool("proton-cachyos", "Proton-CachyOS")]
    dlg = CCCompatPickerDialog(
        tools=tools, current_override="", steam_default_display="Proton-CachyOS",
    )
    dlg.use_specific_radio.setChecked(True)
    dlg.list_widget.setCurrentRow(0)
    dlg._on_save()
    assert dlg.chosen_override() == "/fake/proton-cachyos"


def test_source_tags_applied(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    tools = [
        _tool("proton-cachyos", "long-dirty-vdf-display-name",
              source="compatibilitytools.d", nickname="Proton-CachyOS 11.0"),
        _tool("proton_9", "Proton 9.0 (Beta)",
              source="official", nickname="Proton 9.0 (Beta)"),
    ]
    dlg = CCCompatPickerDialog(
        tools=tools, current_override="",
        steam_default_display="Proton-CachyOS 11.0",
    )
    item0 = dlg.list_widget.item(0).text()
    item1 = dlg.list_widget.item(1).text()
    # The picker must display the nickname, not the display_name.
    assert "Proton-CachyOS 11.0" in item0
    assert "long-dirty-vdf-display-name" not in item0
    assert "Proton 9.0 (Beta)" in item1
    # Source tags still rendered.
    assert "[user]" in item0
    assert "[official]" in item1


def test_cancel_returns_none(qapp):
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    tools = [_tool("proton-cachyos", "Proton-CachyOS")]
    dlg = CCCompatPickerDialog(
        tools=tools, current_override="", steam_default_display="Proton-CachyOS",
    )
    dlg.reject()
    assert dlg.chosen_override() is None


def test_stale_override_falls_back_to_steam_default(qapp):
    """If current_override doesn't match any tool, fall back to
    'Use Steam's selection' rather than leaving 'specific' checked
    with no row selected. Bug-fix regression test."""
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    tools = [_tool("proton-cachyos", "Proton-CachyOS")]
    dlg = CCCompatPickerDialog(
        tools=tools,
        current_override="/fake/uninstalled-proton",
        steam_default_display="Proton-CachyOS",
    )
    assert dlg.use_steam_radio.isChecked()
    assert not dlg.use_specific_radio.isChecked()


def test_save_specific_with_no_row_rejects(qapp):
    """Defensive: if 'specific' is checked but no row is selected,
    Save treats it as Cancel (returns None)."""
    from utils.widgets.cc_compat_picker import CCCompatPickerDialog
    tools = [_tool("proton-cachyos", "Proton-CachyOS")]
    dlg = CCCompatPickerDialog(
        tools=tools,
        current_override="",
        steam_default_display="Proton-CachyOS",
    )
    dlg.use_specific_radio.setChecked(True)
    dlg.list_widget.setCurrentRow(-1)
    dlg._on_save()
    assert dlg.chosen_override() is None
    assert dlg.result() == dlg.DialogCode.Rejected
