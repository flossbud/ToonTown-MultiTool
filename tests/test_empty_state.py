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


def test_empty_state_uses_text_primary_token(qapp):
    from utils.theme_manager import get_theme_colors
    from utils.widgets.empty_state import EmptyState
    c = get_theme_colors(True)
    es = EmptyState(game="ttr")
    title_qss = es.title_label.styleSheet()
    assert c["text_primary"] in title_qss


def test_empty_state_cta_is_neutral(qapp):
    """CTA button is a neutral chip (transparent bg + hairline border +
    text_secondary color), not a saturated game-accent fill."""
    from utils.theme_manager import get_theme_colors
    from utils.widgets.empty_state import EmptyState
    c = get_theme_colors(True)
    es = EmptyState(game="cc")
    cta_qss = es.cta_btn.styleSheet()
    assert "background: transparent" in cta_qss
    assert c["text_secondary"] in cta_qss
    assert c["border_muted"] in cta_qss
    # Regression guard: no saturated game-accent fill on the CTA bg.
    assert "background: #0077ff" not in cta_qss.lower()
    assert "background: #f26d21" not in cta_qss.lower()


def test_empty_state_apply_theme_rebuilds(qapp):
    from utils.theme_manager import get_theme_colors
    from utils.widgets.empty_state import EmptyState
    light = get_theme_colors(False)
    es = EmptyState(game="ttr")
    es.apply_theme(light)
    assert light["text_primary"] in es.title_label.styleSheet()
    assert light["text_muted"] in es.subtitle_label.styleSheet()
    dark = get_theme_colors(True)
    if dark["text_primary"] != light["text_primary"]:
        assert dark["text_primary"] not in es.title_label.styleSheet()
