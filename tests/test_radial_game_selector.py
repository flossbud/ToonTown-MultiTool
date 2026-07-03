"""Radial game-selector sub-ring: Accounts -> (TTR | CC) -> that game's ring.

Widget-level state machine + main-model plumbing (launch_tab game filter).
Anim kill switch keeps activation deterministic offscreen.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from utils.overlay.radial_menu import RadialMenuWidget, _game_logo
from utils.radial_menu_model import RingAccount


@pytest.fixture(autouse=True)
def _no_anim(monkeypatch):
    monkeypatch.setenv("TTMT_NO_RADIAL_ANIM", "1")


def _menu(qapp):
    m = RadialMenuWidget(184.0)
    m.resize(1092, 1092)
    return m


def _acct(aid="a1", game="ttr"):
    return RingAccount(account_id=aid, game=game, label=aid,
                       toon_name=None, dna="", running=False)


def _click(menu, state, key):
    x, y, _r = menu.circle_geometry(state, key)
    menu.activate_at(x, y)


def test_selector_state_circles_and_reveal_order(qapp):
    m = _menu(qapp)
    states = []
    m.state_changed.connect(lambda: states.append(m.state))
    m.set_game_selector(["ttr", "cc"])
    assert m.state == "games"
    assert states == ["games"]
    circles = m._visible_circles()
    assert [(s, k) for s, k, *_ in circles] == [
        ("games", "back"), ("games", 0), ("games", 1)]
    assert set(m.reveal_order("games")) == {"back", 0, 1}


def test_game_click_emits_game_selected(qapp):
    m = _menu(qapp)
    m.set_game_selector(["ttr", "cc"])
    picked = []
    m.game_selected.connect(picked.append)
    _click(m, "games", 1)
    assert picked == ["cc"]
    assert m.state == "games"          # state swaps only when the ring arrives


def test_back_from_selector_returns_to_main(qapp):
    m = _menu(qapp)
    m.set_game_selector(["ttr", "cc"])
    _click(m, "games", "back")
    assert m.state == "main"


def test_back_from_via_games_ring_returns_to_selector(qapp):
    m = _menu(qapp)
    m.set_game_selector(["ttr", "cc"])
    m.set_accounts([_acct()], via_games=True)
    assert m.state == "accounts"
    _click(m, "accounts", "back")
    assert m.state == "games"
    assert [(s, k) for s, k, *_ in m._visible_circles()] == [
        ("games", "back"), ("games", 0), ("games", 1)]


def test_back_from_direct_ring_returns_to_main(qapp):
    m = _menu(qapp)
    m.set_accounts([_acct()])           # single-game flow: no selector
    _click(m, "accounts", "back")
    assert m.state == "main"


def test_interactive_path_covers_selector_spokes(qapp):
    from PySide6.QtCore import QPointF
    m = _menu(qapp)
    m.set_game_selector(["ttr", "cc"])
    path = m.interactive_path()
    for key in ("back", 0, 1):
        x, y, _r = m.circle_geometry("games", key)
        assert path.contains(QPointF(x, y))


def test_game_logo_assets_resolve(qapp):
    assert _game_logo("ttr").isNull() is False
    assert _game_logo("cc").isNull() is False


# ---------------------------------------------------------------------------
# launch_tab plumbing: account_games + game-filtered ring model
# ---------------------------------------------------------------------------

def _launch_tab(basics):
    from tabs.launch_tab import LaunchTab
    cred = MagicMock()
    cred.keyring_available = True
    cred.keyring_probe_pending = False
    cred.get_accounts_metadata.return_value = [
        SimpleNamespace(id=aid, game=g, label=lbl, username=lbl,
                        password="pw", launcher_token="")
        for (aid, g, lbl) in basics]
    cred.get_accounts_basic.side_effect = lambda game=None: [
        t for t in basics if game is None or t[1] == game]
    sm = MagicMock()
    sm.get.return_value = None
    tab = LaunchTab(cred_manager=cred, settings_manager=sm)
    return tab


BASICS = [
    ("id-t1", "ttr", "flossbud"),
    ("id-t2", "ttr", "flossbud27"),
    ("id-c1", "cc", "flossbud27"),
]


def test_account_games_orders_and_dedupes(qapp):
    tab = _launch_tab(BASICS)
    assert tab.account_games() == ["ttr", "cc"]
    assert _launch_tab(BASICS[:2]).account_games() == ["ttr"]
    assert _launch_tab([]).account_games() == []


def test_ring_model_game_filter(qapp):
    tab = _launch_tab(BASICS)
    ttr_ring = tab.recent_account_ring_model(game="ttr")
    assert [a.account_id for a in ttr_ring] == ["id-t1", "id-t2"]
    assert all(a.game == "ttr" for a in ttr_ring)
    cc_ring = tab.recent_account_ring_model(game="cc")
    assert [a.account_id for a in cc_ring] == ["id-c1"]
    everything = tab.recent_account_ring_model()
    assert [a.account_id for a in everything] == ["id-t1", "id-t2", "id-c1"]
