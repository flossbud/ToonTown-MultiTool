"""ConfirmDialog: destructive confirm with optional don't-ask-again."""
import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.confirm_dialog import ConfirmDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_quit_variant_has_dont_ask_again(qapp):
    dlg = ConfirmDialog(
        title="Quit FlashHotrod's game?",
        body="Unsaved progress will be lost.",
        confirm_label="Quit",
        show_dont_ask_again=True,
    )
    assert dlg.dont_ask_again_check.isVisible() or dlg.dont_ask_again_check is not None


def test_delete_variant_no_dont_ask_again(qapp):
    dlg = ConfirmDialog(
        title="Delete FlashHotrod?",
        body="Credentials will be removed.",
        confirm_label="Delete",
        show_dont_ask_again=False,
    )
    assert dlg.dont_ask_again_check is None


def test_confirm_button_label_and_color(qapp):
    dlg = ConfirmDialog(
        title="Quit?", body="x", confirm_label="Quit", show_dont_ask_again=True,
    )
    assert dlg.confirm_btn.text() == "Quit"
    assert "#b34848" in dlg.confirm_btn.styleSheet()


def test_dont_ask_again_value_accessible(qapp):
    dlg = ConfirmDialog(
        title="Quit?", body="x", confirm_label="Quit", show_dont_ask_again=True,
    )
    dlg.dont_ask_again_check.setChecked(True)
    assert dlg.dont_ask_again_checked() is True
