"""Regression pin: building KeymapTab must never show a parentless top-level.

setVisible(True) on a widget with no parent shows it as a decorated top-level
X window; during MultiToonTool construction that mapped short-lived windows on
screen (the startup "black square" flash - the add-set buttons were made
visible one line before being parented into the page layout). The spy below
catches ANY such call during construction, not just the known offender.
"""
from __future__ import annotations

import os

os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen", reason="offscreen only"
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    return tmp_path


class _FakeSettings:
    def __init__(self):
        self._d = {"ttr_engine_dir": "", "cc_engine_dir": "", "theme": "dark"}
    def get(self, k, default=None):
        return self._d.get(k, default)
    def set(self, k, v):
        self._d[k] = v
    def on_change(self, cb):
        pass


def test_keymap_tab_build_shows_no_parentless_toplevel(
        qapp, monkeypatch, isolated_config):
    from tabs.keymap_tab import KeymapTab
    from utils.keymap_manager import KeymapManager

    monkeypatch.setattr(KeymapTab, "_ttr_detected", lambda self: True)
    monkeypatch.setattr(KeymapTab, "_cc_detected", lambda self: True)

    offenders = []
    orig_set_visible = QWidget.setVisible

    def spy(self, visible):
        if visible and self.parent() is None and self.isWindow():
            offenders.append(
                f"{type(self).__module__}.{type(self).__name__}"
                f" title={self.windowTitle()!r}")
        return orig_set_visible(self, visible)

    monkeypatch.setattr(QWidget, "setVisible", spy)
    KeymapTab(KeymapManager(), settings_manager=_FakeSettings(),
              credentials_manager=None)
    assert offenders == []
