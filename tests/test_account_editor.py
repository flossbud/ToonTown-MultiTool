"""AccountEditor modal: Add and Edit modes share one component."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
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


def test_add_mode_empty_username_blocks_save(qapp):
    dlg = AccountEditor(game="ttr", mode="add")
    dlg.show()  # so isVisible() reflects child-widget state
    dlg.password_input.setText("pw")  # password set, username blank
    captured = []
    dlg.account_saved.connect(lambda *a: captured.append(a))
    dlg.save_btn.click()
    assert captured == []  # no emit
    assert dlg.username_error.isVisible()
    assert not dlg.password_error.isVisible()


def test_add_mode_empty_password_blocks_save(qapp):
    dlg = AccountEditor(game="ttr", mode="add")
    dlg.show()
    dlg.username_input.setText("user")
    captured = []
    dlg.account_saved.connect(lambda *a: captured.append(a))
    dlg.save_btn.click()
    assert captured == []
    assert dlg.password_error.isVisible()
    assert not dlg.username_error.isVisible()


def test_add_mode_both_empty_shows_both_errors(qapp):
    dlg = AccountEditor(game="ttr", mode="add")
    dlg.show()
    captured = []
    dlg.account_saved.connect(lambda *a: captured.append(a))
    dlg.save_btn.click()
    assert captured == []
    assert dlg.username_error.isVisible()
    assert dlg.password_error.isVisible()


def test_edit_mode_allows_empty_save(qapp):
    # Edit mode: user can deliberately clear fields. No validation.
    dlg = AccountEditor(game="ttr", mode="edit", initial_label="X")
    captured = []
    dlg.account_saved.connect(lambda *a: captured.append(a))
    dlg.save_btn.click()
    assert len(captured) == 1  # emit happened


def test_typing_clears_error(qapp):
    dlg = AccountEditor(game="ttr", mode="add")
    dlg.show()
    dlg.save_btn.click()  # triggers error
    assert dlg.username_error.isVisible()
    dlg.username_input.setText("x")
    assert not dlg.username_error.isVisible()


def test_cancel_button_does_not_steal_enter_key(qapp):
    # Qt's default autoDefault=True on Cancel can hijack Enter even when
    # Save is setDefault(True). Verify Cancel is opted out so Enter routes
    # to Save.
    dlg = AccountEditor(game="ttr", mode="add")
    assert dlg.cancel_btn.autoDefault() is False
    assert dlg.save_btn.isDefault() is True


@pytest.mark.parametrize("field", ["label_input", "username_input", "password_input"])
def test_enter_key_in_input_triggers_save(qapp, field):
    dlg = AccountEditor(game="ttr", mode="add")
    dlg.show()
    QTest.qWaitForWindowExposed(dlg)
    dlg.label_input.setText("My Toon")
    dlg.username_input.setText("user@example")
    dlg.password_input.setText("pw")
    captured = []
    dlg.account_saved.connect(lambda *a: captured.append(a))
    target = getattr(dlg, field)
    target.setFocus()
    QTest.keyClick(target, Qt.Key_Return)
    assert captured == [("My Toon", "user@example", "pw")]


class TestFollowsTheme:
    """The app stylesheet gives every widget the theme background, so the
    modal's surface is light in light mode. Its text used to be hardcoded
    white, which made labels and typed text nearly invisible there."""

    @staticmethod
    def _luma(css: str, prop: str) -> float:
        import re
        from PySide6.QtGui import QColor
        m = re.search(rf"(?<![-\w]){prop}:\s*([^;}}]+)", css)
        assert m, f"no {prop} in {css!r}"
        return QColor(m.group(1).strip()).lightnessF()

    @pytest.mark.parametrize("is_dark", [False, True])
    def test_text_contrasts_with_the_surface(self, qapp, monkeypatch, is_dark):
        import utils.widgets.account_editor as mod
        monkeypatch.setattr(mod, "is_dark_palette", lambda: is_dark)
        ed = mod.AccountEditor(game="ttr", mode="add")
        surface = self._luma(ed.styleSheet(), "background")
        assert (surface < 0.5) is is_dark
        for widget in (ed.title_label, ed.subline, ed.username_input,
                       ed.password_input, ed.label_input, ed.cancel_btn,
                       ed.username_error):
            text = self._luma(widget.styleSheet(), "color")
            assert abs(text - surface) > 0.3, (
                f"{widget.objectName() or type(widget).__name__}: "
                f"text {text:.2f} on surface {surface:.2f}")

    def test_light_mode_input_text_is_not_white(self, qapp, monkeypatch):
        import utils.widgets.account_editor as mod
        monkeypatch.setattr(mod, "is_dark_palette", lambda: False)
        ed = mod.AccountEditor(game="cc", mode="add")
        assert self._luma(ed.username_input.styleSheet(), "color") < 0.3
        assert self._luma(ed.username_input.styleSheet(), "background") > 0.9
