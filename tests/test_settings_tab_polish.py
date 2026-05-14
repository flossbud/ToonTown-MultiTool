"""Tests for the Settings tab polish pass (2026-05-13)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_section_block_has_shadow_caster_wrapper(qapp):
    """SettingsGroup wraps its _block in a _SectionBlockWrapper that hosts
    a separate childless shadow caster. The wrapper is NOT a plain QWidget
    and the wrapper carries the dark/light flag from apply_theme.

    The real block stays effect-free because applying a graphics effect to
    the row container interferes with its custom paintEvent and child rows.
    """
    from tabs.settings_tab import SettingsGroup, _SectionBlockWrapper
    from utils.theme_manager import get_theme_colors
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    g = SettingsGroup("General")
    g.apply_theme(get_theme_colors(is_dark=True), True)

    assert isinstance(g._block_wrapper, _SectionBlockWrapper)
    # apply_theme propagates is_dark to the wrapper.
    assert g._block_wrapper._is_dark is True
    # Wrapper has no graphics effect — only the childless caster does.
    assert g._block_wrapper.graphicsEffect() is None
    # _block still has no effect (regression guard from the prior wrapper fix).
    assert g._block.graphicsEffect() is None
    assert isinstance(
        g._block_wrapper._shadow.graphicsEffect(),
        QGraphicsDropShadowEffect,
    )

    # Re-applying with is_dark=False updates the wrapper's flag.
    g.apply_theme(get_theme_colors(is_dark=False), False)
    assert g._block_wrapper._is_dark is False


def test_section_title_has_letter_spacing(qapp):
    """Section title stylesheet declares letter-spacing: 0.15px."""
    from tabs.settings_tab import SettingsGroup
    from utils.theme_manager import get_theme_colors

    g = SettingsGroup("General")
    g.apply_theme(get_theme_colors(is_dark=True), True)
    assert "letter-spacing: 0.15px" in g.title_label.styleSheet()
    # Weight is the explicit 700, not 'bold'
    assert "font-weight: 700" in g.title_label.styleSheet()


def test_collapsible_header_title_has_letter_spacing(qapp):
    """The collapsible header's title also uses the refined typography."""
    from tabs.settings_tab import CollapsibleSettingsGroup
    from utils.theme_manager import get_theme_colors

    class _FakeSM:
        def get(self, k, d=None): return d
        def set(self, k, v): pass
        def on_change(self, cb): pass

    g = CollapsibleSettingsGroup("Advanced", _FakeSM(), "advanced_collapsed")
    g.apply_theme(get_theme_colors(is_dark=True), True)
    assert "letter-spacing: 0.15px" in g._header.title_label.styleSheet()
    assert "font-weight: 700" in g._header.title_label.styleSheet()


def test_settings_row_hover_flag_toggles_on_enter_leave(qapp):
    """SettingsRow tracks hover state for ambient highlight paint."""
    from tabs.settings_tab import SettingsRow
    from PySide6.QtCore import QEvent

    row = SettingsRow("Label", "")
    assert row._hovered is False

    row.enterEvent(QEvent(QEvent.Enter))
    assert row._hovered is True

    row.leaveEvent(QEvent(QEvent.Leave))
    assert row._hovered is False


def test_settings_row_has_wa_hover_attribute(qapp):
    """WA_Hover must be set so enterEvent/leaveEvent fire."""
    from tabs.settings_tab import SettingsRow
    from PySide6.QtCore import Qt

    row = SettingsRow("Label", "")
    assert row.testAttribute(Qt.WA_Hover) is True


def test_collapsible_header_hover_flag_toggles(qapp):
    """The collapsible header tracks its own hover state separately."""
    from tabs.settings_tab import CollapsibleSettingsGroup
    from PySide6.QtCore import QEvent

    class _FakeSM:
        def get(self, k, d=None): return d
        def set(self, k, v): pass
        def on_change(self, cb): pass

    g = CollapsibleSettingsGroup("Advanced", _FakeSM(), "advanced_collapsed")
    h = g._header
    assert h._hovered is False

    h.enterEvent(QEvent(QEvent.Enter))
    assert h._hovered is True

    h.leaveEvent(QEvent(QEvent.Leave))
    assert h._hovered is False


def test_collapsible_header_has_wa_hover(qapp):
    from tabs.settings_tab import CollapsibleSettingsGroup
    from PySide6.QtCore import Qt

    class _FakeSM:
        def get(self, k, d=None): return d
        def set(self, k, v): pass
        def on_change(self, cb): pass

    g = CollapsibleSettingsGroup("Advanced", _FakeSM(), "advanced_collapsed")
    assert g._header.testAttribute(Qt.WA_Hover) is True


def test_leading_pill_widget_size_includes_halo(qapp):
    """_LeadingPill is a small fixed-size widget. Size = dot + 2*halo."""
    from tabs.settings_tab import _LeadingPill

    pill = _LeadingPill("game_pill_ttr")
    # SIZE=10 + HALO=2 on each side = 14×14
    assert pill.width() == 14
    assert pill.height() == 14


def test_leading_pill_resolves_token_on_apply_theme(qapp):
    """_LeadingPill stores the resolved hex color from the palette."""
    from tabs.settings_tab import _LeadingPill
    from utils.theme_manager import get_theme_colors

    pill = _LeadingPill("game_pill_ttr")
    pill.apply_theme(get_theme_colors(is_dark=True), True)
    # The token resolves to the dark-mode TTR pill color.
    assert pill._resolved_color == "#7e57c2"


def test_set_leading_indicator_inserts_pill_at_index_zero(qapp):
    """set_leading_indicator inserts the pill before the text column."""
    from tabs.settings_tab import SettingsRow, _LeadingPill

    row = SettingsRow("Label", "")
    row.set_leading_indicator("game_pill_ttr")
    # First item in the row's QHBoxLayout is the pill widget.
    first_item = row._layout.itemAt(0)
    assert isinstance(first_item.widget(), _LeadingPill)


def test_settings_row_without_leading_indicator_unaffected(qapp):
    """Rows that don't call set_leading_indicator have no pill column."""
    from tabs.settings_tab import SettingsRow, _LeadingPill

    row = SettingsRow("Label", "")
    # No call to set_leading_indicator.
    for i in range(row._layout.count()):
        widget = row._layout.itemAt(i).widget()
        assert not isinstance(widget, _LeadingPill)


def test_ttr_game_path_row_has_ttr_pill(qapp, tmp_path, monkeypatch):
    """A GamePathRow for the TTR engine dir gets a TTR-colored pill."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    from tabs.settings_tab import GamePathRow, _LeadingPill
    from utils.theme_manager import get_theme_colors

    sm = SettingsManager()
    row = GamePathRow(
        settings_manager=sm,
        settings_key="ttr_engine_dir",
        exe_name_fn=lambda: "TTREngine",
        find_path_fn=lambda: None,
        label="Toontown Rewritten",
    )
    assert isinstance(row._leading_pill, _LeadingPill)
    row.apply_theme(get_theme_colors(is_dark=True), True)
    assert row._leading_pill._resolved_color == "#7e57c2"  # game_pill_ttr (dark)


def test_cc_game_path_row_has_cc_pill(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    from tabs.settings_tab import GamePathRow, _LeadingPill
    from utils.theme_manager import get_theme_colors

    sm = SettingsManager()
    row = GamePathRow(
        settings_manager=sm,
        settings_key="cc_engine_dir",
        exe_name_fn=lambda: "ccengine",
        find_path_fn=lambda: None,
        label="Corporate Clash",
    )
    assert isinstance(row._leading_pill, _LeadingPill)
    row.apply_theme(get_theme_colors(is_dark=True), True)
    assert row._leading_pill._resolved_color == "#0077ff"  # game_pill_cc (dark)


def test_unknown_settings_key_game_path_row_has_no_pill(qapp, tmp_path, monkeypatch):
    """A GamePathRow with an unrelated settings key gets no pill (defensive)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    from tabs.settings_tab import GamePathRow

    sm = SettingsManager()
    row = GamePathRow(
        settings_manager=sm,
        settings_key="some_other_game_dir",
        exe_name_fn=lambda: "x",
        find_path_fn=lambda: None,
        label="Other",
    )
    assert not hasattr(row, "_leading_pill")


def test_collapsible_content_lives_in_container(qapp):
    """Content rows go inside _content_container; header is a sibling above."""
    from tabs.settings_tab import CollapsibleSettingsGroup, SettingsRow
    from PySide6.QtWidgets import QWidget

    class _FakeSM:
        def get(self, k, d=None): return False  # start expanded for this test
        def set(self, k, v): pass
        def on_change(self, cb): pass

    g = CollapsibleSettingsGroup("Advanced", _FakeSM(), "advanced_collapsed")
    row = SettingsRow("A", "")
    g.add_row(row)

    # Container exists and is a QWidget.
    assert isinstance(g._content_container, QWidget)
    # Header is in the block directly, not in the container.
    assert g._header.parent() is not g._content_container
    # The row is parented to the container.
    assert row.parent() is g._content_container


def test_collapsible_toggle_with_reduced_motion_snaps(qapp, monkeypatch):
    """When reduce_motion is on, toggle skips animation and snaps to final state."""
    from tabs.settings_tab import CollapsibleSettingsGroup, SettingsRow
    import utils.motion as motion

    class _FakeSM:
        def __init__(self):
            self.data = {"advanced_collapsed": True, "reduce_motion_set_explicitly": True, "reduce_motion": True}
        def get(self, k, d=None): return self.data.get(k, d)
        def set(self, k, v): self.data[k] = v
        def on_change(self, cb): pass

    sm = _FakeSM()
    motion.set_settings_manager(sm)
    g = CollapsibleSettingsGroup("Advanced", sm, "advanced_collapsed")
    g.add_row(SettingsRow("A", ""))
    g.toggle()  # collapse → expand
    # No animation in flight; height is snapped to no-max immediately.
    assert g._collapse_anim is None or g._collapse_anim.state() == 0
    assert g._content_container.maximumHeight() == 16777215
    # After expand, the row should be visible (not hidden).
    assert g._rows[0].isHidden() is False
    # Toggle back to collapse — row should be hidden synchronously.
    g.toggle()
    assert g._rows[0].isHidden() is True


def test_collapsible_toggle_with_normal_motion_starts_animation(qapp, monkeypatch):
    """With reduce_motion off and _TEST_DURATION_SCALE > 0, toggle starts an animation."""
    from tabs.settings_tab import CollapsibleSettingsGroup, SettingsRow
    from PySide6.QtCore import QAbstractAnimation
    import utils.motion as motion

    class _FakeSM:
        def __init__(self):
            self.data = {"advanced_collapsed": True, "reduce_motion_set_explicitly": True, "reduce_motion": False}
        def get(self, k, d=None): return self.data.get(k, d)
        def set(self, k, v): self.data[k] = v
        def on_change(self, cb): pass

    sm = _FakeSM()
    motion.set_settings_manager(sm)
    # Keep the test fast but DO run the animation.
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.01)
    g = CollapsibleSettingsGroup("Advanced", sm, "advanced_collapsed")
    g.add_row(SettingsRow("A", ""))
    g.toggle()
    assert g._collapse_anim is not None
    # Either still running or just-finished (with 0.01x duration it may finish in 0-1ms).
    assert g._collapse_anim.state() in (QAbstractAnimation.Running, QAbstractAnimation.Stopped)


def test_collapsible_animation_drives_exact_content_height(qapp, monkeypatch):
    """The animated property pins min/max height together each frame.

    Animating only maximumHeight lets the parent block ignore early frames and
    then jump to a later size. Pinning the content height forces layout size
    hints to track the animation value continuously.
    """
    from tabs.settings_tab import CollapsibleSettingsGroup, SettingsRow
    import utils.motion as motion

    class _FakeSM:
        def __init__(self):
            self.data = {
                "advanced_collapsed": True,
                "reduce_motion_set_explicitly": True,
                "reduce_motion": False,
            }
        def get(self, k, d=None): return self.data.get(k, d)
        def set(self, k, v): self.data[k] = v
        def on_change(self, cb): pass

    sm = _FakeSM()
    motion.set_settings_manager(sm)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 100.0)

    g = CollapsibleSettingsGroup("Advanced", sm, "advanced_collapsed")
    g.add_row(SettingsRow("A", ""))

    g.toggle()
    assert g._collapse_anim.targetObject() is g
    assert g._collapse_anim.propertyName().data().decode() == "content_height"
    assert g._block_wrapper._shadow.isHidden() is True

    g.content_height = 24
    assert g._content_clip.minimumHeight() == 24
    assert g._content_clip.maximumHeight() == 24
    assert g._content_container.maximumHeight() != 24


def test_collapsible_collapse_emits_scroll_reserve(qapp, monkeypatch):
    """Collapsing reserves the disappearing body height for scroll stability."""
    from tabs.settings_tab import CollapsibleSettingsGroup, SettingsRow
    import utils.motion as motion

    class _FakeSM:
        def __init__(self):
            self.data = {
                "advanced_collapsed": False,
                "reduce_motion_set_explicitly": True,
                "reduce_motion": False,
            }
        def get(self, k, d=None): return self.data.get(k, d)
        def set(self, k, v): self.data[k] = v
        def on_change(self, cb): pass

    sm = _FakeSM()
    motion.set_settings_manager(sm)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 100.0)

    g = CollapsibleSettingsGroup("Advanced", sm, "advanced_collapsed")
    g.add_row(SettingsRow("A", ""))
    g.show()
    qapp.processEvents()
    reserves = []
    g.scroll_reserve_changed.connect(reserves.append)

    natural_height = g._content_natural_height()
    assert natural_height > 8
    g.toggle()
    g.content_height = natural_height - 8

    assert reserves[-1] == 8


def test_collapsible_toggle_interrupts_in_flight_animation(qapp, monkeypatch):
    """A second toggle while one is running stops the first and starts a new one."""
    from tabs.settings_tab import CollapsibleSettingsGroup, SettingsRow
    import utils.motion as motion

    class _FakeSM:
        def __init__(self):
            self.data = {"advanced_collapsed": True, "reduce_motion_set_explicitly": True, "reduce_motion": False}
        def get(self, k, d=None): return self.data.get(k, d)
        def set(self, k, v): self.data[k] = v
        def on_change(self, cb): pass

    sm = _FakeSM()
    motion.set_settings_manager(sm)
    # Keep animation alive long enough that we can interrupt it.
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 100.0)
    g = CollapsibleSettingsGroup("Advanced", sm, "advanced_collapsed")
    g.add_row(SettingsRow("A", ""))
    g.toggle()
    first_anim = g._collapse_anim
    g.toggle()  # interrupt
    # The first animation must have been stopped before the second started.
    from PySide6.QtCore import QAbstractAnimation
    assert first_anim.state() == QAbstractAnimation.Stopped
    assert g._collapse_anim is not first_anim


def test_collapse_animation_starts_with_real_height(qapp, monkeypatch):
    """The collapse direction must capture the row-visible sizeHint BEFORE
    hiding rows; otherwise the animation runs 0→0 and is invisible."""
    from tabs.settings_tab import CollapsibleSettingsGroup, SettingsRow
    import utils.motion as motion

    class _FakeSM:
        def __init__(self):
            self.data = {
                "advanced_collapsed": False,  # start expanded
                "reduce_motion_set_explicitly": True,
                "reduce_motion": False,
            }
        def get(self, k, d=None): return self.data.get(k, d)
        def set(self, k, v): self.data[k] = v
        def on_change(self, cb): pass

    sm = _FakeSM()
    motion.set_settings_manager(sm)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 100.0)  # keep animation alive

    g = CollapsibleSettingsGroup("Advanced", sm, "advanced_collapsed")
    # Add a row so the container has a non-trivial sizeHint.
    g.add_row(SettingsRow("Test row", ""))
    # Force the layout to compute heights.
    g._content_container.adjustSize()

    g.toggle()  # collapse
    assert g._collapse_anim is not None
    assert g._collapse_anim.startValue() > 0
    assert g._collapse_anim.endValue() == 0


def test_chevron_widget_initial_rotation_matches_collapsed(qapp):
    """Chevron is 0° (pointing right) when group starts collapsed."""
    from tabs.settings_tab import CollapsibleSettingsGroup, _ChevronWidget

    class _FakeSM:
        def get(self, k, d=None): return True  # collapsed
        def set(self, k, v): pass
        def on_change(self, cb): pass

    g = CollapsibleSettingsGroup("Advanced", _FakeSM(), "advanced_collapsed")
    assert isinstance(g._header._chevron, _ChevronWidget)
    assert g._header._chevron.rotation == 0.0


def test_chevron_widget_initial_rotation_when_expanded(qapp):
    """Chevron is 90° (pointing down) when group starts expanded."""
    from tabs.settings_tab import CollapsibleSettingsGroup

    class _FakeSM:
        def get(self, k, d=None): return False  # expanded
        def set(self, k, v): pass
        def on_change(self, cb): pass

    g = CollapsibleSettingsGroup("Advanced", _FakeSM(), "advanced_collapsed")
    assert g._header._chevron.rotation == 90.0


def test_chevron_animates_on_toggle_with_motion(qapp, monkeypatch):
    """A toggle with reduce_motion off starts a rotation animation in parallel."""
    from tabs.settings_tab import CollapsibleSettingsGroup, SettingsRow
    import utils.motion as motion

    class _FakeSM:
        def __init__(self):
            self.data = {"advanced_collapsed": True, "reduce_motion_set_explicitly": True, "reduce_motion": False}
        def get(self, k, d=None): return self.data.get(k, d)
        def set(self, k, v): self.data[k] = v
        def on_change(self, cb): pass

    sm = _FakeSM()
    motion.set_settings_manager(sm)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 100.0)
    g = CollapsibleSettingsGroup("Advanced", sm, "advanced_collapsed")
    g.add_row(SettingsRow("A", ""))
    # Start: chevron at 0°.
    assert g._header._chevron.rotation == 0.0
    g.toggle()  # expand
    # Chevron animation is in flight; final value will be 90.
    assert g._chevron_anim is not None
    assert g._chevron_anim.endValue() == 90.0


def test_elevated_control_palette_differs_from_block_fill(qapp):
    """The palette helper returns control colors that won't collide with the
    section block fill in either theme. Dark mode is the screenshot bug we
    were fixing: block fill #333333 must NOT equal the control bg."""
    from tabs.settings_tab import _elevated_control_palette
    from utils.theme_manager import get_theme_colors

    # Dark mode: block is hardcoded #333333 in _SectionBlock.paintEvent.
    p = _elevated_control_palette(get_theme_colors(is_dark=True), True)
    assert p["bg"].lower() != "#333333"
    assert p["border"].lower() != "#333333"
    assert p["bg"].lower() != p["border"].lower()

    # Light mode: block is bg_card_inner. Border must not equal the bg
    # (the old border_muted token collided with btn_bg in light mode).
    c = get_theme_colors(is_dark=False)
    p = _elevated_control_palette(c, False)
    assert p["bg"].lower() != c["bg_card_inner"].lower()
    assert p["border"].lower() != p["bg"].lower()


def test_elevated_control_hover_is_tonal_not_accent(qapp):
    """Hover for tertiary controls inside a section block must be a tonal
    step off the resting surface, not a brand-color swap. Catches a
    regression where Browse / Auto-detect hovered to bright accent_blue."""
    from tabs.settings_tab import _elevated_control_palette
    from utils.theme_manager import get_theme_colors

    for is_dark in (True, False):
        c = get_theme_colors(is_dark=is_dark)
        p = _elevated_control_palette(c, is_dark)
        # Hover must differ from resting (state distinct) but stay distinct
        # from the saturated accent surfaces.
        assert p["hover_bg"].lower() != p["bg"].lower()
        assert p["hover_bg"].lower() != c["accent_blue"].lower()
        assert p["hover_bg"].lower() != c["accent_blue_btn"].lower()


def test_dropdown_row_has_tonal_hover(qapp):
    """DropdownRow's QComboBox declares a :hover rule using the same tonal
    palette as buttons — keeps controls in the section block feeling like
    one family rather than dropdowns being silently default-styled."""
    from tabs.settings_tab import DropdownRow, _elevated_control_palette
    from utils.theme_manager import get_theme_colors

    row = DropdownRow("Label", ["A", "B"])
    c = get_theme_colors(is_dark=True)
    row.apply_theme(c, True)
    style = row.combo.styleSheet().lower()
    p = _elevated_control_palette(c, True)
    assert "qcombobox:hover" in style
    assert p["hover_bg"].lower() in style
    assert p["hover_border"].lower() in style
    # Hover stays on-style — no accent reveal here either.
    assert c["accent_blue"].lower() not in style


def test_button_row_hover_does_not_use_accent_blue_dark(qapp):
    """Resolved ButtonRow stylesheet in dark mode must not contain the
    bright accent_blue token — it's reserved for primary CTAs, not Browse
    / Auto-detect / Clear-style utility actions."""
    from tabs.settings_tab import ButtonRow
    from utils.theme_manager import get_theme_colors

    row = ButtonRow("Action", "", button_text="Go", destructive=False)
    c = get_theme_colors(is_dark=True)
    row.apply_theme(c, True)
    style = row.button.styleSheet().lower()
    assert c["accent_blue"].lower() not in style


def test_game_path_row_hover_does_not_use_accent_blue_dark(qapp, tmp_path, monkeypatch):
    """Browse / Auto-detect buttons must not hover to the accent surface."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    from tabs.settings_tab import GamePathRow
    from utils.theme_manager import get_theme_colors

    sm = SettingsManager()
    row = GamePathRow(
        settings_manager=sm,
        settings_key="ttr_engine_dir",
        exe_name_fn=lambda: "TTREngine",
        find_path_fn=lambda: None,
        label="Toontown Rewritten",
    )
    c = get_theme_colors(is_dark=True)
    row.apply_theme(c, True)
    for btn_style in (row.browse_btn.styleSheet().lower(),
                      row.detect_btn.styleSheet().lower()):
        assert c["accent_blue"].lower() not in btn_style


def test_dropdown_row_combo_bg_distinct_from_block_dark(qapp):
    """DropdownRow's QComboBox must not paint at the same color as the
    section block surface in dark mode."""
    from tabs.settings_tab import DropdownRow
    from utils.theme_manager import get_theme_colors

    row = DropdownRow("Label", ["A", "B"])
    row.apply_theme(get_theme_colors(is_dark=True), True)
    style = row.combo.styleSheet().lower()
    # Block fill is #333333; the combo's resting background must differ.
    assert "background: #333333" not in style
    assert "background-color: #333333" not in style


def test_button_row_button_bg_distinct_from_block_dark(qapp):
    """Non-destructive ButtonRow must not paint at the same color as the
    section block surface in dark mode."""
    from tabs.settings_tab import ButtonRow
    from utils.theme_manager import get_theme_colors

    row = ButtonRow("Action", "", button_text="Go", destructive=False)
    row.apply_theme(get_theme_colors(is_dark=True), True)
    style = row.button.styleSheet().lower()
    assert "background-color: #333333" not in style


def test_game_path_row_buttons_bg_distinct_from_block_dark(qapp, tmp_path, monkeypatch):
    """Browse/Auto-detect on a GamePathRow must not paint at the section
    block color in dark mode — the screenshot regression."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from utils.settings_manager import SettingsManager
    from tabs.settings_tab import GamePathRow
    from utils.theme_manager import get_theme_colors

    sm = SettingsManager()
    row = GamePathRow(
        settings_manager=sm,
        settings_key="ttr_engine_dir",
        exe_name_fn=lambda: "TTREngine",
        find_path_fn=lambda: None,
        label="Toontown Rewritten",
    )
    row.apply_theme(get_theme_colors(is_dark=True), True)
    for btn_style in (row.browse_btn.styleSheet().lower(),
                      row.detect_btn.styleSheet().lower()):
        assert "background-color: #333333" not in btn_style


def test_chevron_snaps_with_reduced_motion(qapp, monkeypatch):
    """With reduce_motion on, toggle sets chevron rotation directly."""
    from tabs.settings_tab import CollapsibleSettingsGroup, SettingsRow
    import utils.motion as motion

    class _FakeSM:
        def __init__(self):
            self.data = {"advanced_collapsed": True, "reduce_motion_set_explicitly": True, "reduce_motion": True}
        def get(self, k, d=None): return self.data.get(k, d)
        def set(self, k, v): self.data[k] = v
        def on_change(self, cb): pass

    sm = _FakeSM()
    motion.set_settings_manager(sm)
    g = CollapsibleSettingsGroup("Advanced", sm, "advanced_collapsed")
    g.add_row(SettingsRow("A", ""))
    g.toggle()
    # No animation should have been started.
    assert g._chevron_anim is None or g._chevron_anim.state() == 0
    assert g._header._chevron.rotation == 90.0
