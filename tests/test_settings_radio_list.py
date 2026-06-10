"""Unit tests for SettingsRadioList (offscreen).

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
    tests/test_settings_radio_list.py -p no:cacheprovider -v
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


ITEMS = [
    ("a", "Alpha", "first description"),
    ("b", "Beta", "second description"),
    ("c", "Gamma", "third description"),
]


def _make(app):
    from utils.shared_widgets import SettingsRadioList
    rl = SettingsRadioList(ITEMS)
    rl.show()
    app.processEvents()
    return rl


def test_rows_match_items_in_order(app):
    rl = _make(app)
    try:
        assert [r.value for r in rl._rows] == ["a", "b", "c"]
        assert [r.radio.text() for r in rl._rows] == ["Alpha", "Beta", "Gamma"]
        assert [r.desc.fullText() for r in rl._rows] == [
            "first description", "second description", "third description",
        ]
    finally:
        rl.deleteLater()


def test_first_item_starts_selected_silently(app):
    from utils.shared_widgets import SettingsRadioList
    received = []
    rl = SettingsRadioList(ITEMS)
    rl.value_changed.connect(received.append)
    try:
        assert rl.value() == "a"
        assert received == []  # construction emitted nothing
    finally:
        rl.deleteLater()


def test_constructor_rejects_empty_and_duplicate_items(app):
    from utils.shared_widgets import SettingsRadioList
    with pytest.raises(AssertionError):
        SettingsRadioList([])
    with pytest.raises(AssertionError):
        SettingsRadioList([("x", "X", "d1"), ("x", "X2", "d2")])


def test_set_value_is_silent_and_selects(app):
    rl = _make(app)
    received = []
    rl.value_changed.connect(received.append)
    try:
        rl.set_value("b")
        assert rl.value() == "b"
        assert rl._rows[1].radio.isChecked()
        assert received == []
    finally:
        rl.deleteLater()


def test_set_value_unknown_is_noop(app):
    rl = _make(app)
    try:
        rl.set_value("b")
        rl.set_value("nope")
        assert rl.value() == "b"
    finally:
        rl.deleteLater()


def test_user_click_emits_exactly_once(app):
    rl = _make(app)
    received = []
    rl.value_changed.connect(received.append)
    try:
        QTest.mouseClick(rl._rows[2].radio, Qt.LeftButton)
        app.processEvents()
        assert rl.value() == "c"
        assert received == ["c"]
    finally:
        rl.deleteLater()


def test_click_on_row_background_and_description_selects(app):
    rl = _make(app)
    received = []
    rl.value_changed.connect(received.append)
    try:
        # Click the description label area; QLabel ignores the press so it
        # propagates to the row, whose whole surface activates the radio.
        QTest.mouseClick(rl._rows[1].desc, Qt.LeftButton)
        app.processEvents()
        assert rl.value() == "b"
        # Click the row frame itself (background area).
        QTest.mouseClick(rl._rows[2], Qt.LeftButton)
        app.processEvents()
        assert rl.value() == "c"
        assert received == ["b", "c"]
    finally:
        rl.deleteLater()


def test_reclick_selected_row_emits_nothing(app):
    rl = _make(app)
    received = []
    rl.value_changed.connect(received.append)
    try:
        QTest.mouseClick(rl._rows[0], Qt.LeftButton)  # already selected
        app.processEvents()
        assert received == []
        assert rl.value() == "a"
    finally:
        rl.deleteLater()


def test_exclusivity_one_checked_after_interactions(app):
    rl = _make(app)
    try:
        QTest.mouseClick(rl._rows[1].radio, Qt.LeftButton)
        QTest.mouseClick(rl._rows[2].radio, Qt.LeftButton)
        app.processEvents()
        assert sum(r.radio.isChecked() for r in rl._rows) == 1
        assert rl.value() == "c"
    finally:
        rl.deleteLater()


def test_arrow_key_moves_selection_and_emits_once(app):
    rl = _make(app)
    rl._rows[0].radio.setFocus()
    app.processEvents()
    received = []
    rl.value_changed.connect(received.append)
    try:
        QTest.keyClick(rl._rows[0].radio, Qt.Key_Down)
        app.processEvents()
        assert rl.value() == "b"
        assert received == ["b"]
    finally:
        rl.deleteLater()


def test_selected_property_tracks_selection(app):
    rl = _make(app)
    try:
        assert rl._rows[0].property("selected") == "true"
        rl.set_value("c")
        assert rl._rows[0].property("selected") == "false"
        assert rl._rows[2].property("selected") == "true"
    finally:
        rl.deleteLater()


def test_theme_colors_dark_and_light(app):
    rl = _make(app)
    try:
        dark = {
            "bg_card_inner": "#2e2e2e", "border_input": "#3a3a3a",
            "text_primary": "#ffffff", "text_muted": "#888888",
            "accent_blue_btn": "#0077ff",
        }
        rl.set_theme_colors(dark, is_dark=True)
        ss = rl.styleSheet()
        assert "#2e2e2e" in ss          # selected bg = bg_card_inner token
        assert "#0077ff" in ss          # accent reaches indicator/focus
        assert "background: transparent" in ss  # idle rows stay transparent
        light = {
            "bg_card_inner": "#f1f5f9", "border_input": "#cbd5e1",
            "text_primary": "#0f172a", "text_muted": "#475569",
            "accent_blue_btn": "#2563eb",
        }
        rl.set_theme_colors(light, is_dark=False)
        ss = rl.styleSheet()
        assert "#f1f5f9" in ss and "#2563eb" in ss
        assert "#2e2e2e" not in ss      # dark literals fully replaced
    finally:
        rl.deleteLater()


def test_descriptions_elide_at_narrow_width(app):
    from utils.shared_widgets import SettingsRadioList
    rl = SettingsRadioList([
        ("long", "Label", "an extremely long description that cannot possibly "
                          "fit inside a one hundred and sixty pixel row"),
    ])
    rl.setFixedWidth(160)
    rl.show()
    app.processEvents()
    try:
        desc = rl._rows[0].desc
        assert desc.text() != desc.fullText()       # elided
        assert desc.text().endswith("…")
        assert desc.toolTip() == desc.fullText()    # full text recoverable
        # The widget never demands more than its given width.
        assert rl.minimumSizeHint().width() <= 160
    finally:
        rl.deleteLater()
