import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp):
    from tabs.debug_tab import DebugTab
    return DebugTab()


def test_disabled_drops_ordinary_lines(tab):
    tab.logging_enabled = False
    tab.append_log("[Service] should be dropped")
    assert tab.card.model.rowCount() == 0


def test_credentials_passthrough_while_disabled(tab):
    tab.logging_enabled = False
    tab.append_log("[Credentials] captured early")
    tab.append_log("[CredentialsManager] also captured")
    assert tab.card.model.rowCount() == 2


def test_enabled_appends_with_classifier(tab):
    from utils.widgets.logs_console.model import LINE_ROLE
    tab.logging_enabled = True
    tab.append_log("[TTR API] Login failed")
    line = tab.card.model.index(tab.card.model.rowCount() - 1, 0).data(LINE_ROLE)
    assert line.level == "error" and line.source == "api"


def test_explicit_level_kwarg_wins(tab):
    from utils.widgets.logs_console.model import LINE_ROLE
    tab.logging_enabled = True
    tab.append_log("[TTR API] Login failed", level="info")
    line = tab.card.model.index(tab.card.model.rowCount() - 1, 0).data(LINE_ROLE)
    assert line.level == "info"


def test_apply_theme_exists_and_cascades(tab):
    tab.apply_theme(False)
    tab.apply_theme(True)


def test_str_signal_delivers_to_append_log(tab, qapp):
    from PySide6.QtCore import QObject, Signal
    from utils.widgets.logs_console.model import LINE_ROLE

    class _Emitter(QObject):
        sig = Signal(str)

    tab.logging_enabled = True
    e = _Emitter()
    e.sig.connect(tab.append_log)
    e.sig.emit("[TTR API] Login OK")
    line = tab.card.model.index(tab.card.model.rowCount() - 1, 0).data(LINE_ROLE)
    assert line.level == "ok" and line.source == "api"
