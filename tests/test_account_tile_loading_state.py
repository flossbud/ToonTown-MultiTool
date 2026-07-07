"""AccountTile loading state: spinner + 'Loading…' + active Quit."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_loading_shows_pill_and_quit(qapp):
    # v2 reskin: the loading state shows the inline status pill with the
    # "Loading…" label and an active Quit button (the old spinner chrome was
    # dropped; the pill carries the state instead).
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile("cc", 0)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("loading", "")
    assert tile.status_pill.isVisibleTo(tile)
    assert tile.status_label.text() == "Loading…"
    assert not tile.status_dot.isVisible()  # green pulse dot is running-only
    assert tile.primary_button.text() == "Quit"
    assert tile.primary_button.isEnabled()
    tile.deleteLater()


def test_loading_to_running_shows_pulse_dot(qapp):
    # The green pulse dot is running-only: hidden during loading, shown once
    # the game is running.
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile("cc", 0)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("loading", "")
    assert not tile.status_dot.isVisible()
    tile.set_state("running", "Game running")
    assert tile.status_dot.isVisible()
    tile.deleteLater()
