"""Blocked credentials, advisory bars, empty rosters, deletions, theme."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from tabs.launch_tab import LaunchTab
from utils.rendition_poses import RenditionPoseFetcher
from utils.widgets.grandstand.card_shelf import CardShelf
from utils.widgets.grandstand.model import RosterEntry
from utils.widgets.grandstand.party import LaunchParty
from utils.widgets.grandstand.view import GrandstandView


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: None)
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: None)


def _entry(aid, toon="Flossbud", species="cat", game="ttr", dna="7400"):
    return RosterEntry(account_id=aid, game=game, label=f"L{aid}",
                       username=f"u{aid}", toon_name=toon, species=species,
                       dna=dna, accent="#4a8fe7", footer="Primary",
                       portrait_mode="render" if dna else "waiting",
                       state="idle", message="", raw_error="")


@pytest.fixture
def view(qapp):
    """Shown, deliberately. Task 7 shipped a blocked-mode test that passed
    vacuously because the widget was never shown — under a hidden parent every
    Qt child reports isVisible() == False, so the assertion was already true
    before the code under test ran. Any test here that asserts isVisible()
    needs a real baseline."""
    v = GrandstandView(LaunchParty(None))
    v.resize(880, 688)
    v.show()
    qapp.processEvents()
    yield v
    v.close()
    v.deleteLater()
    qapp.processEvents()


# ── credentials (spec Q6) ───────────────────────────────────────────────────

def test_blocked_credentials_take_over_the_hero(view):
    view.set_accounts("ttr", [_entry("a")])
    assert view.hero.play_button.isVisible() is True      # real baseline
    view.set_credential_state("blocked", "Your keychain is locked.",
                              "Unlock accounts", lambda: None)
    assert view.hero.is_blocked() is True
    assert view.hero.play_button.isVisible() is False


def test_a_blocked_launcher_cannot_dispatch(view):
    view.set_accounts("ttr", [_entry("a")])
    view.shelf.card_for("a").clicked.emit("a")
    view.set_credential_state("blocked", "locked", "Unlock", lambda: None)
    seen = []
    view.party_launch_requested.connect(lambda g, ids: seen.append(ids))
    view.hero.play_button.click()
    assert seen == []


@pytest.mark.parametrize("signal_name", ["launch_clicked", "retry_clicked"])
def test_blocked_credentials_prevent_card_launch_paths(view, signal_name):
    view.set_accounts("ttr", [_entry("a")])
    view.set_credential_state("blocked", "locked", "Unlock", lambda: None)
    seen = []
    view.launch_requested.connect(lambda g, aid: seen.append(("launch", g, aid)))
    view.retry_requested.connect(lambda g, aid: seen.append(("retry", g, aid)))
    getattr(view.shelf, signal_name).emit("a")
    assert seen == []


def test_clearing_a_block_restores_card_launch(view):
    view.set_accounts("ttr", [_entry("a")])
    view.set_credential_state("blocked", "locked", "Unlock", lambda: None)
    view.set_credential_state("ok")
    seen = []
    view.launch_requested.connect(lambda g, aid: seen.append((g, aid)))
    view.shelf.launch_clicked.emit("a")
    assert seen == [("ttr", "a")]


def test_advisory_credentials_use_the_strip_not_the_hero(view):
    view.set_credential_state("advisory", "Passwords will not be saved.")
    assert view.advisory.isVisibleTo(view) is True
    assert view.hero.is_blocked() is False
    assert view.hero.play_button.isVisible() is True


def test_ok_hides_both(view):
    view.set_credential_state("advisory", "x")
    view.set_credential_state("ok", "")
    assert view.advisory.isVisibleTo(view) is False
    assert view.hero.is_blocked() is False


def test_the_stack_still_fits_with_the_advisory_strip_showing(view, qapp):
    """The strip adds a band to a stack that must never scroll. `or
    view.height() <= 688` would make this unfailable — the fixture resized to
    exactly 688 — so assert the only thing that carries information."""
    view.set_credential_state("advisory", "Passwords will not be saved.")
    qapp.processEvents()
    assert view.sizeHint().height() <= 688


# ── empty states (spec §7) ──────────────────────────────────────────────────

def test_no_accounts_leaves_only_the_add_tile(view):
    view.set_accounts("ttr", [])
    assert view.shelf.cards() == []
    assert view.shelf.add_tile.isVisibleTo(view.shelf)


def test_card_shelf_set_empty_clears_cards_and_keeps_the_add_tile(qapp):
    shelf = CardShelf()
    shelf.set_entries([_entry("a")])
    shelf.set_empty(True)
    assert shelf.cards() == []
    assert shelf.add_tile.isVisibleTo(shelf)


def test_no_accounts_disables_play_with_the_invitation(view):
    view.set_accounts("ttr", [])
    assert view.hero.play_label() == "SELECT A TOON"
    assert view.hero.play_enabled() is False
    assert "Choose one or more toons" in view.hero.names_text()


def test_populated_active_game_can_transition_to_empty(view):
    view.set_accounts("ttr", [_entry("a")])
    view.shelf.card_for("a").clicked.emit("a")
    assert view.hero.play_enabled() is True

    view.party().prune("ttr", set())
    view.set_accounts("ttr", [])

    assert view.shelf.cards() == []
    assert view.shelf.add_tile.isVisibleTo(view.shelf)
    assert view.hero.play_enabled() is False
    assert view.hero.play_label() == "SELECT A TOON"
    assert view.hero.crew_area.slots() == []


def test_each_game_keeps_its_own_emptiness(view):
    view.set_accounts("ttr", [_entry("a")])
    view.set_accounts("cc", [])
    view.selector.game_clicked.emit("cc")
    assert view.shelf.cards() == []
    view.selector.game_clicked.emit("ttr")
    assert [c.account_id() for c in view.shelf.cards()] == ["a"]


# ── deletion (spec §7) ──────────────────────────────────────────────────────

def test_deleting_a_selected_account_prunes_the_party(view):
    view.set_accounts("ttr", [_entry("a"), _entry("b")])
    view.shelf.card_for("a").clicked.emit("a")
    view.shelf.card_for("b").clicked.emit("b")
    view.party().prune("ttr", {"b"})
    view.set_accounts("ttr", [_entry("b")])
    assert view.party().selected("ttr") == ["b"]
    assert view.hero.play_label() == "PLAY 1 TOON"


def test_deleting_the_starred_account_reverts_the_greeting(view):
    view.set_accounts("ttr", [_entry("a")])
    view.set_main_toon_names("ttr", {"a": "Flossbud"})
    view.shelf.card_for("a").star_clicked.emit("a")
    view.party().prune("ttr", set())
    view.set_accounts("ttr", [])
    assert view.party().star("ttr") is None
    assert view.hero.greeting_text() == "Welcome back!"


def test_launch_tab_delete_prunes_the_mounted_party(monkeypatch, qapp):
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    accounts = [
        SimpleNamespace(id=aid, game="ttr", label=aid, username=aid,
                        password="pw", launcher_token="")
        for aid in ("a", "b")
    ]
    cred = MagicMock(keyring_available=True, keyring_probe_pending=False)
    cred.get_accounts_metadata.side_effect = lambda: list(accounts)
    cred.get_account_metadata.side_effect = lambda index: accounts[index]

    def delete_account(index):
        removed = accounts.pop(index)
        return removed.id, ""

    cred.delete_account.side_effect = delete_account
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)

    class AcceptDialog:
        DialogCode = SimpleNamespace(Accepted=1)

        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return self.DialogCode.Accepted

    import tabs.launch_tab as launch_tab
    monkeypatch.setattr(launch_tab, "ConfirmDialog", AcceptDialog)
    try:
        tab.grandstand.shelf.card_for("a").clicked.emit("a")
        tab.grandstand.shelf.card_for("b").clicked.emit("b")
        tab.grandstand.shelf.card_for("a").star_clicked.emit("a")

        tab._on_delete("ttr", "a")

        assert tab._party.selected("ttr") == ["b"]
        assert tab._party.star("ttr") is None
    finally:
        tab.shutdown()
        tab.close()


# ── degraded art (spec §7) ──────────────────────────────────────────────────

def test_an_account_with_no_dna_still_paints(view, qapp):
    view.set_accounts("ttr", [_entry("a", toon=None, dna="")])
    view.show()
    qapp.processEvents()
    view.shelf.card_for("a").repaint()      # silhouette path, must not raise


def test_a_toonless_account_does_not_break_the_stage(view):
    view.set_accounts("ttr", [_entry("a", toon=None, dna="")])
    view.shelf.card_for("a").clicked.emit("a")
    assert len(view.hero.crew_area.slots()) == 1
    assert view.hero.crew_area.slots()[0].treatment == "placeholder"


# ── theme ───────────────────────────────────────────────────────────────────

def test_theme_switch_reaches_every_surface(view, monkeypatch):
    from utils.widgets.grandstand import palette as gp

    view.set_accounts("ttr", [_entry("a")])
    surfaces = [view.selector, view.hero, view.hero.crew_area, view.shelf,
                view.shelf.card_for("a")]
    for surface in surfaces:
        surface.apply_theme = MagicMock(wraps=surface.apply_theme)
    advisory_palette = MagicMock(wraps=gp.advisory_strip)
    monkeypatch.setattr(gp, "advisory_strip", advisory_palette)

    view.apply_theme(False)
    view.apply_theme(True)                  # must not raise on either branch

    for surface in surfaces:
        assert [args[0] for args, _kwargs in surface.apply_theme.call_args_list] == [
            False, True]
    assert [args[0] for args, _kwargs in advisory_palette.call_args_list] == [
        False, True]


def test_launch_tab_theme_switch_reaches_grandstand(monkeypatch, qapp):
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    cred = MagicMock(keyring_available=True, keyring_probe_pending=False)
    cred.get_accounts_metadata.return_value = []
    settings = MagicMock()
    settings.get.side_effect = (
        lambda key, default=None: "dark" if key == "theme" else default)
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        tab.grandstand.apply_theme = MagicMock()
        tab.refresh_theme()
        tab.grandstand.apply_theme.assert_called_once_with(True)
    finally:
        tab.shutdown()
        tab.close()


@pytest.mark.parametrize(
    "pending,available,reason",
    [
        (True, False, "Checking your keyring…"),
        (False, False,
         "No keyring available — passwords will not be saved."),
    ],
)
def test_grandstand_uses_advisory_instead_of_legacy_banner(
        monkeypatch, qapp, pending, available, reason):
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    cred = MagicMock(keyring_available=available, keyring_probe_pending=pending)
    cred.get_accounts_metadata.return_value = []
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        assert tab._keyring_banner is None
        assert tab.grandstand.advisory_label.text() == reason
        assert tab.grandstand.advisory.isVisibleTo(tab.grandstand)
        assert tab.grandstand.hero.is_blocked() is False
    finally:
        tab.shutdown()
        tab.close()


def test_grandstand_locked_vault_blocks_without_a_legacy_banner(
        monkeypatch, qapp):
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    cred = MagicMock(keyring_available=False, keyring_probe_pending=True,
                     macos_unlock_state="denied")
    cred.get_accounts_metadata.return_value = []
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        assert tab._keyring_banner is None
        assert tab.grandstand.hero.is_blocked() is True
        assert tab.grandstand.hero.blocked_text() == (
            "Your macOS keychain is locked, so no account can launch.")
        assert tab.grandstand.hero.blocked_button.text() == "Unlock accounts"
    finally:
        tab.shutdown()
        tab.close()
