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


def test_empty_state_cta_is_accent_filled(qapp):
    """v2 reskin: CTA button is a solid game-accent pill with white text
    (replaces the old neutral ghost chip)."""
    from utils.theme_manager import V2_ACCENTS
    from utils.widgets.empty_state import EmptyState
    es = EmptyState(game="cc")
    cta_qss = es.cta_btn.styleSheet()
    assert V2_ACCENTS["cc"]["c"] in cta_qss
    assert "color: #ffffff" in cta_qss


def test_empty_state_apply_theme_rebuilds(qapp):
    from utils.theme_manager import get_theme_colors, get_v2_tokens
    from utils.widgets.empty_state import EmptyState
    light = get_theme_colors(False)
    es = EmptyState(game="ttr")
    es.apply_theme(light)
    assert light["text_primary"] in es.title_label.styleSheet()
    assert get_v2_tokens(False)["sub"] in es.subtitle_label.styleSheet()
    dark = get_theme_colors(True)
    if dark["text_primary"] != light["text_primary"]:
        assert dark["text_primary"] not in es.title_label.styleSheet()


def test_empty_state_emits_add(qapp):
    from utils.widgets.empty_state import EmptyState
    e = EmptyState("cc")
    fired = []
    e.add_clicked.connect(lambda: fired.append(1))
    e.cta_btn.click()
    assert fired == [1]
