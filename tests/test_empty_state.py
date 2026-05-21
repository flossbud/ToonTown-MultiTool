"""Section empty state - illustration + CTA."""
import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.empty_state import EmptyState


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_ttr_empty_state_text(qapp):
    w = EmptyState(game="ttr")
    assert "TTR" in w.cta_btn.text()
    assert "No TTR accounts" in w.title_label.text()


def test_cc_empty_state_text(qapp):
    w = EmptyState(game="cc")
    assert "CC" in w.cta_btn.text()
    assert "No CC accounts" in w.title_label.text()


def test_cta_emits_signal(qapp):
    w = EmptyState(game="ttr")
    captured = []
    w.add_clicked.connect(lambda: captured.append("clicked"))
    w.cta_btn.click()
    assert captured == ["clicked"]
