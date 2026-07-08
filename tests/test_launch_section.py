"""LaunchSection: section header + 2-col grid of AccountTiles + empty state."""
import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.launch_section import LaunchSection


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_empty_section_shows_empty_state(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_accounts([])
    sec.show()  # required for isVisible to mean anything
    assert sec.empty_state is not None and sec.empty_state.isVisible()
    assert sec.add_tile is None or not sec.add_tile.isVisible()


def test_populated_section_shows_tiles_and_add_tile(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_accounts([{"label": "A", "username": "a@x"}, {"label": "B", "username": "b@x"}])
    sec.show()  # required for isVisible to mean anything
    assert len(sec.tiles) == 2
    assert sec.pager.add_btn.isVisible()
    assert not sec.empty_state.isVisible()


def test_section_header_has_title_and_launcher_btn(qapp):
    sec = LaunchSection(game="cc", icon_path="assets/cc.png")
    assert "Corporate Clash" in sec.title_label.text()
    assert "CC" in sec.launcher_btn.text() or "Launcher" in sec.launcher_btn.text()


def test_account_count_subline_updates(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_accounts([{"label": "A", "username": "a@x"}])
    assert "1" in sec.subline.text()
    sec.set_accounts([{"label": "A", "username": "a@x"}, {"label": "B", "username": "b@x"}])
    assert "2" in sec.subline.text()
    sec.set_accounts([])
    assert "No accounts" in sec.subline.text()


def test_launcher_btn_emits(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    captured = []
    sec.launcher_clicked.connect(lambda: captured.append("x"))
    sec.launcher_btn.click()
    assert captured == ["x"]


def test_add_tile_click_emits(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    sec.set_accounts([{"label": "A", "username": "a@x"}])
    captured = []
    sec.add_account_clicked.connect(lambda: captured.append("x"))
    sec.pager.add_btn.click()
    assert captured == ["x"]


def test_max_accounts_hides_add_tile(qapp):
    # at_ceiling=True is triggered when 16 accounts are present (the ceiling).
    # Use set_page directly so the test stays meaningful with the new pager.
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png")
    full = [{"label": f"A{i}", "username": f"u{i}", "id": f"id{i}"}
            for i in range(4)]
    sec.set_page(full, page=3, page_count=4, base_index=12,
                 activity=[False] * 4, show_empty_state=False, at_ceiling=True,
                 total_count=16)
    sec.show()  # required for isVisible to mean anything
    assert not sec.pager.add_btn.isVisible()


def test_section_uses_card_surface_ttr(qapp):
    """The section surface is now a CardSurface keyed to the game accent
    (replaces the hand-rolled flat card + 2px top stripe)."""
    from utils.widgets.card_surface import CardSurface
    sec = LaunchSection(game="ttr", icon_path="")
    assert isinstance(sec.card, CardSurface)
    assert sec.card.accent_key == "ttr"


def test_section_uses_card_surface_cc(qapp):
    from utils.widgets.card_surface import CardSurface
    sec = LaunchSection(game="cc", icon_path="")
    assert isinstance(sec.card, CardSurface)
    assert sec.card.accent_key == "cc"


def test_apply_theme_flips_card_polarity(qapp):
    """apply_theme(light_dict) must flip the CardSurface to its light path
    (the surface paints its gradient/border, so we assert the polarity flag
    the paint reads rather than a QSS string)."""
    from utils.theme_manager import get_theme_colors
    sec = LaunchSection(game="ttr", icon_path="")
    sec.apply_theme(get_theme_colors(True))
    assert sec.card._is_dark is True
    sec.apply_theme(get_theme_colors(False))
    assert sec.card._is_dark is False


def test_empty_state_lives_inside_card(qapp):
    """Empty state must be a descendant of the section card so it can't float
    outside the card bounds (the bug from the screenshot)."""
    sec = LaunchSection(game="cc", icon_path="")
    card = sec.card
    assert sec.empty_state is not None
    # Walk up the parent chain; we should pass through the card.
    parent = sec.empty_state.parentWidget()
    while parent is not None and parent is not card:
        parent = parent.parentWidget()
    assert parent is card, "empty_state must be a descendant of the section card"


def test_section_launcher_button_is_chipbutton(qapp):
    from utils.widgets.launch_section import LaunchSection
    from utils.widgets.chip_button import ChipButton
    sec = LaunchSection(game="ttr", icon_path="")
    assert isinstance(sec.launcher_btn, ChipButton)


def test_add_tile_is_chipbutton(qapp):
    """The pager's '+ Add Account' button inherits from ChipButton so pressing
    it runs the same paint_scale animation."""
    from utils.widgets.launch_section import LaunchSection
    from utils.widgets.chip_button import ChipButton
    sec = LaunchSection(game="ttr", icon_path="")
    sec.set_accounts([{"label": "x", "username": "y"}])
    assert isinstance(sec.pager.add_btn, ChipButton)


def test_section_has_compact_max_width(qapp):
    """Sections cap at 740px wide: a 720px VISIBLE card (MultiToon compact-card
    parity) plus CardSurface's 10px/side painted-shadow reserve, so two fixed
    336px tiles fit two-up without clipping."""
    from PySide6.QtWidgets import QSizePolicy
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    assert sec.maximumWidth() == 740
    assert sec.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding


def test_set_layout_mode_toggles_max_width(qapp):
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    assert sec.maximumWidth() == 740
    sec.set_layout_mode("full")
    assert sec.maximumWidth() == 860
    sec.set_layout_mode("compact")
    assert sec.maximumWidth() == 740


def test_set_layout_mode_unknown_is_noop(qapp):
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    before = sec.maximumWidth()
    sec.set_layout_mode("invalid")
    assert sec.maximumWidth() == before


def test_tiles_are_fixed_336x96(qapp):
    """Tiles are a fixed 336x96 (no content-scaling). A window resize must
    NOT change a tile's size - the old _content_scale path is gone."""
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    sec.set_accounts([{"label": "a", "username": "u"}])
    tile = sec.tile_at(0)
    assert tile.width() == 336
    assert tile.height() == 96
    sec.show()
    sec.set_layout_mode("full")
    sec.resize(860, sec.height())
    QApplication.processEvents()
    assert tile.width() == 336
    assert tile.height() == 96


def test_set_layout_mode_runs_reveal_animation(qapp, monkeypatch):
    """After set_layout_mode, every tile ends at opacity 1.0 once animations settle.
    With TTMT_TEST_DURATION_SCALE=0 the animation resolves in one event-loop tick."""
    import utils.motion as motion
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    sec.set_accounts([
        {"label": "a", "username": "u1"},
        {"label": "b", "username": "u2"},
    ])
    # Force opacity to 0 to prove the reveal pushes it back to 1.0.
    for tile in sec.tiles:
        tile.tile_opacity = 0.0
    sec.set_layout_mode("full")
    qapp.processEvents()
    qapp.processEvents()  # pump again for staggered QTimer.singleShot starts
    for tile in sec.tiles:
        assert tile.tile_opacity == 1.0


def test_set_layout_mode_reduced_motion_snaps_opacity(qapp, monkeypatch):
    """With reduced motion, tiles snap to opacity 1.0 immediately."""
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    sec.set_accounts([{"label": "a", "username": "u"}])
    for tile in sec.tiles:
        tile.tile_opacity = 0.0
    sec.set_layout_mode("full")
    for tile in sec.tiles:
        assert tile.tile_opacity == 1.0


def test_set_layout_mode_same_mode_does_not_reflash(qapp):
    """Calling set_layout_mode with the current mode is a no-op — must not
    zero opacities and re-run the reveal."""
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    sec.set_accounts([{"label": "a", "username": "u"}])
    sec.set_layout_mode("full")
    for tile in sec.tiles:
        tile.tile_opacity = 1.0  # baseline
    # Same-mode call should not touch opacity at all.
    sec.set_layout_mode("full")
    for tile in sec.tiles:
        assert tile.tile_opacity == 1.0


def test_add_tile_uses_theme_tokens(qapp):
    """The pager's '+ Add Account' button is a game-accent filled pill (v2
    redesign - was a fixed blue), with white text."""
    from utils.theme_manager import V2_ACCENTS, get_theme_colors
    sec = LaunchSection(game="ttr", icon_path="")
    sec.set_accounts([{"label": "x", "username": "y"}])
    sec.apply_theme(get_theme_colors(True))
    qss = sec.pager.add_btn.styleSheet().lower()
    assert V2_ACCENTS["ttr"]["c"].lower() in qss
    assert "#ffffff" in qss


def test_add_tile_apply_theme_swaps_palettes(qapp):
    """LaunchSection.apply_theme must propagate to the pager's add button (which
    is a game-accent filled pill in the v2 redesign)."""
    from utils.theme_manager import V2_ACCENTS, get_theme_colors
    sec = LaunchSection(game="cc", icon_path="")
    sec.set_accounts([{"label": "x", "username": "y"}])
    sec.apply_theme(get_theme_colors(False))
    qss = sec.pager.add_btn.styleSheet().lower()
    assert V2_ACCENTS["cc"]["c"].lower() in qss
    assert "#ffffff" in qss
