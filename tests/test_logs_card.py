import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def card(qapp):
    from utils.widgets.logs_console.logs_card import LogsCard
    c = LogsCard()
    c.resize(868, 640)
    c.show()
    QApplication.processEvents()
    return c


def test_card_uses_purple_card_surface(card):
    assert card.surface.accent_key == "purple"
    assert card.surface.title_label.text() == "Logs"


def test_append_reaches_the_model_and_status(card):
    card.append("[Credentials] Keyring ready")
    card.append("[TTR API] Login OK")
    QApplication.processEvents()
    assert card.model.rowCount() == 2
    assert "2 lines" in card.status.text()
    assert "following" in card.status.text()


def test_status_reflects_paused(card):
    for i in range(60):
        card.append(f"line {i}")
    QApplication.processEvents()
    card.pane.set_following(False)
    assert "paused" in card.status.text()


def test_apply_theme_cascades_both_ways(card):
    card.apply_theme(False)
    card.apply_theme(True)   # no crash; component token flips are pinned in their own suites


def test_dot_animates_only_while_visible(card):
    # The card fixture is shown; the dot's showEvent started the pulse.
    assert card.dot._anim is not None
    card.hide()
    QApplication.processEvents()
    assert card.dot._anim is None
    card.show()
    QApplication.processEvents()
    assert card.dot._anim is not None
