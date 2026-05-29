"""AccountTile loading state: spinner + 'Loading…' + active Quit."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_loading_shows_spinner_and_quit(qapp):
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile("cc", 0)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("loading", "")
    assert tile.status_band.isVisible()
    assert tile.status_label.text() == "Loading…"
    assert tile.status_spinner.isVisible()
    assert not tile.status_dot.isVisible()
    assert tile.primary_button.text() == "Quit"
    assert tile.primary_button.isEnabled()
    tile.deleteLater()


def test_loading_to_running_swaps_spinner_for_dot(qapp):
    from utils.widgets.account_tile import AccountTile
    tile = AccountTile("cc", 0)
    tile.show()  # required for isVisible to mean anything
    tile.set_state("loading", "")
    assert tile.status_spinner.isVisible()
    tile.set_state("running", "Game running")
    assert not tile.status_spinner.isVisible()
    assert tile.status_dot.isVisible()
    tile.deleteLater()
