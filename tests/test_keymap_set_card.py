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


def test_default_set_has_hint_label(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QLabel
    card = SetCard(index=0, set_data={"name": "Default", "forward": "Up"})
    hints = [w for w in card.findChildren(QLabel)
             if w.objectName() == "set_body_hint"]
    assert len(hints) == 1


def test_alternate_set_has_no_hint(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QLabel
    card = SetCard(index=1, set_data={"name": "Alt", "forward": "w"})
    hints = [w for w in card.findChildren(QLabel)
             if w.objectName() == "set_body_hint"]
    assert hints == []


def test_default_set_has_detect_button(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QPushButton
    card = SetCard(index=0, set_data={"name": "Default"}, active_game="ttr")
    detect = [b for b in card.findChildren(QPushButton)
              if b.objectName() == "detect_btn"]
    assert len(detect) == 1
    assert "TTR" in detect[0].text()


def test_default_set_cc_detect_button_label(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QPushButton
    card = SetCard(index=0, set_data={"name": "Default"}, active_game="cc")
    detect = [b for b in card.findChildren(QPushButton)
              if b.objectName() == "detect_btn"]
    assert "CC" in detect[0].text()


def test_key_field_for_action_exists(qapp):
    from tabs.keymap_tab import SetCard, MovementKeyField
    card = SetCard(index=0, set_data={
        "name": "Default", "forward": "Up", "reverse": "Down",
        "left": "Left", "right": "Right", "jump": "space",
        "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L",
    }, active_game="ttr")
    fwd = card.findChild(MovementKeyField, "key_field_forward")
    assert fwd is not None
    assert fwd.get_key() == "Up"


def test_setcard_accepts_is_dark_kwarg(qapp):
    from tabs.keymap_tab import SetCard
    card_dark = SetCard(index=0, set_data={"name": "Default"}, is_dark=True)
    card_light = SetCard(index=0, set_data={"name": "Default"}, is_dark=False)
    assert card_dark._is_dark is True
    assert card_light._is_dark is False


def test_setcard_set_theme_updates_internal_state(qapp):
    from tabs.keymap_tab import SetCard
    card = SetCard(index=0, set_data={"name": "Default"}, is_dark=True)
    assert card._is_dark is True
    card.set_theme(is_dark=False)
    assert card._is_dark is False


def test_setcard_paints_in_both_themes(qapp):
    """paintEvent must not raise in either theme."""
    from PySide6.QtGui import QPixmap
    from tabs.keymap_tab import SetCard
    for is_dark in (True, False):
        card = SetCard(index=0, set_data={"name": "Default"}, is_dark=is_dark)
        card.resize(400, 80)
        pm = QPixmap(card.size())
        pm.fill()
        card.render(pm)


def test_bodyclip_constructs(qapp):
    from tabs.keymap_tab import _BodyClip
    clip = _BodyClip()
    assert clip is not None
    # No content set yet -> natural_height returns 0
    assert clip.natural_height() == 0


def test_bodyclip_set_content_widget_reparents(qapp):
    from tabs.keymap_tab import _BodyClip
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
    clip = _BodyClip()
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(QLabel("hello world line one"))
    lay.addWidget(QLabel("hello world line two"))
    clip.set_content_widget(content)
    assert content.parent() is clip
    # Natural height reflects the content's layout minimumSize().
    assert clip.natural_height() > 0


def test_bodyclip_content_height_property(qapp):
    from tabs.keymap_tab import _BodyClip
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
    clip = _BodyClip()
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.addWidget(QLabel("a"))
    lay.addWidget(QLabel("b"))
    clip.set_content_widget(content)
    # Setting content_height should clamp the clip's effective height.
    clip.setProperty("content_height", 12)
    assert clip.minimumHeight() == 12
    assert clip.maximumHeight() == 12
    # Setting to 0 collapses.
    clip.setProperty("content_height", 0)
    assert clip.minimumHeight() == 0
    assert clip.maximumHeight() == 0


def test_bodyclip_expand_emits_signal(qapp):
    from tabs.keymap_tab import _BodyClip
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
    from PySide6.QtCore import QEventLoop, QTimer
    import utils.motion as motion

    clip = _BodyClip()
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.addWidget(QLabel("row a"))
    lay.addWidget(QLabel("row b"))
    clip.set_content_widget(content)

    # Force reduced-motion path so expand() resolves synchronously.
    original_scale = motion._TEST_DURATION_SCALE
    motion._TEST_DURATION_SCALE = 0.0
    try:
        fired = []
        clip.expand_finished.connect(lambda: fired.append(True))
        clip.expand()
        # Pump the event loop briefly so the 0-duration animation finishes.
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
        assert fired == [True]
    finally:
        motion._TEST_DURATION_SCALE = original_scale


def test_setcard_body_is_bodyclip(qapp):
    from tabs.keymap_tab import SetCard, _BodyClip
    card = SetCard(index=0, set_data={"name": "Default"})
    assert isinstance(card._body, _BodyClip)


def test_setcard_header_has_fixed_height(qapp):
    from tabs.keymap_tab import SetCard
    card = SetCard(index=0, set_data={"name": "Default"})
    h = card._header
    # Header should be locked: min == max == natural sizeHint.
    assert h.minimumHeight() > 0
    assert h.minimumHeight() == h.maximumHeight()


def test_movementkeyfield_has_pointer_cursor(qapp):
    from tabs.keymap_tab import MovementKeyField
    from PySide6.QtCore import Qt
    field = MovementKeyField("Up")
    assert field.cursor().shape() == Qt.PointingHandCursor


def test_direction_label_width_fits_forward(qapp):
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QLabel
    from PySide6.QtGui import QFontMetrics
    card = SetCard(index=0, set_data={
        "name": "Default", "forward": "Up", "reverse": "Down",
        "left": "Left", "right": "Right", "jump": "space",
        "book": "Alt_L", "gags": "g", "tasks": "t", "map": "Shift_L",
    }, active_game="ttr")
    forward_label = None
    for lbl in card.findChildren(QLabel, "direction_label"):
        if lbl.text() == "Forward":
            forward_label = lbl
            break
    assert forward_label is not None, "could not find the Forward direction_label"
    fm = QFontMetrics(forward_label.font())
    advance = fm.horizontalAdvance("Forward")
    # +4 px slack for Qt's text-rendering padding (label width is a fixed
    # box, the rendered text needs a tiny bit of room inside).
    assert forward_label.width() >= advance + 4, (
        f"direction_label width {forward_label.width()} is too narrow for "
        f"'Forward' text width {advance} (need {advance + 4})"
    )
