import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_constructs_for_default_set(qapp):
    from tabs.keymap_tab import SetCard
    card = SetCard(index=0, set_data={"name": "Default"})
    assert card.index == 0


def test_constructs_for_alternate_set(qapp):
    from tabs.keymap_tab import SetCard
    card = SetCard(index=1, set_data={"name": "Alt"})
    assert card.index == 1


def test_paints_without_crashing(qapp):
    from PySide6.QtGui import QPixmap
    from tabs.keymap_tab import SetCard
    card = SetCard(index=0, set_data={"name": "Default"})
    card.resize(400, 80)
    # Force a paint into an offscreen pixmap; will raise if paintEvent throws.
    pm = QPixmap(card.size())
    pm.fill()
    card.render(pm)
