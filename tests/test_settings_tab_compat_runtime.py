"""Tests for the compatibility-runtime row in the Settings tab.

Row appears below the CC path row, hidden on Windows and when no CC
install is configured.
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


def test_compat_row_hidden_on_windows(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    from tabs.settings_tab import CompatRuntimeRow
    row = CompatRuntimeRow(
        settings_manager=None,
        get_active_install=lambda: _steam_install(tmp_path, _proton_dir(tmp_path, "p")),
    )
    assert row.is_platform_hidden is True
    assert row.isHidden() is True


def test_steam_proton_no_override_shows_steam_default_suffix(
    qapp, tmp_path, monkeypatch,
):
    """Linux + steam-proton + no override → label has '(Steam default)'."""
    monkeypatch.setattr(sys, "platform", "linux")
    proton = _proton_dir(tmp_path, "ProtonCachy")
    install = _steam_install(tmp_path, proton)

    class _SM:
        def __init__(self): self.values = {}
        def get(self, k, d=None): return self.values.get(k, d)
        def set(self, k, v): self.values[k] = v
        def on_change(self, cb): pass

    sm = _SM()
    # Force resolver to return our test proton dir.
    monkeypatch.setattr("services.cc_launcher.resolve_effective_proton",
                        lambda inst, s: proton)
    monkeypatch.setattr(
        "services.steam_proton_tools.enumerate_proton_tools",
        lambda: [ProtonTool(name="proton-cachyos", display_name="Proton-CachyOS",
                            nickname="Proton-CachyOS",
                            proton_dir=proton, source="compatibilitytools.d",
                            steam_root="/fake", version_key=(9, 0))],
    )
    from tabs.settings_tab import CompatRuntimeRow
    row = CompatRuntimeRow(settings_manager=sm, get_active_install=lambda: install)

    assert row.is_platform_hidden is False
    assert row.change_button.isHidden() is False
    text = row.sub_widget.text()
    assert " · default" in text, f"expected ' · default' in {text!r}"
    # The test fixture uses a ProtonTool with display_name="Proton-CachyOS";
    # the nickname for that input is also "Proton-CachyOS" (single brand
    # token, no version, Stage-1 VDF acceptance).
    assert "Proton-CachyOS" in text


def test_steam_proton_with_override_shows_custom_suffix(
    qapp, tmp_path, monkeypatch,
):
    monkeypatch.setattr(sys, "platform", "linux")
    proton = _proton_dir(tmp_path, "GE-Proton")
    install = _steam_install(tmp_path, _proton_dir(tmp_path, "ConfigInfo"))

    class _SM:
        def __init__(self): self.values = {"cc_steam_proton_override": proton}
        def get(self, k, d=None): return self.values.get(k, d)
        def set(self, k, v): self.values[k] = v
        def on_change(self, cb): pass

    sm = _SM()
    monkeypatch.setattr("services.cc_launcher.resolve_effective_proton",
                        lambda inst, s: proton)
    monkeypatch.setattr(
        "services.steam_proton_tools.enumerate_proton_tools",
        lambda: [ProtonTool(name="ge-proton", display_name="GE-Proton9-26",
                            nickname="GE-Proton9-26",
                            proton_dir=proton, source="compatibilitytools.d",
                            steam_root="/fake", version_key=(9, 26))],
    )
    from tabs.settings_tab import CompatRuntimeRow
    row = CompatRuntimeRow(settings_manager=sm, get_active_install=lambda: install)

    text = row.sub_widget.text()
    assert " · custom" in text, f"expected ' · custom' in {text!r}"
    assert "GE-Proton9-26" in text


def test_steam_proton_resolver_none_disables_change_button(
    qapp, tmp_path, monkeypatch,
):
    monkeypatch.setattr(sys, "platform", "linux")
    install = _steam_install(tmp_path, proton_dir=None)

    class _SM:
        def __init__(self): self.values = {}
        def get(self, k, d=None): return self.values.get(k, d)
        def set(self, k, v): self.values[k] = v
        def on_change(self, cb): pass

    sm = _SM()
    monkeypatch.setattr("services.cc_launcher.resolve_effective_proton",
                        lambda inst, s: None)
    from tabs.settings_tab import CompatRuntimeRow
    row = CompatRuntimeRow(settings_manager=sm, get_active_install=lambda: install)

    assert "No Steam Proton found" in row.sub_widget.text()
    assert not row.change_button.isEnabled()


def test_bottles_install_shows_readonly_label_no_button(
    qapp, tmp_path, monkeypatch,
):
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

    class _SM:
        def get(self, k, d=None): return d
        def set(self, k, v): pass
        def on_change(self, cb): pass

    from tabs.settings_tab import CompatRuntimeRow
    row = CompatRuntimeRow(settings_manager=_SM(), get_active_install=lambda: install)

    assert "Bottles" in row.sub_widget.text()
    assert "Soda 9.0" in row.sub_widget.text()
    assert row.change_button.isHidden() is True


def test_no_cc_install_hides_row(qapp, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    class _SM:
        def get(self, k, d=None): return d
        def set(self, k, v): pass
        def on_change(self, cb): pass

    from tabs.settings_tab import CompatRuntimeRow
    row = CompatRuntimeRow(settings_manager=_SM(), get_active_install=lambda: None)

    assert row.isHidden() is True


def test_change_button_click_persists_chosen_override(
    qapp, tmp_path, monkeypatch,
):
    """Clicking Change opens the picker; on Accept with a specific Proton,
    the override is written to settings and refresh() rebuilds the label."""
    monkeypatch.setattr(sys, "platform", "linux")
    proton = _proton_dir(tmp_path, "ChosenProton")
    install = _steam_install(tmp_path, _proton_dir(tmp_path, "ConfigInfo"))

    class _SM:
        def __init__(self): self.values = {}
        def get(self, k, d=None): return self.values.get(k, d)
        def set(self, k, v): self.values[k] = v
        def on_change(self, cb): pass

    sm = _SM()

    # Stub the picker: simulate "Accepted with proton=<chosen>".
    class _StubDialog:
        DialogCode = type("DC", (), {"Accepted": 1, "Rejected": 0})()

        def __init__(self, tools, current_override, steam_default_display,
                     parent=None):
            self._chosen = proton

        def exec(self):
            return self.DialogCode.Accepted

        def chosen_override(self):
            return self._chosen

    monkeypatch.setattr("utils.widgets.cc_compat_picker.CCCompatPickerDialog",
                        _StubDialog)
    monkeypatch.setattr("services.cc_launcher.resolve_effective_proton",
                        lambda inst, s: proton)
    monkeypatch.setattr(
        "services.steam_proton_tools.enumerate_proton_tools",
        lambda: [ProtonTool(name="chosen", display_name="ChosenProton",
                            nickname="ChosenProton",
                            proton_dir=proton, source="compatibilitytools.d",
                            steam_root="/fake", version_key=(9, 0))],
    )

    from tabs.settings_tab import CompatRuntimeRow
    row = CompatRuntimeRow(settings_manager=sm, get_active_install=lambda: install)
    row._on_change_clicked()

    assert sm.values.get("cc_steam_proton_override") == proton


def test_change_button_click_cancel_does_not_persist(
    qapp, tmp_path, monkeypatch,
):
    """Cancelling the picker leaves cc_steam_proton_override untouched."""
    monkeypatch.setattr(sys, "platform", "linux")
    proton = _proton_dir(tmp_path, "ConfigInfo")
    install = _steam_install(tmp_path, proton)

    class _SM:
        def __init__(self): self.values = {"cc_steam_proton_override": "preexisting"}
        def get(self, k, d=None): return self.values.get(k, d)
        def set(self, k, v): self.values[k] = v
        def on_change(self, cb): pass

    sm = _SM()

    class _StubDialog:
        DialogCode = type("DC", (), {"Accepted": 1, "Rejected": 0})()
        def __init__(self, tools, current_override, steam_default_display, parent=None):
            pass
        def exec(self):
            return self.DialogCode.Rejected
        def chosen_override(self):
            return None

    monkeypatch.setattr("utils.widgets.cc_compat_picker.CCCompatPickerDialog",
                        _StubDialog)
    monkeypatch.setattr("services.cc_launcher.resolve_effective_proton",
                        lambda inst, s: proton)
    monkeypatch.setattr(
        "services.steam_proton_tools.enumerate_proton_tools",
        lambda: [],
    )

    from tabs.settings_tab import CompatRuntimeRow
    row = CompatRuntimeRow(settings_manager=sm, get_active_install=lambda: install)
    row._on_change_clicked()

    assert sm.values["cc_steam_proton_override"] == "preexisting"  # unchanged
