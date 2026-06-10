import os
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QStyledItemDelegate


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def test_current_value_delegate_can_be_installed_on_combobox(app):
    from utils.shared_widgets import _CurrentValueDelegate
    cb = QComboBox()
    cb.addItems(["A", "B", "C"])
    delegate = _CurrentValueDelegate(cb)
    cb.setItemDelegate(delegate)
    assert cb.itemDelegate() is delegate
    assert isinstance(delegate, QStyledItemDelegate)


def test_settings_combobox_auto_installs_current_value_delegate(app):
    from utils.shared_widgets import SettingsComboBox, _CurrentValueDelegate
    cb = SettingsComboBox()
    cb.addItems(["A", "B", "C"])
    assert isinstance(cb.itemDelegate(), _CurrentValueDelegate)


def test_settings_combobox_is_a_qcombobox(app):
    from utils.shared_widgets import SettingsComboBox
    cb = SettingsComboBox()
    assert isinstance(cb, QComboBox)


def test_settings_combobox_preserves_currentindex_semantics(app):
    from utils.shared_widgets import SettingsComboBox
    cb = SettingsComboBox()
    cb.addItems(["A", "B", "C"])
    cb.setCurrentIndex(2)
    assert cb.currentIndex() == 2
    assert cb.currentText() == "C"


def test_current_value_delegate_paints_dot_on_current_row(app):
    """Render the menu's current row to a QPixmap and confirm the dot's
    pixel matches the combo's configured accent color."""
    from PySide6.QtGui import QPixmap, QPainter, QColor
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem
    from utils.shared_widgets import SettingsComboBox

    cb = SettingsComboBox()
    cb.addItems(["A", "B", "C"])
    cb.setCurrentIndex(1)  # "B"

    model = cb.model()
    delegate = cb.itemDelegate()

    # Render row B (current).
    pm = QPixmap(120, 28)
    pm.fill(QColor(0, 0, 0))  # opaque background so the dot is unambiguous
    painter = QPainter(pm)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 120, 28)
    delegate.paint(painter, option, model.index(1, 0))
    painter.end()

    # Dot center is at (right - 12 - 3, height/2) = (105, 14).
    img = pm.toImage()
    sample = img.pixelColor(105, 14)
    # Default accent is #0077ff (R=0, G=119, B=255). Antialiasing softens
    # edges, but the center pixel should be at or very near the pure color.
    assert sample.red() < 30, f"expected R≈0, got R={sample.red()}"
    assert 90 < sample.green() < 140, f"expected G≈119, got G={sample.green()}"
    assert sample.blue() > 220, f"expected B≈255, got B={sample.blue()}"


def test_set_theme_colors_changes_dot_to_configured_accent(app):
    """Light theme's accent_blue_btn is #2563eb, distinct from the dark
    default #0077ff. set_theme_colors must propagate to the painted dot."""
    from PySide6.QtGui import QPixmap, QPainter, QColor
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem
    from utils.shared_widgets import SettingsComboBox

    cb = SettingsComboBox()
    cb.addItems(["A", "B"])
    cb.setCurrentIndex(0)
    cb.set_theme_colors(accent="#2563eb")  # light-theme accent

    pm = QPixmap(120, 28)
    pm.fill(QColor(0, 0, 0))
    painter = QPainter(pm)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 120, 28)
    cb.itemDelegate().paint(painter, option, cb.model().index(0, 0))
    painter.end()

    img = pm.toImage()
    sample = img.pixelColor(105, 14)
    # #2563eb is (R=37, G=99, B=235) — distinct from default #0077ff (R=0, G=119, B=255).
    # Green and blue differ from the default by enough that this catches
    # any regression where the dot ignores set_theme_colors.
    assert sample.green() < 110, f"expected G<110 (light accent), got G={sample.green()}"
    assert sample.red() > 20, f"expected R>20 (light accent), got R={sample.red()}"


def test_current_value_delegate_does_not_paint_dot_on_non_current_row(app):
    from PySide6.QtGui import QPixmap, QPainter, QColor
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem
    from utils.shared_widgets import SettingsComboBox

    cb = SettingsComboBox()
    cb.addItems(["A", "B", "C"])
    cb.setCurrentIndex(1)  # "B" is current

    model = cb.model()
    delegate = cb.itemDelegate()

    pm = QPixmap(120, 28)
    pm.fill(QColor(0, 0, 0))
    painter = QPainter(pm)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 120, 28)
    delegate.paint(painter, option, model.index(2, 0))  # row "C", NOT current
    painter.end()

    img = pm.toImage()
    sample = img.pixelColor(120 - 15, 14)
    # No dot — should still be background-ish (low blue).
    assert sample.blue() < 100, f"expected no dot, got B={sample.blue()}"


def test_settings_combobox_paints_chevron_in_droparea(app):
    """After paintEvent, the right edge (where the chevron lives) should
    have non-background pixels in roughly the idle-gray range."""
    from PySide6.QtGui import QColor
    from utils.shared_widgets import SettingsComboBox

    cb = SettingsComboBox()
    cb.addItems(["A"])
    cb.resize(180, 30)
    cb.show()
    app.processEvents()

    pm = cb.grab()
    img = pm.toImage()
    # Caret cell is the rightmost 30px; chevron center is ~15px from right edge.
    cx = pm.width() - 15
    cy = pm.height() // 2
    # Look across a +-4px horizontal band for any stroke pixel (not background).
    found_stroke = False
    for dx in range(-4, 5):
        c = img.pixelColor(cx + dx, cy)
        # Idle chevron is dark gray (#aaaaaa). Any pixel that's clearly
        # not background and has roughly equal RGB (gray, not blue) counts.
        if 100 < c.red() < 220 and abs(c.red() - c.green()) < 25 and abs(c.red() - c.blue()) < 25:
            found_stroke = True
            break
    cb.hide()
    assert found_stroke, "expected idle gray chevron strokes in drop-down area"


def test_settings_combobox_chevron_color_follows_is_dark_flag(app):
    """Verify the is_dark flag actually changes what's painted by
    comparing dark vs light renders. Dark idle stroke is #aaaaaa (R=170);
    light idle stroke is #64748b (R=100). They must be distinguishably
    different — a regression that ignored the flag would produce
    identical pixels and fail this test."""
    from utils.shared_widgets import SettingsComboBox

    def _sample_stroke_pixel(cb):
        """Return the darkest stroke pixel on the left arm of the chevron.

        The chevron is drawn as a darker stroke over whatever the platform
        renders as the combo background. On offscreen (CI) the bg is
        near-white; on a dark theme/style the bg is dark — either way the
        stroke is the darker pixel relative to bg, so we sample the
        darkest pixel in a small window on the left arm of the chevron.
        We scan only dx in [-4, -1] to stay clear of right-side combo
        border/shadow pixels that appear at dx=0 and beyond."""
        pm = cb.grab()
        img = pm.toImage()
        cx = pm.width() - 15
        cy = pm.height() // 2
        darkest = None
        for dy in range(-3, 4):
            for dx in range(-4, 0):  # left arm: stop before dx=0 (border zone)
                c = img.pixelColor(cx + dx, cy + dy)
                if darkest is None or c.red() < darkest.red():
                    darkest = c
        return darkest

    cb_dark = SettingsComboBox()
    cb_dark.addItems(["A"])
    cb_dark.set_theme_colors(accent="#0077ff", is_dark=True)
    cb_dark.resize(180, 30)
    cb_dark.show()
    app.processEvents()

    cb_light = SettingsComboBox()
    cb_light.addItems(["A"])
    cb_light.set_theme_colors(accent="#2563eb", is_dark=False)
    cb_light.resize(180, 30)
    cb_light.show()
    app.processEvents()

    dark_stroke = _sample_stroke_pixel(cb_dark)
    light_stroke = _sample_stroke_pixel(cb_light)
    cb_dark.hide()
    cb_light.hide()

    assert dark_stroke is not None, "no stroke pixel found in dark render"
    assert light_stroke is not None, "no stroke pixel found in light render"
    # Dark idle #aaaaaa (R=170) vs light idle #64748b (R=100): center
    # pixels should differ by a lot (>30 even after antialiasing).
    diff = abs(dark_stroke.red() - light_stroke.red())
    assert diff > 30, (
        f"expected dark and light chevron strokes to differ visibly; "
        f"got dark R={dark_stroke.red()}, light R={light_stroke.red()}, diff={diff}"
    )


@pytest.fixture
def settings_manager():
    class _Stub:
        def __init__(self):
            self._d = {}
            self._listeners = []

        def get(self, key, default=None):
            return self._d.get(key, default)

        def set(self, key, value):
            self._d[key] = value
            for fn in list(self._listeners):
                fn(key, value)

        def on_change(self, fn):
            self._listeners.append(fn)

    return _Stub()


def test_general_page_theme_dropdown_is_settings_combobox(app, settings_manager):
    """The Appearance (theme) dropdown on the General page must be a SettingsComboBox
    (not a plain QComboBox), so it gets the custom chevron + current-value
    dot via inheritance."""
    from utils.shared_widgets import SettingsComboBox
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    combo = _find_combo_by_label(tab, "Appearance")
    tab.deleteLater()
    assert isinstance(combo, SettingsComboBox), (
        f"Appearance dropdown is {type(combo).__name__}, expected SettingsComboBox"
    )


def test_all_settings_combos_are_settings_combobox(app, settings_manager):
    """All 5 known Settings dropdowns must be SettingsComboBox instances."""
    from PySide6.QtWidgets import QComboBox
    from utils.shared_widgets import SettingsComboBox
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    combos = tab.findChildren(QComboBox)
    # Filter to direct settings combos (delegate may install a QComboBox-like
    # internal somewhere, but the visible ones we set_control() into rows
    # should all be SettingsComboBox).
    non_settings = [c for c in combos if not isinstance(c, SettingsComboBox)]
    tab.deleteLater()
    assert not non_settings, (
        f"Found {len(non_settings)} QComboBox(es) that are not SettingsComboBox: "
        f"{[type(c).__name__ for c in non_settings]}"
    )
    assert len(combos) == 5, (
        f"Expected exactly 5 dropdowns on the Settings tab, found {len(combos)}"
    )


def _find_combo_by_label(tab, label_text):
    """Walk the tab's widget tree, find a SettingsField whose label matches,
    return its control widget (a QComboBox or subclass)."""
    from PySide6.QtWidgets import QLabel, QComboBox
    for label in tab.findChildren(QLabel):
        if label.text() == label_text:
            field = label.parent()
            for child in field.findChildren(QComboBox):
                return child
    return None


def test_menu_text_role_overrides_painted_menu_item_text(app):
    """If an item has MENU_TEXT_ROLE data, the delegate paints that long-form
    text in the menu, while the closed state (currentText) keeps the short
    DisplayRole value. Used by Reduce motion: closed shows "System",
    menu shows "System default"."""
    from PySide6.QtGui import QPixmap, QPainter, QColor
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtWidgets import QStyleOptionViewItem
    from utils.shared_widgets import SettingsComboBox, MENU_TEXT_ROLE

    cb = SettingsComboBox()
    cb.addItems(["System", "On", "Off"])
    cb.setItemData(0, "System default", MENU_TEXT_ROLE)
    cb.setCurrentIndex(0)

    # Closed-state representation: currentText reflects the DisplayRole only.
    assert cb.currentText() == "System", (
        f"closed state must show short text; got {cb.currentText()!r}"
    )

    # Menu rendering goes through the delegate. initStyleOption must swap
    # option.text to the long-form when MENU_TEXT_ROLE is set.
    delegate = cb.itemDelegate()
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 200, 28)
    delegate.initStyleOption(option, cb.model().index(0, 0))
    assert option.text == "System default", (
        f"menu must show long-form text; got {option.text!r}"
    )

    # Items without the role keep their DisplayRole text unchanged.
    option2 = QStyleOptionViewItem()
    option2.rect = QRect(0, 0, 200, 28)
    delegate.initStyleOption(option2, cb.model().index(1, 0))
    assert option2.text == "On", (
        f"non-overridden item must keep DisplayRole; got {option2.text!r}"
    )


def test_reduce_motion_combo_uses_short_closed_text(app, settings_manager):
    """The Reduce motion dropdown's first option must show "System" in the
    closed state (not the truncated "System d") while still offering
    "System default" in the open menu."""
    from utils.shared_widgets import SettingsComboBox, MENU_TEXT_ROLE
    from tabs.settings_tab import SettingsTab

    tab = SettingsTab(settings_manager)
    combo = _find_combo_by_label(tab, "Reduce motion")
    assert combo is not None, "could not find Reduce motion dropdown"

    # itemText(0) reflects what's drawn in the closed state.
    short_text = combo.itemText(0)
    # itemData with MENU_TEXT_ROLE is what the menu shows.
    long_text = combo.itemData(0, MENU_TEXT_ROLE)
    tab.deleteLater()

    assert short_text == "System", (
        f"closed-state text must be 'System' (no truncation); got {short_text!r}"
    )
    assert long_text == "System default", (
        f"menu text must remain descriptive; got {long_text!r}"
    )


def test_chat_handling_radio_list_exists_with_forwarding_logic_label(app, settings_manager):
    from utils.shared_widgets import SettingsRadioList
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    try:
        rl = tab._chat_handling_radio_list
        assert isinstance(rl, SettingsRadioList)
        assert [r.value for r in rl._rows] == [
            "focused_only", "all_toons", "keyset_dynamic", "per_toon",
        ]
        assert tab._chat_handling_field.label_widget.text() == "Forwarding Logic"
    finally:
        tab.deleteLater()


def test_chat_handling_radio_normalizes_legacy_advanced(app, settings_manager):
    from tabs.settings_tab import SettingsTab
    settings_manager.set("chat_handling_mode", "advanced")
    tab = SettingsTab(settings_manager)
    try:
        assert tab._chat_handling_radio_list.value() == "per_toon"
    finally:
        tab.deleteLater()


def test_chat_handling_radio_resets_legacy_simple_to_default(app, settings_manager):
    """A persisted legacy 'simple' (the old implicit default) selects
    Focused Toon Only: only a choice made in the new control counts as an
    explicit mode selection."""
    from tabs.settings_tab import SettingsTab
    settings_manager.set("chat_handling_mode", "simple")
    tab = SettingsTab(settings_manager)
    try:
        assert tab._chat_handling_radio_list.value() == "focused_only"
    finally:
        tab.deleteLater()


def test_chat_handling_radio_default_focused_only(app, settings_manager):
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    try:
        assert tab._chat_handling_radio_list.value() == "focused_only"
    finally:
        tab.deleteLater()


def test_chat_handling_build_never_writes_setting(app, settings_manager):
    """Hardened no-write regression: spy on settings_manager.set so even a
    write-and-restore during construction is caught (a final-value
    comparison alone would miss it)."""
    from tabs.settings_tab import SettingsTab
    settings_manager.set("chat_handling_mode", "advanced")
    calls = []
    orig_set = settings_manager.set
    settings_manager.set = lambda k, v: (calls.append((k, v)), orig_set(k, v))[1]
    tab = SettingsTab(settings_manager)
    try:
        chat_writes = [kv for kv in calls if kv[0] == "chat_handling_mode"]
        assert chat_writes == [], f"construction wrote: {chat_writes}"
        assert settings_manager.get("chat_handling_mode") == "advanced"
    finally:
        settings_manager.set = orig_set
        tab.deleteLater()


def test_chat_handling_radio_change_persists_and_emits(app, settings_manager):
    """User selection writes the canonical value AND emits the signal
    carrying that value (matches the old dropdown test's coverage)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    received = []
    tab.chat_handling_mode_changed.connect(received.append)
    try:
        rl = tab._chat_handling_radio_list
        rl.show()
        app.processEvents()
        QTest.mouseClick(rl._rows[3].radio, Qt.LeftButton)  # Per-Toon (manual)
        app.processEvents()
        assert settings_manager.get("chat_handling_mode") == "per_toon"
        assert received == ["per_toon"]
    finally:
        tab.deleteLater()


def test_chat_handling_radio_list_fits_compact_width(app, settings_manager):
    """The radio list must never demand more horizontal room than the real
    usable panel width (~349px), so the card cannot overflow at compact
    window sizes. Promotes the smoke probe's tab-level assertion into the
    committed suite."""
    from tabs.settings_tab import SettingsTab
    tab = SettingsTab(settings_manager)
    try:
        tab.resize(420, 700)
        app.processEvents()
        assert tab._chat_handling_radio_list.minimumSizeHint().width() <= 349
    finally:
        tab.deleteLater()


def test_chat_handling_theme_pass_reaches_radio_list(app, settings_manager, monkeypatch):
    """refresh_theme() must propagate tokens to the radio list (spying on
    the method catches a missing findChildren loop, which direct
    set_theme_colors calls in widget tests would not)."""
    from utils.shared_widgets import SettingsRadioList
    from tabs.settings_tab import SettingsTab
    calls = []
    orig = SettingsRadioList.set_theme_colors
    monkeypatch.setattr(
        SettingsRadioList, "set_theme_colors",
        lambda self, c, is_dark=True: (calls.append(self), orig(self, c, is_dark)),
    )
    tab = SettingsTab(settings_manager)
    try:
        calls.clear()  # ignore constructor-time default application
        tab.refresh_theme()
        assert tab._chat_handling_radio_list in calls
    finally:
        tab.deleteLater()
