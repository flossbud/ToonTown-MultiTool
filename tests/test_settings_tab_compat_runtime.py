"""Tests for the compatibility-runtime field on the CC panel (Games page).

The field appears under the CC panel and is hidden on Windows and when no
CC install is configured. State lives on SettingsTab as:
    tab._compat_field        — the InsetRow widget
    tab._compat_change_btn   — the Change… QPushButton
    tab._refresh_compat_runtime_row() — rebuild label from settings
    tab._on_compat_change_clicked()   — Change… handler
    tab._get_active_cc_install()      — resolves the current install
"""

import os
import sys
import pytest
from PySide6.QtWidgets import QApplication

from services.wine_runtimes import WineInstall
from services.steam_proton_tools import ProtonTool

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _SM:
    def __init__(self, initial=None):
        self.values = dict(initial or {})
    def get(self, k, d=None):
        return self.values.get(k, d)
    def set(self, k, v):
        self.values[k] = v
    def on_change(self, cb):
        pass


def _proton_dir(tmp_path, name):
    d = tmp_path / name
    d.mkdir(parents=True)
    bin_ = d / "proton"
    bin_.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(bin_, 0o755)
    return str(d)


def _steam_install(tmp_path, proton_dir):
    pfx = tmp_path / "prefix"
    pfx.mkdir(parents=True)
    exe = pfx / "fake.exe"
    exe.write_text("")
    return WineInstall(
        exe_path=str(exe), launcher="steam-proton", prefix_path=str(pfx),
        display_name="Steam · CC",
        metadata={"appid": "9999", "steam_root": "/fake",
                  "proton_dir": proton_dir},
    )


def _build_tab(sm):
    """Build a SettingsTab without invoking the Games page (so we can
    construct the compat field in isolation, without depending on a real
    cc_engine_dir on disk). Returns the tab."""
    from tabs.settings_tab import SettingsTab
    return SettingsTab(settings_manager=sm)


def test_compat_field_hidden_on_windows(qapp, tmp_path, monkeypatch):
    """On Windows, the compat field is never added to the CC card."""
    monkeypatch.setattr(sys, "platform", "win32")
    sm = _SM()
    tab = _build_tab(sm)
    # On Windows, _build_games_page never calls cc_card.add_row(compat_row)
    # so the row exists but is never parented into the card.
    assert hasattr(tab, "_compat_field")
    assert tab._compat_field.parent() is None


def test_steam_proton_no_override_shows_default_suffix(qapp, tmp_path, monkeypatch):
    """Linux + steam-proton + no override → helper text ends with '· default'."""
    monkeypatch.setattr(sys, "platform", "linux")
    proton = _proton_dir(tmp_path, "ProtonCachy")
    install = _steam_install(tmp_path, proton)

    sm = _SM()
    monkeypatch.setattr(
        "services.cc_launcher.resolve_effective_proton",
        lambda inst, s: proton,
    )
    monkeypatch.setattr(
        "services.steam_proton_tools.enumerate_proton_tools",
        lambda: [ProtonTool(
            name="proton-cachyos", display_name="Proton-CachyOS",
            nickname="Proton-CachyOS", proton_dir=proton,
            source="compatibilitytools.d", steam_root="/fake",
            version_key=(9, 0),
        )],
    )
    tab = _build_tab(sm)
    # Force the active install resolver to return our test install
    monkeypatch.setattr(tab, "_get_active_cc_install", lambda: install)
    tab._refresh_compat_runtime_row()

    text = tab._compat_field.helper_widget.text()
    assert " · default" in text
    assert "Proton-CachyOS" in text
    assert tab._compat_change_btn.isHidden() is False
    assert tab._compat_change_btn.isEnabled() is True


def test_steam_proton_with_override_shows_custom_suffix(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    proton = _proton_dir(tmp_path, "GE-Proton")
    install = _steam_install(tmp_path, _proton_dir(tmp_path, "ConfigInfo"))

    sm = _SM({"cc_steam_proton_override": proton})
    monkeypatch.setattr(
        "services.cc_launcher.resolve_effective_proton",
        lambda inst, s: proton,
    )
    monkeypatch.setattr(
        "services.steam_proton_tools.enumerate_proton_tools",
        lambda: [ProtonTool(
            name="ge-proton", display_name="GE-Proton9-26",
            nickname="GE-Proton9-26", proton_dir=proton,
            source="compatibilitytools.d", steam_root="/fake",
            version_key=(9, 26),
        )],
    )
    tab = _build_tab(sm)
    monkeypatch.setattr(tab, "_get_active_cc_install", lambda: install)
    tab._refresh_compat_runtime_row()

    text = tab._compat_field.helper_widget.text()
    assert " · custom" in text
    assert "GE-Proton9-26" in text


def test_steam_proton_resolver_none_disables_change_button(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    install = _steam_install(tmp_path, proton_dir=None)

    sm = _SM()
    monkeypatch.setattr(
        "services.cc_launcher.resolve_effective_proton",
        lambda inst, s: None,
    )
    tab = _build_tab(sm)
    monkeypatch.setattr(tab, "_get_active_cc_install", lambda: install)
    tab._refresh_compat_runtime_row()

    assert "No Steam Proton found" in tab._compat_field.helper_widget.text()
    assert not tab._compat_change_btn.isEnabled()


def test_bottles_install_shows_readonly_label_no_button(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    pfx = tmp_path / "bottle"
    pfx.mkdir(parents=True)
    exe = pfx / "fake.exe"
    exe.write_text("")
    install = WineInstall(
        exe_path=str(exe), launcher="bottles", prefix_path=str(pfx),
        display_name="Bottles · X",
        metadata={"bottle_display_name": "Soda 9.0", "bottle_name": "x"},
    )

    sm = _SM()
    tab = _build_tab(sm)
    monkeypatch.setattr(tab, "_get_active_cc_install", lambda: install)
    tab._refresh_compat_runtime_row()

    text = tab._compat_field.helper_widget.text()
    assert "Bottles" in text
    assert "Soda 9.0" in text
    assert tab._compat_change_btn.isHidden() is True


def test_no_cc_install_hides_field(qapp, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    sm = _SM()
    tab = _build_tab(sm)
    monkeypatch.setattr(tab, "_get_active_cc_install", lambda: None)
    tab._refresh_compat_runtime_row()
    assert tab._compat_field.isHidden() is True


def test_change_click_persists_chosen_override(qapp, tmp_path, monkeypatch):
    """Clicking Change opens the picker; on Accept with a specific Proton,
    the override is written to settings and refresh rebuilds the label."""
    monkeypatch.setattr(sys, "platform", "linux")
    proton = _proton_dir(tmp_path, "ChosenProton")
    install = _steam_install(tmp_path, _proton_dir(tmp_path, "ConfigInfo"))

    sm = _SM()

    class _StubDialog:
        DialogCode = type("DC", (), {"Accepted": 1, "Rejected": 0})()

        def __init__(self, tools, current_override, steam_default_display,
                     parent=None):
            self._chosen = proton

        def exec(self):
            return self.DialogCode.Accepted

        def chosen_override(self):
            return self._chosen

    monkeypatch.setattr(
        "utils.widgets.cc_compat_picker.CCCompatPickerDialog", _StubDialog,
    )
    monkeypatch.setattr(
        "services.cc_launcher.resolve_effective_proton",
        lambda inst, s: proton,
    )
    monkeypatch.setattr(
        "services.steam_proton_tools.enumerate_proton_tools",
        lambda: [ProtonTool(
            name="chosen", display_name="ChosenProton",
            nickname="ChosenProton", proton_dir=proton,
            source="compatibilitytools.d", steam_root="/fake",
            version_key=(9, 0),
        )],
    )

    tab = _build_tab(sm)
    monkeypatch.setattr(tab, "_get_active_cc_install", lambda: install)
    tab._on_compat_change_clicked()

    assert sm.values.get("cc_steam_proton_override") == proton


def test_change_click_cancel_does_not_persist(qapp, tmp_path, monkeypatch):
    """Cancelling the picker leaves cc_steam_proton_override untouched."""
    monkeypatch.setattr(sys, "platform", "linux")
    proton = _proton_dir(tmp_path, "ConfigInfo")
    install = _steam_install(tmp_path, proton)

    sm = _SM({"cc_steam_proton_override": "preexisting"})

    class _StubDialog:
        DialogCode = type("DC", (), {"Accepted": 1, "Rejected": 0})()
        def __init__(self, tools, current_override, steam_default_display, parent=None):
            pass
        def exec(self):
            return self.DialogCode.Rejected
        def chosen_override(self):
            return None

    monkeypatch.setattr(
        "utils.widgets.cc_compat_picker.CCCompatPickerDialog", _StubDialog,
    )
    monkeypatch.setattr(
        "services.cc_launcher.resolve_effective_proton",
        lambda inst, s: proton,
    )
    monkeypatch.setattr(
        "services.steam_proton_tools.enumerate_proton_tools",
        lambda: [],
    )

    tab = _build_tab(sm)
    monkeypatch.setattr(tab, "_get_active_cc_install", lambda: install)
    tab._on_compat_change_clicked()

    assert sm.values["cc_steam_proton_override"] == "preexisting"
