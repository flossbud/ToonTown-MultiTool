"""AccountTile widget unit tests. Game-agnostic; takes 'ttr' or 'cc'."""
import pytest
from PySide6.QtWidgets import QApplication
from utils.widgets.account_tile import AccountTile


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_idle_shows_launch(qapp):
    tile = AccountTile(game="ttr", slot_index=0)
    tile.show()  # required for isVisible to mean anything
    tile.set_account("PinkPirate", "pink@example", 0)
    tile.set_state("idle")
    assert tile.primary_button.text() == "Launch"
    assert tile.primary_button.isEnabled()
    assert not tile.status_band.isVisible()


def test_logging_in_disables_button_shows_band(qapp):
    tile = AccountTile(game="ttr", slot_index=0)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("logging_in", "Reaching server...")
    assert tile.primary_button.text() == "Logging in…"
    assert not tile.primary_button.isEnabled()
    assert tile.status_band.isVisible()


def test_running_shows_quit(qapp):
    tile = AccountTile(game="ttr", slot_index=0)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("running")
    assert tile.primary_button.text() == "Quit"
    assert tile.primary_button.isEnabled()


def test_failed_shows_retry_and_band(qapp):
    tile = AccountTile(game="ttr", slot_index=0)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("failed", "Bad credentials")
    assert tile.primary_button.text() == "Retry"
    assert tile.status_band.isVisible()


def test_queued_shows_cancel(qapp):
    tile = AccountTile(game="ttr", slot_index=0)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("queued", "pos 5")
    assert tile.primary_button.text() == "Cancel"


def test_need_2fa_shows_enter_2fa(qapp):
    tile = AccountTile(game="cc", slot_index=1)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("need_2fa")
    assert "2FA" in tile.primary_button.text()


def test_failed_preserves_raw_message_for_expand(qapp):
    raw = "TTR API HTTP 401: {'success': 'false', 'banner': 'Bad creds'}"
    tile = AccountTile(game="ttr", slot_index=0)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("failed", "Bad credentials", raw_message=raw)
    assert tile.raw_error_message == raw


def test_summarize_long_error_shortens_for_band(qapp):
    tile = AccountTile(game="ttr", slot_index=0)
    tile.show()  # required for isVisible to mean anything
    long = "Some really long traceback that does not fit in the band at all"
    tile.set_state("failed", long)
    # Band shows curated summary; raw kept for modal.
    assert tile.status_band.isVisible()


from utils.widgets.account_tile import summarize_error


def test_summarize_error_empty_returns_failed():
    assert summarize_error("") == "Failed"


def test_summarize_error_401_routes_to_bad_credentials():
    assert summarize_error("HTTP 401 Unauthorized") == "Bad credentials"
    assert summarize_error("bad creds in the response") == "Bad credentials"
    assert summarize_error("Incorrect username or password") == "Bad credentials"


def test_summarize_error_network_routes():
    assert summarize_error("Network unreachable") == "Network error"
    assert summarize_error("Connection refused") == "Network error"
    assert summarize_error("Request timeout") == "Network error"


def test_summarize_error_queue_timeout_takes_precedence():
    # "queue" + "timeout" must route to "Queue timed out", not "Network error".
    assert summarize_error("Queue timed out after 10 minutes") == "Queue timed out"


def test_summarize_error_engine_not_found_routes():
    assert summarize_error("Engine not found at ~/foo") == "Engine not found"
    assert summarize_error("TTREngine missing") == "Engine not found"


def test_summarize_error_runtime_routes():
    assert summarize_error("Wine prefix locked") == "Runtime error"
    assert summarize_error("Proton dispatch failed") == "Runtime error"
    assert summarize_error("umu-run exited 1") == "Runtime error"


def test_summarize_error_not_installed_routes_to_runtime_missing():
    """Bottles flatpak / Steam / Lutris 'X not installed' stderr should
    map to 'Runtime missing' on the band. Reported in the wild as
    'error: app/com.usebottles.bottles/x86_64/master not installed' when
    the user has only the host-native Bottles but TTMT tries flatpak."""
    assert summarize_error(
        "error: app/com.usebottles.bottles/x86_64/master not installed"
    ) == "Runtime missing"
    assert summarize_error("Proton runtime is not installed") == "Runtime missing"


def test_summarize_error_exact_32_chars_no_truncation():
    msg = "x" * 32
    assert summarize_error(msg) == msg


def test_summarize_error_33_chars_truncates_with_ellipsis():
    msg = "x" * 33
    result = summarize_error(msg)
    # 32 chars + the ellipsis character.
    assert result == ("x" * 32 + "…")
    assert len(result) == 33  # 32 x's + 1 ellipsis char


def test_summarize_error_unmatched_short_message_returned_as_is():
    assert summarize_error("Some plain error") == "Some plain error"


def test_account_tile_has_hover_qss(qapp):
    """Hovering the tile lifts background from bg_card_inner to
    bg_card_inner_hover. No more accent border-top brightening."""
    from utils.theme_manager import get_theme_colors
    tile = AccountTile(game="ttr", slot_index=0)
    qss = tile.styleSheet()
    c = get_theme_colors(True)
    assert "QFrame#account_tile:hover" in qss
    # Structural guard: in dark mode bg_card_inner_hover happens to equal
    # border_card (#363636), so a substring match on the color alone is
    # satisfied by the border rule. Assert the :hover BLOCK exists so a
    # refactor that accidentally drops the hover rule can't pass this test.
    hover_block_start = qss.find("QFrame#account_tile:hover")
    assert hover_block_start != -1
    hover_block = qss[hover_block_start:]
    assert c["bg_card_inner_hover"] in hover_block, \
        "bg_card_inner_hover token must appear inside the :hover block, not just in border"
    # Regression guard: no per-game border-top accent line.
    assert "border-top: 3px" not in qss
    assert "border-top: 4px" not in qss


def test_account_tile_has_hover_qss_cc(qapp):
    """CC tiles share the same neutral hover; identity carried by section
    card stripe, not by per-tile accent."""
    from utils.theme_manager import get_theme_colors
    tile = AccountTile(game="cc", slot_index=0)
    qss = tile.styleSheet()
    c = get_theme_colors(True)
    assert "QFrame#account_tile:hover" in qss
    # Structural guard: in dark mode bg_card_inner_hover happens to equal
    # border_card (#363636), so a substring match on the color alone is
    # satisfied by the border rule. Assert the :hover BLOCK exists so a
    # refactor that accidentally drops the hover rule can't pass this test.
    hover_block_start = qss.find("QFrame#account_tile:hover")
    assert hover_block_start != -1
    hover_block = qss[hover_block_start:]
    assert c["bg_card_inner_hover"] in hover_block, \
        "bg_card_inner_hover token must appear inside the :hover block, not just in border"
    assert "border-top: 3px" not in qss


def test_slot_badge_uses_game_pill_color(qapp):
    """Slot index badge uses the game pill token (same color as the section
    card top stripe) so identity-source colors stay in lockstep."""
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    ttr_tile = AccountTile(game="ttr", slot_index=0)
    assert c["game_pill_ttr"].lower() in ttr_tile.badge.styleSheet().lower()
    cc_tile = AccountTile(game="cc", slot_index=0)
    assert c["game_pill_cc"].lower() in cc_tile.badge.styleSheet().lower()


def test_account_tile_apply_theme_rebuilds_qss(qapp):
    """apply_theme(light) must swap the tile to light-mode tokens."""
    from utils.theme_manager import get_theme_colors
    tile = AccountTile(game="ttr", slot_index=0)
    light = get_theme_colors(False)
    tile.apply_theme(light)
    qss = tile.styleSheet()
    assert light["bg_card_inner"] in qss
    assert light["bg_card_inner_hover"] in qss
    dark = get_theme_colors(True)
    if dark["bg_card_inner"] != light["bg_card_inner"]:
        assert dark["bg_card_inner"] not in qss


def test_account_tile_press_drives_paint_scale(qapp):
    """Pressing the tile flips _is_pressed and targets PRESS_SCALE.
    Mirrors tests/test_chip_rail.py::test_chip_press_drives_chipbutton_paint_scale."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from utils.widgets.account_tile import AccountTile

    tile = AccountTile(game="ttr", slot_index=0)
    assert tile._is_pressed is False
    assert tile._target_scale() == AccountTile.NORMAL_SCALE

    press = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(5, 5),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    tile.mousePressEvent(press)
    assert tile._is_pressed is True
    assert tile._target_scale() == AccountTile.PRESS_SCALE

    release = QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(5, 5),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
    )
    tile.mouseReleaseEvent(release)
    assert tile._is_pressed is False
    assert tile._target_scale() == AccountTile.NORMAL_SCALE


def test_account_tile_paint_scale_property_exists(qapp):
    """paint_scale is a writable Qt Property for QPropertyAnimation."""
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile(game="ttr", slot_index=0)
    assert tile.paint_scale == 1.0
    tile.paint_scale = 0.96
    assert tile.paint_scale == 0.96


def test_account_tile_leave_while_pressed_resets_state(qapp):
    """Press then drag out: leaveEvent must reset _is_pressed so the tile
    does not stick at PRESS_SCALE when the release happens outside bounds."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from utils.widgets.account_tile import AccountTile

    tile = AccountTile(game="ttr", slot_index=0)
    press = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(5, 5),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    tile.mousePressEvent(press)
    assert tile._is_pressed is True

    leave = QEvent(QEvent.Leave)
    tile.leaveEvent(leave)
    assert tile._is_pressed is False
    assert tile._target_scale() == AccountTile.NORMAL_SCALE


def test_account_tile_opacity_property(qapp):
    """tile_opacity is an animatable Qt Property defaulting to 1.0."""
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile(game="ttr", slot_index=0)
    assert tile.tile_opacity == 1.0
    tile.tile_opacity = 0.5
    assert tile.tile_opacity == 0.5


def test_in_tile_buttons_are_chipbuttons(qapp):
    """primary_button, edit_btn, delete_btn are ChipButton instances so
    they participate in the app-wide press-scale animation pattern."""
    from utils.widgets.account_tile import AccountTile
    from utils.widgets.chip_button import ChipButton
    tile = AccountTile(game="ttr", slot_index=0)
    assert isinstance(tile.primary_button, ChipButton)
    assert isinstance(tile.edit_btn, ChipButton)
    assert isinstance(tile.delete_btn, ChipButton)


def test_in_tile_primary_button_press_targets_quiet_press_scale(qapp):
    """Pressing the Launch button flips its ChipButton _is_pressed state and
    targets the gentler 0.96 press scale (not ChipButton's default 0.88)."""
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile(game="ttr", slot_index=0)
    btn = tile.primary_button
    assert btn._is_pressed is False
    btn.pressed.emit()
    assert btn._is_pressed is True
    assert btn._target_scale() == 0.96
    btn.released.emit()
    assert btn._is_pressed is False


def test_in_tile_buttons_have_no_hover_upscale(qapp):
    """Hover does NOT upscale these buttons (option B: no movement on hover)."""
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile(game="ttr", slot_index=0)
    assert tile.primary_button.HOVER_SCALE == 1.0
    assert tile.edit_btn.HOVER_SCALE == 1.0
    assert tile.delete_btn.HOVER_SCALE == 1.0


def test_status_band_running_uses_success_tokens(qapp):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    tile = AccountTile(game="ttr", slot_index=0)
    tile.set_state("running")
    band_qss = tile.status_band.styleSheet()
    assert c["status_success_bg"] in band_qss
    assert c["status_success_text"] in band_qss


def test_status_band_queued_uses_warning_tokens(qapp):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    tile = AccountTile(game="ttr", slot_index=0)
    tile.set_state("queued", "pos 5")
    band_qss = tile.status_band.styleSheet()
    assert c["status_warning_bg"] in band_qss
    assert c["status_warning_text"] in band_qss


def test_status_band_failed_uses_error_tokens(qapp):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    tile = AccountTile(game="ttr", slot_index=0)
    tile.set_state("failed", "Bad credentials")
    band_qss = tile.status_band.styleSheet()
    assert c["status_error_bg"] in band_qss
    assert c["status_error_text"] in band_qss


def test_status_band_need_2fa_uses_info_tokens(qapp):
    from utils.theme_manager import get_theme_colors
    c = get_theme_colors(True)
    tile = AccountTile(game="cc", slot_index=1)
    tile.set_state("need_2fa")
    band_qss = tile.status_band.styleSheet()
    assert c["status_info_bg"] in band_qss
    assert c["status_info_text"] in band_qss


def test_status_band_rethemes_on_apply_theme(qapp):
    """End-to-end re-theming: a tile in 'running' state must update its
    band QSS to light-mode tokens when apply_theme(light) is called.

    Verifies the _current_state cache + _refresh_status_band -> set_state
    re-call chain that exists specifically for theme switches."""
    from utils.theme_manager import get_theme_colors
    light = get_theme_colors(False)
    dark = get_theme_colors(True)
    tile = AccountTile(game="ttr", slot_index=0)
    tile.set_state("running")
    # Sanity: starts in dark.
    assert dark["status_success_bg"] in tile.status_band.styleSheet()
    # Switch theme.
    tile.apply_theme(light)
    band_qss = tile.status_band.styleSheet()
    assert light["status_success_bg"] in band_qss
    assert light["status_success_text"] in band_qss
    # Dark values must no longer appear (if they differ).
    if dark["status_success_bg"] != light["status_success_bg"]:
        assert dark["status_success_bg"] not in band_qss
