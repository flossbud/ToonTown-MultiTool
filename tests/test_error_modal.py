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


def test_title_includes_account_name(qapp):
    dlg = ErrorModal(account_name="SaltyMcKraken", game="cc", raw_message="x")
    assert "SaltyMcKraken" in dlg.title_label.text()
