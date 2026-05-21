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
