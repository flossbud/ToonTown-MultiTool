"""AccountEditor modal: Add and Edit modes share one component."""
import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.account_editor import AccountEditor


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_add_mode_title(qapp):
    dlg = AccountEditor(game="ttr", mode="add")
    assert "Add" in dlg.windowTitle() or "Add" in dlg.title_label.text()
    assert dlg.label_input.text() == ""


def test_edit_mode_prefills_fields(qapp):
    dlg = AccountEditor(
        game="cc", mode="edit",
        initial_label="SaltyMcKraken",
        initial_username="salty@example",
        initial_password="hunter2",
    )
    assert dlg.label_input.text() == "SaltyMcKraken"
    assert dlg.username_input.text() == "salty@example"
    assert dlg.password_input.text() == "hunter2"


def test_accent_bar_color_matches_game(qapp):
    ttr_dlg = AccountEditor(game="ttr", mode="add")
    cc_dlg = AccountEditor(game="cc", mode="add")
    # Each game's stylesheet contains its accent color string.
    assert "#4A8FE7" in ttr_dlg.styleSheet() or "#4A8FE7" in ttr_dlg.accent_bar.styleSheet()
    assert "#F26D21" in cc_dlg.styleSheet() or "#F26D21" in cc_dlg.accent_bar.styleSheet()


def test_save_emits_values(qapp):
    dlg = AccountEditor(game="ttr", mode="add")
    dlg.label_input.setText("New")
    dlg.username_input.setText("new@example")
    dlg.password_input.setText("pw")
    captured = {}
    dlg.account_saved.connect(lambda lab, user, pw: captured.update({"lab": lab, "u": user, "p": pw}))
    dlg.save_btn.click()
    assert captured == {"lab": "New", "u": "new@example", "p": "pw"}
