import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


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


def test_default_set_has_no_delete_button(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QPushButton
    card = SetCard(index=0, set_data={"name": "Default"})
    delete_btns = [b for b in card.findChildren(QPushButton)
                   if b.toolTip() == "Delete this movement set"]
    assert delete_btns == []


def test_alternate_set_has_delete_button(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QPushButton
    card = SetCard(index=1, set_data={"name": "Alt"})
    delete_btns = [b for b in card.findChildren(QPushButton)
                   if b.toolTip() == "Delete this movement set"]
    assert len(delete_btns) == 1


def test_default_set_name_is_qlabel(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QLabel
    card = SetCard(index=0, set_data={"name": "Default"})
    labels = [w for w in card.findChildren(QLabel)
              if w.objectName() == "set_name_label"]
    assert len(labels) == 1
    assert labels[0].text() == "Default"


def test_alternate_set_name_is_qlineedit(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QLineEdit
    card = SetCard(index=1, set_data={"name": "WASD alt"})
    edits = [w for w in card.findChildren(QLineEdit)
             if w.objectName() == "set_name_edit"]
    assert len(edits) == 1
    assert edits[0].text() == "WASD alt"


def test_toggle_signal_fires_on_header_click(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QMouseEvent
    card = SetCard(index=0, set_data={"name": "Default"})
    received = []
    card.toggle_requested.connect(lambda: received.append(True))
    pt = QPoint(40, 30)
    ev = QMouseEvent(QEvent.MouseButtonPress, pt,
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    card.mousePressEvent(ev)
    assert received == [True]
