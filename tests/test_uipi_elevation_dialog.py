import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from utils.widgets.uipi_elevation_dialog import UipiElevationDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_dialog_emits_restart_signal():
    _app()
    dlg = UipiElevationDialog(affected_toons=["Toon 2"])
    fired = []
    dlg.restart_as_admin.connect(lambda: fired.append(True))
    dlg._restart_btn.click()
    assert fired == [True]


def test_dialog_emits_dont_ask_again():
    _app()
    dlg = UipiElevationDialog(affected_toons=["Toon 2"])
    fired = []
    dlg.dont_ask_again.connect(lambda: fired.append(True))
    dlg._dont_ask_btn.click()
    assert fired == [True]


def test_why_button_reveals_remediation():
    _app()
    dlg = UipiElevationDialog(affected_toons=["Toon 2"])
    assert dlg._why_btn is not None
    assert not dlg._remediation.isVisible() or dlg._remediation.isHidden()
    dlg._why_btn.click()
    assert dlg._remediation.isVisibleTo(dlg)   # revealed after clicking Why


def test_dialog_lists_affected_toons():
    _app()
    dlg = UipiElevationDialog(affected_toons=["Toon 2", "Toon 3"])
    # The affected toons appear somewhere in the dialog's text.
    texts = []
    for lbl in dlg.findChildren(type(dlg._title)):
        texts.append(lbl.text())
    assert any("Toon 2" in t and "Toon 3" in t for t in texts)
