"""LaunchSection: section header + 2-col grid of AccountTiles + empty state."""
import pytest
from PySide6.QtWidgets import QApplication, QFrame
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
    assert sec.add_tile is not None and sec.add_tile.isVisible()
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
    sec.add_tile.click()
    assert captured == ["x"]


def test_max_accounts_hides_add_tile(qapp):
    sec = LaunchSection(game="ttr", icon_path="assets/ttr.png", max_accounts=2)
    sec.set_accounts([{"label": "A", "username": "a"}, {"label": "B", "username": "b"}])
    sec.show()  # required for isVisible to mean anything
    assert not sec.add_tile.isVisible()


def test_section_card_is_flat_with_ttr_top_stripe(qapp):
    """Section card is a flat bg_card surface with a 2 px coloured stripe
    along the top edge (replaces the gradient wash). TTR uses the
    game_pill_ttr violet."""
    from utils.theme_manager import get_theme_colors
    sec = LaunchSection(game="ttr", icon_path="")
    card = sec.findChild(QFrame, "section_card")
    assert card is not None
    qss = card.styleSheet()
    c = get_theme_colors(True)  # widget builds against dark by default

    # Regression guard: no gradient wash anywhere on the card.
    assert "qlineargradient" not in qss, "card must be flat, not a gradient"
    # Flat bg + hairline border + 2 px coloured top stripe.
    assert c["bg_card"] in qss
    assert c["border_card"] in qss
    assert "border-top: 2px" in qss
    assert c["game_pill_ttr"] in qss


def test_section_card_is_flat_with_cc_top_stripe(qapp):
    from utils.theme_manager import get_theme_colors
    sec = LaunchSection(game="cc", icon_path="")
    card = sec.findChild(QFrame, "section_card")
    assert card is not None
    qss = card.styleSheet()
    c = get_theme_colors(True)
    assert "qlineargradient" not in qss
    assert c["bg_card"] in qss
    assert c["border_card"] in qss
    assert "border-top: 2px" in qss
    assert c["game_pill_cc"] in qss


def test_section_header_keeps_hairline_divider(qapp):
    """Header still has the hairline below it, but the divider color now
    comes from the border_muted theme token (was a hardcoded rgba literal)."""
    from utils.theme_manager import get_theme_colors
    sec = LaunchSection(game="ttr", icon_path="")
    header_frame = sec.findChild(QFrame, "section_header")
    assert header_frame is not None
    qss = header_frame.styleSheet()
    assert "border-bottom" in qss
    # Header itself is transparent; the bottom divider is the only QSS rule.
    assert "qlineargradient" not in qss
    c = get_theme_colors(True)
    assert c["border_muted"] in qss


def test_apply_theme_rebuilds_card_qss(qapp):
    """apply_theme(light_dict) must swap the card QSS to use light tokens."""
    from utils.theme_manager import get_theme_colors
    sec = LaunchSection(game="ttr", icon_path="")
    light = get_theme_colors(False)
    sec.apply_theme(light)
    card = sec.findChild(QFrame, "section_card")
    qss = card.styleSheet()
    assert light["bg_card"] in qss
    assert light["border_card"] in qss
    # Dark bg_card (#252525) must no longer appear if it differs from light.
    dark = get_theme_colors(True)
    if dark["bg_card"] != light["bg_card"]:
        assert dark["bg_card"] not in qss


def test_empty_state_lives_inside_card(qapp):
    """Empty state must be a descendant of section_card so it can't float
    outside the card bounds (the bug from the screenshot)."""
    sec = LaunchSection(game="cc", icon_path="")
    card = sec.findChild(QFrame, "section_card")
    assert sec.empty_state is not None
    # Walk up the parent chain; we should pass through the card.
    parent = sec.empty_state.parentWidget()
    while parent is not None and parent is not card:
        parent = parent.parentWidget()
    assert parent is card, "empty_state must be a descendant of section_card"


def test_section_launcher_button_is_chipbutton(qapp):
    from utils.widgets.launch_section import LaunchSection
    from utils.widgets.chip_button import ChipButton
    sec = LaunchSection(game="ttr", icon_path="")
    assert isinstance(sec.launcher_btn, ChipButton)


def test_add_tile_is_chipbutton(qapp):
    """The '+ Add Account' tile inherits from ChipButton, so pressing it
    runs the same paint_scale animation."""
    from utils.widgets.launch_section import LaunchSection
    from utils.widgets.chip_button import ChipButton
    sec = LaunchSection(game="ttr", icon_path="")
    sec.set_accounts([{"label": "x", "username": "y"}])
    assert sec.add_tile is not None
    assert isinstance(sec.add_tile, ChipButton)


def test_section_has_compact_max_width(qapp):
    """Sections cap at 720px wide (MultiToon compact-card parity)."""
    from PySide6.QtWidgets import QSizePolicy
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    assert sec.maximumWidth() == 720
    assert sec.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding


def test_set_layout_mode_toggles_max_width(qapp):
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    assert sec.maximumWidth() == 720
    sec.set_layout_mode("full")
    assert sec.maximumWidth() == 860
    sec.set_layout_mode("compact")
    assert sec.maximumWidth() == 720


def test_set_layout_mode_unknown_is_noop(qapp):
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    before = sec.maximumWidth()
    sec.set_layout_mode("invalid")
    assert sec.maximumWidth() == before


def test_section_resize_scales_tile_minheight(qapp):
    """At wider widths, tile min-height grows proportionally (within clamps)."""
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    sec.set_accounts([{"label": "a", "username": "u"}])
    tile = sec.tile_at(0)
    base_h = tile.minimumHeight()
    # Full-mode reference is 720px; max-width is 860. Resize to 860 gives
    # scale=860/720~=1.19>1.0 (well within the 1.4 clamp). Widget must be
    # shown so that subsequent resize() calls trigger resizeEvent.
    sec.show()
    sec.set_layout_mode("full")
    sec.resize(860, sec.height())
    # After resize, the scale factor should be > 1.0, so min-height bumps.
    assert tile.minimumHeight() > base_h


def test_section_resize_scale_factor_clamped(qapp):
    """Resize-driven scale clamps at 1.4 even on absurdly wide screens."""
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    sec.show()
    sec.set_layout_mode("full")
    sec.resize(4000, sec.height())
    assert sec._content_scale <= 1.4
    assert sec._content_scale >= 1.0


def test_set_accounts_after_scale_applies_to_new_tiles(qapp):
    """If accounts are (re)loaded after a window resize has bumped scale
    above 1.0, the fresh tiles must inherit the current scaled min-height
    rather than the AccountTile default of 130."""
    from utils.widgets.launch_section import LaunchSection
    sec = LaunchSection(game="ttr", icon_path="")
    sec.show()
    sec.set_layout_mode("full")
    sec.resize(860, sec.height())  # bumps scale to ~1.19
    assert sec._content_scale > 1.0
    sec.set_accounts([{"label": "a", "username": "u"}])
    tile = sec.tile_at(0)
    assert tile.minimumHeight() == int(130 * sec._content_scale)
    # add_tile should also be scaled (it was excluded from the loop in
    # the original Task 11 implementation).
    assert sec.add_tile is not None
    assert sec.add_tile.minimumHeight() == int(130 * sec._content_scale)


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
