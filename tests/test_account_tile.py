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
    """Hovering the tile brightens its background and accent border-top."""
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile(game="ttr", slot_index=0)
    qss = tile.styleSheet()
    assert "QFrame#account_tile:hover" in qss
    # Brighter background and brighter TTR accent border on hover.
    assert "#2e2e2e" in qss
    assert "#6aa4ee" in qss  # brightened TTR accent


def test_account_tile_has_hover_qss_cc(qapp):
    """CC tiles get the brightened orange accent and shared brighter background."""
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile(game="cc", slot_index=0)
    qss = tile.styleSheet()
    assert "QFrame#account_tile:hover" in qss
    assert "#2e2e2e" in qss
    assert "#f48748" in qss  # brightened CC accent


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
