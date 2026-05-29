"""ErrorModal: shows full raw error + Copy button."""
import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.error_modal import ErrorModal


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_shows_raw_message(qapp):
    raw = "TTR API HTTP 401\nBody: {'banner': 'Bad creds'}"
    dlg = ErrorModal(account_name="FlashHotrod", game="ttr", raw_message=raw)
    assert raw in dlg.body_text.toPlainText()


def test_copy_puts_raw_in_clipboard(qapp):
    raw = "ZZZ-unique-token-XYZ"
    dlg = ErrorModal(account_name="X", game="ttr", raw_message=raw)
    dlg.copy_btn.click()
    cb = QApplication.clipboard()
    assert cb.text() == raw


def test_copy_button_uses_shared_clipboard_helper(qapp, monkeypatch):
    raw = "host-fallback-token"
    copied = []
    monkeypatch.setattr(
        "utils.widgets.error_modal.copy_text",
        lambda text: copied.append(text) or True,
    )
    dlg = ErrorModal(account_name="X", game="ttr", raw_message=raw)

    dlg.copy_btn.click()

    assert copied == [raw]
    assert dlg.copy_btn.text() == "Copied"


def test_copy_button_shows_failure_when_helper_fails(qapp, monkeypatch):
    monkeypatch.setattr(
        "utils.widgets.error_modal.copy_text", lambda text: False,
    )
    dlg = ErrorModal(account_name="X", game="ttr", raw_message="boom")

    dlg.copy_btn.click()

    assert dlg.copy_btn.text() == "Copy failed"


def test_title_includes_account_name(qapp):
    dlg = ErrorModal(account_name="SaltyMcKraken", game="cc", raw_message="x")
    assert "SaltyMcKraken" in dlg.title_label.text()
