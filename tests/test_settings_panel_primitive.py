"""Tests for the new SettingsField (row) and SettingsPanel (container)."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ── SettingsField ────────────────────────────────────────────────────────


def test_field_renders_label_only(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme")
    assert field.label_widget.text() == "Theme"
    assert field.helper_widget is None


def test_field_renders_label_with_helper(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme", helper="Switches between dark and light.")
    assert field.label_widget.text() == "Theme"
    assert field.helper_widget is not None
    assert field.helper_widget.text() == "Switches between dark and light."


def test_field_set_control_attaches_widget(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme")
    btn = QPushButton("Browse")
    field.set_control(btn)
    # Control widget is reachable through the field for theming and access.
    assert field.control_widget is btn
    # And actually placed in the layout (parent set to the field).
    assert btn.parentWidget() is field


def test_field_is_last_property_default_false(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme")
    assert field.is_last is False


def test_field_set_is_last_updates_property(qapp):
    from tabs.settings_tab import SettingsField
    field = SettingsField("Theme")
    field.set_is_last(True)
    assert field.is_last is True


def test_field_apply_theme_styles_labels(qapp):
    from tabs.settings_tab import SettingsField
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(is_dark=True)
    field = SettingsField("Theme", helper="Helper text.")
    field.apply_theme(c, is_dark=True)
    # text_primary should be applied to the main label.
    assert c["text_primary"] in field.label_widget.styleSheet()
    # text_muted should be applied to the helper.
    assert c["text_muted"] in field.helper_widget.styleSheet()


# ── SettingsPanel ────────────────────────────────────────────────────────


def test_panel_neutral_stripe_default(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="General")
    assert panel.stripe_kind == "neutral"


def test_panel_ttr_stripe(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="Toontown Rewritten", stripe="ttr")
    assert panel.stripe_kind == "ttr"


def test_panel_cc_stripe(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="Corporate Clash", stripe="cc")
    assert panel.stripe_kind == "cc"


@pytest.mark.parametrize("stripe,token", [
    ("blue",   "accent_blue_btn"),
    ("yellow", "accent_yellow"),
    ("orange", "accent_orange"),
    ("green",  "accent_green"),
    ("red",    "accent_red"),
    ("pink",   "accent_pink_border"),
])
def test_panel_named_color_stripe_resolves_to_palette_token(qapp, stripe, token):
    """Settings panels can use named accent stripes (blue/yellow/orange/
    green/red/pink). Each name must resolve to the matching palette token in
    both themes so dark/light render consistently."""
    from tabs.settings_tab import SettingsPanel
    from utils.theme_manager import get_theme_colors
    panel = SettingsPanel(title=stripe.title(), stripe=stripe)
    assert panel.stripe_kind == stripe
    for is_dark in (True, False):
        panel.apply_theme(get_theme_colors(is_dark), is_dark)
        expected = get_theme_colors(is_dark)[token]
        assert panel._stripe_color() == expected, (
            f"stripe={stripe} should resolve to {token} ({expected}) "
            f"in {'dark' if is_dark else 'light'}; got {panel._stripe_color()}"
        )


def test_panel_header_renders_title_and_sub(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="Games", sub="Subtitle here.")
    assert panel.title_label.text() == "Games"
    assert panel.sub_label is not None
    assert panel.sub_label.text() == "Subtitle here."


def test_panel_header_no_sub_label_when_omitted(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="Games")
    assert panel.sub_label is None


def test_panel_logo_loaded_when_path_provided(qapp, tmp_path):
    """Panels with a logo path display the logo at 40x40."""
    from tabs.settings_tab import SettingsPanel
    # Use the real bundled asset.
    asset = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "assets", "ttr.png",
    )
    panel = SettingsPanel(title="TTR", stripe="ttr", logo_path=asset)
    assert panel.logo_label is not None
    pm = panel.logo_label.pixmap()
    assert pm is not None and not pm.isNull()
    # Pixmap scaled to 40 on the long edge (KeepAspectRatio).
    assert max(pm.width(), pm.height()) == 40


def test_panel_no_logo_when_path_omitted(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="General")
    assert panel.logo_label is None


def test_panel_add_field_appends_and_marks_last(qapp):
    from tabs.settings_tab import SettingsPanel, SettingsField
    panel = SettingsPanel(title="General")
    f1 = SettingsField("Theme")
    f2 = SettingsField("Max accounts")
    panel.add_field(f1)
    panel.add_field(f2)
    # Both fields in the panel's tracking list.
    assert panel.fields == [f1, f2]
    # Only the last one has is_last True.
    assert f1.is_last is False
    assert f2.is_last is True


def test_panel_add_header_button_renders_in_button_row(qapp):
    """Header buttons live on their own row inside the header so they
    cannot be pushed off-screen by the title/sub column in compact mode."""
    from tabs.settings_tab import SettingsPanel
    from PySide6.QtWidgets import QPushButton
    panel = SettingsPanel(title="TTR", stripe="ttr")
    browse = QPushButton("Browse")
    detect = QPushButton("Auto-detect")
    panel.add_header_button(browse)
    panel.add_header_button(detect)
    # Both reachable for theming.
    assert browse in panel.header_buttons
    assert detect in panel.header_buttons
    # Both attached to the panel widget tree (parent chain reaches the panel).
    p = browse
    while p is not None and p is not panel:
        p = p.parentWidget()
    assert p is panel
    # Header height now includes the buttons row — force a layout pass first.
    panel.show()
    panel.adjustSize()
    assert panel.header_widget.height() >= SettingsPanel.HEADER_HEIGHT_WITH_LOGO


def test_panel_header_button_row_fits_in_compact_width(qapp):
    """At the compact content width (389 px = 575 main min - 130 sidebar
    - 56 page margins), both header buttons must fit inside the panel
    rather than extending past its right edge."""
    from tabs.settings_tab import SettingsPanel
    from PySide6.QtWidgets import QPushButton
    from utils.theme_manager import get_theme_colors

    panel = SettingsPanel(
        title="Toontown Rewritten", stripe="ttr", sub="~/games/ttr",
    )
    browse = QPushButton("Browse")
    browse.setFixedHeight(28)
    detect = QPushButton("Auto-detect")
    detect.setFixedHeight(28)
    panel.add_header_button(browse)
    panel.add_header_button(detect)
    panel.apply_theme(get_theme_colors(is_dark=True), is_dark=True)
    panel.resize(349, 200)
    # Force layout flush.
    panel.adjustSize()
    panel.resize(349, panel.sizeHint().height())
    panel.show()

    # Each button's right edge in panel-local coordinates must be inside
    # the panel's width.
    for btn in (browse, detect):
        right = btn.mapTo(panel, btn.rect().bottomRight()).x()
        assert right <= panel.width(), (
            f"{btn.text()!r} extends to x={right} but panel is {panel.width()} wide"
        )


def test_panel_apply_theme_does_not_crash(qapp):
    from tabs.settings_tab import SettingsPanel, SettingsField
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(is_dark=True)
    panel = SettingsPanel(title="Games", stripe="ttr", sub="x")
    panel.add_field(SettingsField("Field A"))
    panel.add_field(SettingsField("Field B", helper="helper"))
    panel.apply_theme(c, is_dark=True)


# ── SettingsPanel.set_sub ────────────────────────────────────────────────


def test_panel_set_sub_creates_label_when_absent(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="TTR", stripe="ttr")
    assert panel.sub_label is None
    panel.set_sub("~/games/ttr")
    assert panel.sub_label is not None
    assert panel.sub_label.text() == "~/games/ttr"


def test_panel_set_sub_replaces_existing_text(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="TTR", stripe="ttr", sub="initial")
    panel.set_sub("updated")
    assert panel.sub_label.text() == "updated"


def test_panel_set_sub_rich_text_format(qapp):
    from PySide6.QtCore import Qt as _Qt
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="CC", stripe="cc", sub=" ")
    panel.set_sub("<span style='color:red'>x</span>", rich_text=True)
    assert panel.sub_label.textFormat() == _Qt.RichText
    panel.set_sub("plain path", rich_text=False)
    assert panel.sub_label.textFormat() == _Qt.PlainText


def test_panel_set_sub_color_override_applied(qapp):
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="X", stripe="neutral", sub="x")
    panel.set_sub("error path", color_override="#E05252")
    assert "#E05252" in panel.sub_label.styleSheet()


def test_panel_set_sub_runtime_create_resizes_header(qapp):
    """Regression: a panel built without sub must grow its header when set_sub
    is later called, so the sub label is not visually clipped."""
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="X", stripe="neutral")  # no sub
    initial_height = panel.header_widget.height()
    panel.set_sub("late-added sub")
    assert panel.header_widget.height() > initial_height


def test_panel_ttr_stripe_is_visible_after_apply_theme(qapp):
    """Render the TTR panel offscreen and confirm a pixel inside the top
    stripe area carries the TTR brand color. This is the regression test
    for the missing-chrome bug found in the first smoke-test."""
    from PySide6.QtGui import QColor, QImage
    from utils.theme_manager import get_theme_colors
    from tabs.settings_tab import SettingsPanel

    panel = SettingsPanel(title="TTR", stripe="ttr", sub="path")
    panel.apply_theme(get_theme_colors(is_dark=True), is_dark=True)
    panel.resize(400, 120)

    img = QImage(panel.size(), QImage.Format_ARGB32)
    img.fill(0)
    panel.render(img)

    # The brand stripe sits in the top STRIPE_HEIGHT pixels. Sample at y=1
    # to land squarely inside it, well away from the corner rounding.
    sample = QColor(img.pixel(200, 1))
    ttr = QColor("#4A8FE7")
    # Allow modest tolerance for antialiasing and the rounded corners' AA
    # bleed at y=1; the body of the stripe should still be close to brand.
    assert abs(sample.red() - ttr.red()) < 40, (
        f"stripe pixel {sample.getRgb()} not close to TTR brand {ttr.getRgb()}"
    )
    assert abs(sample.green() - ttr.green()) < 40
    assert abs(sample.blue() - ttr.blue()) < 40


def test_panel_neutral_stripe_does_not_use_brand_colors(qapp):
    """A neutral panel must not paint TTR or CC brand colors anywhere
    in its top stripe."""
    from PySide6.QtGui import QColor, QImage
    from utils.theme_manager import get_theme_colors
    from tabs.settings_tab import SettingsPanel

    panel = SettingsPanel(title="General")
    panel.apply_theme(get_theme_colors(is_dark=True), is_dark=True)
    panel.resize(400, 120)

    img = QImage(panel.size(), QImage.Format_ARGB32)
    img.fill(0)
    panel.render(img)

    sample = QColor(img.pixel(200, 1))
    ttr = QColor("#4A8FE7")
    cc = QColor("#F26D21")
    # Neutral stripe uses border_light (#555555 in dark). Confirm we're not
    # accidentally drawing a brand color.
    assert abs(sample.red() - ttr.red()) > 40 or abs(sample.blue() - ttr.blue()) > 40
    assert abs(sample.red() - cc.red()) > 40 or abs(sample.blue() - cc.blue()) > 40


def test_panel_body_fill_distinguishable_from_app_bg(qapp):
    """Panel body must be visibly distinct from the surrounding app bg,
    so the card surface reads as elevated. Sample a pixel inside the
    body area (below the stripe + header, above the bottom corner)."""
    from PySide6.QtGui import QColor, QImage
    from utils.theme_manager import get_theme_colors
    from tabs.settings_tab import SettingsPanel, SettingsField

    panel = SettingsPanel(title="General")
    panel.add_field(SettingsField("X"))
    panel.apply_theme(get_theme_colors(is_dark=True), is_dark=True)
    panel.resize(400, 200)

    img = QImage(panel.size(), QImage.Format_ARGB32)
    img.fill(0)
    panel.render(img)

    # Sample a pixel inside the body area (away from header border + bottom edge).
    sample = QColor(img.pixel(50, 80))
    bg_app = QColor("#1a1a1a")
    # Body should be bg_card (#252525) which is ~11 units brighter per channel.
    assert sample.red() - bg_app.red() >= 5, (
        f"body pixel {sample.getRgb()} not perceptibly brighter than "
        f"bg_app {bg_app.getRgb()}"
    )


def test_field_two_controls_stack_in_bottom_row(qapp):
    """When add_control is called twice, both controls migrate to the
    bottom row so they cannot be clipped by narrow viewport widths."""
    from tabs.settings_tab import SettingsField
    from PySide6.QtWidgets import QPushButton
    field = SettingsField("X")
    b1 = QPushButton("A")
    b2 = QPushButton("B")
    field.add_control(b1)
    field.add_control(b2)
    # Both buttons in the controls list.
    assert b1 in field._controls
    assert b2 in field._controls
    # Bottom row is visible once 2+ controls exist.
    assert field._bottom_row.isVisible() or not field._bottom_row.isHidden()
    # Parent of both buttons is the bottom_row widget.
    assert b1.parentWidget() is field._bottom_row
    assert b2.parentWidget() is field._bottom_row


def test_field_three_controls_all_in_bottom_row(qapp):
    """External CC log dir uses 3 buttons -- verify all three land in the
    bottom row."""
    from tabs.settings_tab import SettingsField
    from PySide6.QtWidgets import QPushButton
    field = SettingsField("External log")
    b1 = QPushButton("Browse")
    b2 = QPushButton("Clear")
    b3 = QPushButton("Detect")
    field.add_control(b1)
    field.add_control(b2)
    field.add_control(b3)
    for b in (b1, b2, b3):
        assert b.parentWidget() is field._bottom_row


def test_field_single_control_stays_on_top_row(qapp):
    """A field with only one control (like a Switch toggle) keeps it
    inline on the top row to the right of the label/helper."""
    from tabs.settings_tab import SettingsField
    from PySide6.QtWidgets import QPushButton
    field = SettingsField("Theme")
    btn = QPushButton("Browse")
    field.set_control(btn)
    assert btn.parentWidget() is field
    # Bottom row stays hidden.
    assert field._bottom_row.isHidden()


def test_panel_uses_launch_section_card_pattern(qapp):
    """Regression: SettingsPanel must mirror launch_section.py's proven
    section_card pattern to survive Qt's parent-stylesheet cascade.
    See utils/widgets/launch_section.py lines 132-148 for the reference.
    """
    from PySide6.QtCore import Qt
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="X", stripe="ttr")
    # 1. WA_StyledBackground enabled -- required for QSS bg to render
    assert panel.testAttribute(Qt.WA_StyledBackground), (
        "panel needs WA_StyledBackground for QSS bg/border/radius to render"
    )
    # 2. Outer layout has 1px inset so children don't overpaint chrome
    margins = panel.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (1, 1, 1, 1)
    # 3. Header + body have explicit objectNames so they can be styled
    assert panel.header_widget.objectName() == "settings_panel_header"
    assert panel._body_widget.objectName() == "settings_panel_body"
    # 4. Header + body have WA_StyledBackground for their transparent QSS
    assert panel.header_widget.testAttribute(Qt.WA_StyledBackground)
    assert panel._body_widget.testAttribute(Qt.WA_StyledBackground)


def test_panel_stripe_lives_in_border_top_qss(qapp):
    """The brand stripe must be encoded as the panel's CSS border-top
    width/color. paintEvent-based stripes get clobbered by the parent
    stylesheet cascade -- only the QSS border-top approach is robust."""
    from utils.theme_manager import get_theme_colors
    from tabs.settings_tab import SettingsPanel
    panel = SettingsPanel(title="TTR", stripe="ttr")
    panel.apply_theme(get_theme_colors(is_dark=True), is_dark=True)
    qss = panel.styleSheet()
    # Stripe color is in the border-top declaration.
    assert "border-top:" in qss
    # TTR brand color is #4A8FE7 -- check it shows up in the QSS.
    assert "#4A8FE7" in qss or "#4a8fe7" in qss


def test_panel_no_paintevent_override(qapp):
    """SettingsPanel must NOT override paintEvent -- Qt's default QFrame
    paintEvent + WA_StyledBackground correctly renders the QSS chrome.
    Adding a custom paintEvent (even one that calls super) historically
    caused chrome to disappear due to QPainter ordering issues with the
    style cascade. The test guards against re-introducing that bug."""
    from PySide6.QtWidgets import QFrame
    from tabs.settings_tab import SettingsPanel
    # SettingsPanel inherits paintEvent from QFrame -- it should not have
    # its own override defined on the class itself.
    assert "paintEvent" not in SettingsPanel.__dict__, (
        "SettingsPanel must not override paintEvent; use QSS chrome only "
        "(see launch_section.py for the reference pattern)"
    )


def test_field_has_transparent_background_to_let_panel_chrome_show(qapp):
    """SettingsField must declare transparent bg so the panel's body
    chrome (bg_card fill + left/right/bottom borders) shows through.
    Without this, the page widget's `background: bg_app` cascade leaks
    in and SettingsField paints opaque bg_app over the panel chrome.
    See utils/widgets/launch_section.py:166-168 for the same comment."""
    from PySide6.QtCore import Qt
    from tabs.settings_tab import SettingsField
    field = SettingsField("X")
    assert field.objectName() == "settings_field"
    assert field.testAttribute(Qt.WA_StyledBackground)
    # apply_theme must produce a stylesheet with transparent bg.
    from utils.theme_manager import get_theme_colors
    field.apply_theme(get_theme_colors(is_dark=True), is_dark=True)
    qss = field.styleSheet()
    assert "QFrame#settings_field" in qss
    assert "background: transparent" in qss


# ── SettingsField.set_full_width_control ────────────────────────────────


def test_set_full_width_control_places_widget_in_bottom_row(qapp):
    from PySide6.QtWidgets import QLabel
    from tabs.settings_tab import SettingsField
    f = SettingsField("Label")
    w = QLabel("control")
    f.set_full_width_control(w)
    try:
        assert f.control_widget is w
        assert f._controls == [w]
        assert w.parent() is f._bottom_row
        assert not f._bottom_row.isHidden()
        # Trailing stretch removed: the widget is the only layout item, so
        # it spans the full row width.
        assert f._bottom_control_slot.count() == 1
        assert f._bottom_control_slot.itemAt(0).widget() is w
        # Stretch factor 1, so the widget actually expands to fill the row
        # (a bare addWidget(widget) would still pass the count check).
        assert f._bottom_control_slot.stretch(0) == 1
    finally:
        f.deleteLater()


def test_set_full_width_control_replaces_previous(qapp):
    from PySide6.QtWidgets import QLabel
    from tabs.settings_tab import SettingsField
    f = SettingsField("Label")
    first, second = QLabel("one"), QLabel("two")
    f.set_full_width_control(first)
    f.set_full_width_control(second)
    try:
        assert f.control_widget is second
        assert f._controls == [second]
        assert f._bottom_control_slot.count() == 1
        assert f._bottom_control_slot.itemAt(0).widget() is second
        assert first.parent() is None
    finally:
        f.deleteLater()


def test_add_control_rejected_after_full_width(qapp):
    import pytest
    from PySide6.QtWidgets import QLabel
    from tabs.settings_tab import SettingsField
    f = SettingsField("Label")
    f.set_full_width_control(QLabel("full"))
    try:
        with pytest.raises(AssertionError):
            f.add_control(QLabel("extra"))
    finally:
        f.deleteLater()


def test_set_control_after_full_width_restores_normal_mode(qapp):
    from PySide6.QtWidgets import QLabel
    from tabs.settings_tab import SettingsField
    f = SettingsField("Label")
    f.set_full_width_control(QLabel("full"))
    normal = QLabel("normal")
    f.set_control(normal)
    try:
        assert f.control_widget is normal
        assert f._bottom_row.isHidden()
        # Trailing stretch restored for future add_control migrations.
        assert f._bottom_control_slot.count() == 1
        assert f._bottom_control_slot.itemAt(0).widget() is None  # stretch
        # add_control works again in normal mode.
        f.add_control(QLabel("second"))
        assert len(f._controls) == 2
    finally:
        f.deleteLater()
