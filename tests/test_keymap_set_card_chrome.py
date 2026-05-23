import pytest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton
from PySide6.QtCore import Qt


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_card(qapp, index=0, active_game="ttr", is_dark=True):
    from tabs.keymap_tab import SetCard
    return SetCard(
        index=index,
        set_data={
            "name": f"Set {index + 1}",
            "forward": "w", "reverse": "s", "left": "a", "right": "d",
            "jump": "space", "gags": "g",
        },
        active_game=active_game,
        is_dark=is_dark,
    )


def test_setcard_has_no_painted_paintevent(qapp):
    """SetCard chrome must come from QSS, not a QPainter override."""
    from tabs.keymap_tab import SetCard
    from PySide6.QtWidgets import QFrame
    # The base QFrame.paintEvent is fine. The deleted override pulled
    # QPainter + QPainterPath + QLinearGradient. Assert the method on
    # SetCard is the inherited QFrame method (no subclass override).
    assert SetCard.paintEvent is QFrame.paintEvent, (
        "SetCard.paintEvent override should be removed; chrome is QSS-driven now"
    )


def test_setcard_has_object_name(qapp):
    card = _make_card(qapp)
    assert card.objectName() == "set_card"


def test_setcard_qss_uses_set_color_top_border(qapp):
    from utils.theme_manager import get_set_color
    card = _make_card(qapp, index=2)  # SET_COLORS[2] = ("#DAA520", "#1a1a1a")
    bg_hex, _ = get_set_color(2)
    qss = card.styleSheet()
    assert "border-top: 2px solid" in qss
    assert bg_hex.lower() in qss.lower()


def test_setcard_qss_uses_bg_card_token(qapp):
    from utils.theme_manager import get_theme_colors
    card = _make_card(qapp, is_dark=True)
    c = get_theme_colors(True)
    qss = card.styleSheet()
    assert f"background: {c['bg_card']}" in qss
    assert f"border-left: 1px solid {c['border_card']}" in qss


def test_setcard_qss_has_border_radius(qapp):
    card = _make_card(qapp)
    assert "border-radius: 10px" in card.styleSheet()


def test_badge_background_is_set_color(qapp):
    from utils.theme_manager import get_set_color
    card = _make_card(qapp, index=3)  # SET_COLORS[3] = green
    bg_hex, text_hex = get_set_color(3)
    badge = card.findChild(QLabel, "set_card_badge")
    assert badge is not None
    assert bg_hex.lower() in badge.styleSheet().lower()
    assert text_hex.lower() in badge.styleSheet().lower()


def test_name_label_uses_text_primary(qapp):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    card = _make_card(qapp, index=0)  # default set => QLabel
    name = card.findChild(QLabel, "set_name_label")
    assert name is not None
    assert f"color: {c['text_primary']}" in name.styleSheet()
    assert "font-size: 15px" in name.styleSheet()


def test_chevron_color_is_text_muted(qapp):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    card = _make_card(qapp)
    assert card._chevron._color.name().lower() == c["text_muted"].lower()


def test_delete_button_uses_border_muted(qapp):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    card = _make_card(qapp, index=1)  # alternate set => has delete
    # The delete button is the only QPushButton in the header row.
    del_btn = card._del_btn
    assert del_btn is not None
    qss = del_btn.styleSheet()
    assert f"border: 1px solid {c['border_muted']}" in qss
    assert "background: transparent" in qss


def test_direction_label_uses_text_secondary(qapp):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    card = _make_card(qapp, index=0)
    labels = [lbl for lbl in card.findChildren(QLabel, "direction_label")]
    assert len(labels) > 0
    qss = labels[0].styleSheet()
    assert f"color: {c['text_secondary']}" in qss
    assert "font-size: 12px" in qss


def test_movementkeyfield_default_qss_is_token_driven(qapp):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    card = _make_card(qapp, index=0)
    from tabs.keymap_tab import MovementKeyField
    fields = card.findChildren(MovementKeyField)
    assert len(fields) > 0
    qss = fields[0].styleSheet()
    assert "background: transparent" in qss
    assert f"border: 1px solid {c['border_muted']}" in qss


def test_movementkeyfield_awaiting_uses_set_color(qapp):
    from utils.theme_manager import get_set_color
    bg_hex, _ = get_set_color(4)  # SET_COLORS[4] = orange
    card = _make_card(qapp, index=4)
    from tabs.keymap_tab import MovementKeyField
    field = card.findChildren(MovementKeyField)[0]
    qss = field.styleSheet()
    assert 'QLineEdit[awaiting="true"]' in qss
    assert bg_hex.lower() in qss.lower()


def test_no_shadow_on_card_after_build(qapp):
    """Drop shadow is intentionally absent in the redesign; LaunchSection
    cards do not shadow either."""
    from tabs.keymap_tab import KeymapTab, SetCard
    from utils.keymap_manager import KeymapManager

    class _FakeSettings:
        def __init__(self):
            self._d = {"ttr_engine_dir": "", "cc_engine_dir": "", "theme": "dark"}
        def get(self, k, default=None):
            return self._d.get(k, default)
        def set(self, k, v):
            self._d[k] = v
        def on_change(self, cb):
            pass

    tab = KeymapTab(KeymapManager(), settings_manager=_FakeSettings())
    cards = tab.findChildren(SetCard)
    assert len(cards) > 0
    for card in cards:
        assert card.graphicsEffect() is None, (
            "SetCard should not have a QGraphicsDropShadowEffect attached"
        )


def test_detect_button_qss_is_token_driven(qapp):
    from tabs.keymap_tab import KeymapTab
    from utils.keymap_manager import KeymapManager
    from utils.theme_manager import get_theme_colors
    from PySide6.QtWidgets import QPushButton

    class _FakeSettings:
        def __init__(self):
            self._d = {"ttr_engine_dir": "", "cc_engine_dir": "", "theme": "dark"}
        def get(self, k, default=None):
            return self._d.get(k, default)
        def set(self, k, v):
            self._d[k] = v
        def on_change(self, cb):
            pass

    tab = KeymapTab(KeymapManager(), settings_manager=_FakeSettings())
    tab.refresh_theme()
    c = get_theme_colors(True)
    btns = tab.findChildren(QPushButton, "detect_btn")
    assert len(btns) >= 1
    qss = btns[0].styleSheet()
    assert "background: transparent" in qss
    assert f"border: 1px solid {c['border_muted']}" in qss
    assert f"color: {c['text_secondary']}" in qss
    # Hover accent must be game-scoped: blue for TTR, orange for CC.
    # _FakeSettings forces TTR detection above; assert TTR accent here.
    assert f"border: 1px solid {c['accent_blue_btn']}" in qss
    assert f"color: {c['accent_blue_btn']}" in qss


def test_detect_button_uses_cc_accent_when_active(qapp, monkeypatch):
    from tabs.keymap_tab import KeymapTab
    from utils.keymap_manager import KeymapManager
    from utils.theme_manager import get_theme_colors
    from PySide6.QtWidgets import QPushButton

    class _FakeSettings:
        def __init__(self):
            self._d = {"ttr_engine_dir": "", "cc_engine_dir": "", "theme": "dark"}
        def get(self, k, default=None):
            return self._d.get(k, default)
        def set(self, k, v):
            self._d[k] = v
        def on_change(self, cb):
            pass

    # Force CC-only detection so _active_game becomes "cc".
    monkeypatch.setattr(KeymapTab, "_ttr_detected", lambda self: False)
    monkeypatch.setattr(KeymapTab, "_cc_detected", lambda self: True)

    tab = KeymapTab(KeymapManager(), settings_manager=_FakeSettings())
    tab.refresh_theme()
    c = get_theme_colors(True)
    btns = tab.findChildren(QPushButton, "detect_btn")
    assert len(btns) >= 1
    qss = btns[0].styleSheet()
    assert f"border: 1px solid {c['accent_orange_border']}" in qss
    assert f"color: {c['accent_orange_border']}" in qss
