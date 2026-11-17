"""Turning keep-alive off never asks anything, wherever it is turned off.

Consent is asked once, when keep-alive is turned on in Settings. Off is
unconditional: the Settings master switch, the launchpad's Settings sheet,
the session (per toon, even after keep-alive stopped being available) and a
strip's keep-alive block all turn it off without a dialog. Every QDialog's
exec() is a tripwire here, so a prompt from anywhere fails the test.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from utils.settings_keys import KEEP_ALIVE_CONSENT_ACKNOWLEDGED, KEEP_ALIVE_ENABLED

# Shared helpers and fixtures of the suites these surfaces already have.
from tests.test_launchpad_settings_sheet import _Settings, _sheet, quiet  # noqa: F401
from tests.test_settings_rows import _page
from tests.test_strips_controller import click, model, rig, settle  # noqa: F401
from tests.toon_session_harness import KEEP_ALIVE_ON, Rig


@pytest.fixture
def asked(monkeypatch):
    """Every dialog shown modally, by class name. Answers Cancel."""
    shown = []

    def trip(self, *args, **kwargs):
        shown.append(type(self).__name__)
        return 0

    monkeypatch.setattr(QDialog, "exec", trip)
    return shown


def _rows(settings, monkeypatch):
    from utils.widgets.settings_rows import SettingsRows
    rows = SettingsRows(settings)
    page = _page()
    rows._build_keep_alive_card(page)
    rows._page_keepalive = page                       # keep the rows alive
    warned = []
    real = rows._show_keep_alive_warning_dialog
    monkeypatch.setattr(rows, "_show_keep_alive_warning_dialog",
                        lambda: warned.append(1) or real())
    return rows, warned


@pytest.mark.parametrize("consent", [True, False, None])
def test_the_settings_master_switch_turns_off_without_asking(
        qapp, quiet, monkeypatch, asked, consent):
    data = {KEEP_ALIVE_ENABLED: True}
    if consent is not None:
        data[KEEP_ALIVE_CONSENT_ACKNOWLEDGED] = consent
    sm = _Settings(data)
    rows, warned = _rows(sm, monkeypatch)
    rows._on_keep_alive_master_toggle(False)
    assert sm.data[KEEP_ALIVE_ENABLED] is False
    assert warned == [] and asked == []
    # Turning it off neither records nor withdraws consent.
    assert sm.data.get(KEEP_ALIVE_CONSENT_ACKNOWLEDGED) == consent


def test_turning_it_on_still_asks(qapp, quiet, monkeypatch, asked):
    """The tripwire sees the consent dialog: the off tests above are not
    passing because nothing could ever be seen."""
    sm = _Settings()
    rows, warned = _rows(sm, monkeypatch)
    rows._on_keep_alive_master_toggle(True)
    assert warned == [1] and asked == ["QMessageBox"]
    assert sm.data.get(KEEP_ALIVE_ENABLED) is not True


def test_the_settings_sheet_switch_turns_off_without_asking(
        qapp, quiet, monkeypatch, asked):
    sm = _Settings({KEEP_ALIVE_ENABLED: True, KEEP_ALIVE_CONSENT_ACKNOWLEDGED: True})
    s = _sheet(sm)
    switch = s.keep_alive_row().control_widget
    assert switch.isChecked()
    QTest.mouseClick(switch, Qt.LeftButton)
    assert sm.data[KEEP_ALIVE_ENABLED] is False
    assert asked == []


@pytest.fixture
def session_rig(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    made = []

    def _make(**kwargs):
        made.append(Rig(tmp_path, **kwargs))
        return made[-1]

    yield _make
    for r in made:
        r.close()


@pytest.mark.parametrize("withdrawn", [KEEP_ALIVE_ENABLED, KEEP_ALIVE_CONSENT_ACKNOWLEDGED])
def test_the_session_turns_a_toon_off_after_keep_alive_went_away(
        session_rig, asked, withdrawn):
    """A toon's keep-alive outlives the master switch (it is the user's
    setup), so it can be on while keep-alive is unavailable; turning it off
    then must still work, and asks nothing."""
    rig = session_rig(settings=dict(KEEP_ALIVE_ON))
    rig.wm.set_windows(["a", "b"])
    rig.session.set_keep_alive("a", True)
    rig.settings.set(withdrawn, False)
    assert not rig.session.keep_alive_available()
    assert rig.session.toon("a").keep_alive is True       # kept underneath
    rig.session.set_keep_alive("a", False)
    assert rig.session.toon("a").keep_alive is False
    assert asked == []


def test_the_session_turns_every_toon_off_without_asking(session_rig, asked):
    rig = session_rig(settings=dict(KEEP_ALIVE_ON))
    rig.wm.set_windows(["a", "b"])
    rig.session.set_keep_alive("a", True)
    rig.session.toggle_keep_alive_all()                    # any on -> those off
    assert [t.keep_alive for t in rig.session.toons()] == [False, False]
    assert asked == []


def test_a_strip_click_turns_keep_alive_off_without_asking(rig, asked):
    from utils.strips import layout as L
    session, controller, _rects = rig()
    assert session.toon("102").keep_alive is True
    click(controller, "102", L.KEEP_ALIVE)
    settle()
    assert session.toon("102").keep_alive is False
    assert model(controller, "102").keep_alive is False
    assert asked == []
