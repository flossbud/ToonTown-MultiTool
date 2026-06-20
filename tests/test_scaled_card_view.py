import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid
from utils.overlay.scaled_card_view import ScaledCardView


def test_hosts_card_and_scales(qapp):
    card = QWidget(); card.resize(376, 232)
    v = ScaledCardView()
    v.set_card(card)
    assert v.card() is card
    v.set_scale(1.5)
    t = v.view_transform()
    assert round(t.m11(), 3) == 1.5 and round(t.m22(), 3) == 1.5  # uniform scale


def test_release_returns_card_undeleted(qapp):
    card = QWidget()
    v = ScaledCardView()
    v.set_card(card)
    returned = v.release_card()
    assert returned is card
    assert card.parent() is None
    assert isValid(card)            # released, NOT deleted (borrowed-widget contract)
    assert v.card() is None


def test_hosts_a_parented_card(qapp):
    """The borrowed card arrives parented to its grid cell; set_card must detach it
    so QGraphicsScene.addWidget (top-level-only) actually embeds it."""
    grid = QWidget()
    card = QWidget(grid)            # parented, like a real grid cell
    assert card.parent() is grid
    v = ScaledCardView()
    v.set_card(card)
    assert v._proxy.widget() is card   # embed succeeded (not None)
    assert card.parent() is not grid   # detached from the grid


def test_rehost_returns_displaced_card(qapp):
    """Re-hosting must RETURN the displaced card (parentless, undeleted) so the
    caller can never silently lose it."""
    a, b = QWidget(), QWidget()
    v = ScaledCardView()
    assert v.set_card(a) is None         # nothing displaced on first host
    displaced = v.set_card(b)
    assert displaced is a
    assert isValid(a) and a.parent() is None
    assert v.card() is b


def test_scale_before_card_is_safe(qapp):
    """Scaling before any card is hosted must not crash."""
    v = ScaledCardView()
    v.set_scale(1.75)                    # no card yet
    assert round(v.view_transform().m11(), 3) == 1.75
    card = QWidget()
    v.set_card(card)                     # hosting after a scale still works
    assert v.card() is card


def test_close_releases_borrowed_card(qapp):
    """closeEvent un-owns the borrowed card so close() never deletes it (the scene
    would otherwise delete the proxied widget on destruction)."""
    card = QWidget()
    v = ScaledCardView()
    v.set_card(card)
    v.close()
    qapp.processEvents()
    assert isValid(card)                 # survived close()
    assert v.card() is None
