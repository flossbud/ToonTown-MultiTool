"""Tests for the Settings tab polish pass (2026-05-13)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_section_block_has_drop_shadow_after_apply_theme(qapp):
    """_SectionBlock attaches a QGraphicsDropShadowEffect on apply_theme."""
    from tabs.settings_tab import SettingsGroup
    from utils.theme_manager import get_theme_colors

    g = SettingsGroup("General")
    g.apply_theme(get_theme_colors(is_dark=True), True)

    effect = g._block.graphicsEffect()
    assert isinstance(effect, QGraphicsDropShadowEffect)
    # Soft, low offset — values match apply_card_shadow's defaults.
    assert effect.blurRadius() == 18
    assert effect.offset().y() == 4


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
