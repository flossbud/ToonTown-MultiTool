import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication


class _StubSettings:
    def __init__(self, **kv):
        self._kv = kv
        self.sets = []
    def get(self, key, default=None):
        return self._kv.get(key, default)
    def set(self, key, value):
        self._kv[key] = value
        self.sets.append((key, value))
    def on_change(self, cb):
        pass


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_title_bar_switch_present_and_wired(qapp, monkeypatch):
    from tabs.settings_tab import SettingsTab
    from utils.shared_widgets import Switch
    # Suppress the keep-alive warning dialog so setChecked(True) on the
    # keep-alive master switch doesn't block with a modal QMessageBox.exec().
    monkeypatch.setattr(
        SettingsTab, "_show_keep_alive_warning_dialog", lambda self: True
    )
    sm = _StubSettings(theme="dark", use_system_title_bar=False)
    tab = SettingsTab(sm)
    switches = tab.findChildren(Switch)
    assert switches, "no Switch widgets found in settings"
    matches = []
    for sw in switches:
        sm.sets.clear()
        # Toggle to the opposite of current state so every switch emits once.
        sw.setChecked(not sw.isChecked())
        if any(k == "use_system_title_bar" for k, _ in sm.sets):
            matches.append(sw)
    assert len(matches) == 1, (
        f"expected exactly one switch to write use_system_title_bar, "
        f"got {len(matches)}"
    )
