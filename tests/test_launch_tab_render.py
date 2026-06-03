import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from tabs.launch_tab import LaunchTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _meta(aid, game):
    return SimpleNamespace(id=aid, game=game, label=aid, username=aid,
                           password="pw", launcher_token="")


def _tab(qapp, accounts):
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = accounts
    sm = MagicMock(); sm.get.return_value = None
    return LaunchTab(cred_manager=cred, settings_manager=sm)


def test_five_accounts_show_two_pages_first_page_four_tiles(qapp):
    tab = _tab(qapp, [_meta(f"t{i}", "ttr") for i in range(5)])
    tab._build_ui()
    assert tab._page["ttr"] == 0
    assert len(tab.ttr_section.tiles) == 4
    assert tab.ttr_section.tiles[0].badge.text() == "1"


def test_flip_to_page_two_shows_remaining(qapp):
    tab = _tab(qapp, [_meta(f"t{i}", "ttr") for i in range(5)])
    tab._build_ui()
    tab._on_page_changed("ttr", 1)
    assert tab._page["ttr"] == 1
    assert len(tab.ttr_section.tiles) == 1
    assert tab.ttr_section.tiles[0].badge.text() == "5"


def test_four_accounts_reserve_landing_page(qapp):
    tab = _tab(qapp, [_meta(f"t{i}", "ttr") for i in range(4)])
    tab._build_ui()
    tab._on_page_changed("ttr", 1)
    assert tab.ttr_section.empty_page_hint.isVisible() or len(tab.ttr_section.tiles) == 0


def test_per_section_paging_is_independent(qapp):
    accounts = [_meta(f"t{i}", "ttr") for i in range(5)] + [_meta(f"c{i}", "cc") for i in range(5)]
    tab = _tab(qapp, accounts)
    tab._build_ui()
    tab._on_page_changed("ttr", 1)
    assert tab._page["ttr"] == 1
    assert tab._page["cc"] == 0  # CC page unaffected


def test_clamps_page_after_shrink(qapp):
    tab = _tab(qapp, [_meta(f"t{i}", "ttr") for i in range(8)])
    tab._build_ui()
    tab._on_page_changed("ttr", 2)  # page index 2 valid for 8 accts (3 pages)
    assert tab._page["ttr"] == 2
    tab.cred_manager.get_accounts_metadata.return_value = [_meta("t0", "ttr")]
    tab._build_ui()  # now 1 account -> 1 page; page clamps to 0
    assert tab._page["ttr"] == 0
