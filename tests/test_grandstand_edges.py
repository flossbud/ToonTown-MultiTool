"""Blocked credentials, advisory bars, empty rosters, deletions, theme."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from tabs.launch_tab import LaunchTab
from utils.credential_copy import KEYRING_WARNING_COPY
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


def test_blocking_without_a_reason_still_blocks(view):
    """The safety property must not depend on the truthiness of display copy."""
    view.set_accounts("ttr", [_entry("a")])
    view.shelf.card_for("a").clicked.emit("a")
    view.set_credential_state("blocked")
    seen = []
    view.party_launch_requested.connect(lambda g, ids: seen.append(ids))
    view.hero.play_button.click()
    assert seen == []
    assert view.hero.play_button.isVisible() is False
    assert view.hero.blocked_text() == (
        "🔒  Your accounts are locked\n"
        "Unlock to load your saved accounts for this session.")


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


def test_blocked_credentials_hide_the_official_launcher_control(view):
    assert view.hero.official_button.isVisible() is True
    view.set_credential_state("blocked", "locked", "Unlock", lambda: None)
    assert view.hero.official_button.isVisible() is False
    view.set_credential_state("ok")
    assert view.hero.official_button.isVisible() is True


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


def test_the_advisory_strip_never_widens_the_view(view, qapp):
    """The host disables horizontal scrolling, so a strip that cannot shrink
    clips its own message instead of showing it."""
    view.resize(880, 688)
    qapp.processEvents()
    before = view.width()
    view.set_credential_state("advisory", "")
    qapp.processEvents()
    assert view.advisory.isVisibleTo(view) is True
    assert view.sizeHint().width() <= 880
    assert view.width() == before


def test_the_full_advisory_copy_is_still_reachable(view):
    view.set_credential_state("advisory", "")
    assert view.advisory_label.toolTip() == KEYRING_WARNING_COPY.body


def test_advisory_copy_elides_when_a_hidden_view_is_reshown(view, qapp):
    long_copy = "Passwords will not be remembered this session. " * 40
    view.set_credential_state("advisory", "Checking your keyring…")
    qapp.processEvents()
    view.hide()
    qapp.processEvents()
    view.set_credential_state("advisory", long_copy)
    view.show()
    qapp.processEvents()
    assert view.advisory_label.text().endswith("…")
    assert view.advisory_label.text() != long_copy
    assert view.advisory_label.toolTip() == long_copy


def test_advisory_elision_tracks_the_available_width(view, qapp):
    long_copy = "Passwords will not be remembered this session. " * 40
    view.set_credential_state("advisory", long_copy)
    qapp.processEvents()
    wide = view.advisory_label.text()

    view.resize(640, 688)
    qapp.processEvents()
    narrow = view.advisory_label.text()
    assert narrow.endswith("…")
    assert len(narrow) < len(wide)

    view.resize(880, 688)
    qapp.processEvents()
    assert len(view.advisory_label.text()) > len(narrow)


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


def test_capture_repaints_a_toonless_card_and_lineup(monkeypatch, qapp):
    from utils.recent_toons import RecentToonsStore
    from utils.toon_capture_bridge import ToonCaptureBridge

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False)
    try:
        values = {}
        store_settings = SimpleNamespace(
            get=lambda key, default=None: values.get(key, default),
            set=lambda key, value: values.__setitem__(key, value),
        )
        tab._recent_toons = RecentToonsStore(store_settings)
        tab._toon_bridge = ToonCaptureBridge(tab._recent_toons)
        tab._render_current_view("ttr")
        before = tab.grandstand.shelf.card_for("a")
        assert before.footer_text() == "No toon yet"

        tab._toon_bridge.record_launch(4242, "ttr", "a")
        tab.capture_toon(
            4242, "Flossbud", "7400", species="cat", accent="#123456")

        card = tab.grandstand.shelf.card_for("a")
        assert card.name_text() == "Flossbud"
        card.clicked.emit("a")
        lineup = tab.grandstand.hero.crew_area.slots()
        assert [entry.account_id for entry in lineup] == ["a"]
        assert lineup[0].treatment == "bust"
    finally:
        tab.shutdown()
        tab.close()


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


def test_late_customizations_manager_repaints_grandstand_entries(
        monkeypatch, qapp):
    from utils.recent_toons import RecentToonsStore

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False)
    try:
        values = {}
        store_settings = SimpleNamespace(
            get=lambda key, default=None: values.get(key, default),
            set=lambda key, value: values.__setitem__(key, value),
        )
        tab._recent_toons = RecentToonsStore(store_settings)
        tab._recent_toons.record(
            "a", "Flossbud", "ttr", "7400", species="cat",
            accent="#123456")
        tab._render_current_view("ttr")
        tab.grandstand.shelf.card_for("a").clicked.emit("a")
        assert tab.grandstand.shelf.card_for("a").entry().pose == "portrait"
        assert tab.grandstand.hero.crew_area.slots()[0].pose == "portrait"

        render = MagicMock(wraps=tab._render_current_view)
        tab._render_current_view = render
        manager = SimpleNamespace(
            get=lambda game, toon_name: {
                "accent": "#abcdef",
                "pose": "waving",
            } if (game, toon_name) == ("ttr", "Flossbud") else {})

        tab.set_customizations_manager(manager)

        assert [call.args for call in render.call_args_list] == [
            ("ttr",), ("cc",)]
        entry = tab.grandstand.shelf.card_for("a").entry()
        assert entry.accent == "#abcdef"
        assert entry.pose == "waving"
        lineup = tab.grandstand.hero.crew_area.slots()
        assert lineup[0].pose == "waving"
        assert lineup[0].treatment == "standing"
    finally:
        tab.shutdown()
        tab.close()


@pytest.mark.parametrize(
    "pending,available,reason",
    [
        (True, False, "Checking your keyring…"),
        (False, False,
         "Passwords will not be remembered this session."),
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
            "🔒  Your accounts are locked\n"
            "Unlock to load your saved accounts for this session.")
        assert tab.grandstand.hero.blocked_button.text() == "Unlock accounts"
        assert tab.grandstand.hero.blocked_button.isHidden() is False
    finally:
        tab.shutdown()
        tab.close()


def test_grandstand_corrupt_vault_blocks_without_unlock_action(
        monkeypatch, qapp):
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    cred = MagicMock(keyring_available=False, keyring_probe_pending=True,
                     macos_unlock_state="corrupt")
    cred.get_accounts_metadata.return_value = []
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        reason = tab.grandstand.hero.blocked_text()
        assert tab._keyring_banner is None
        assert tab.grandstand.hero.is_blocked() is True
        assert reason.startswith("⚠  Couldn't open your saved accounts\n")
        assert "Your data was left untouched." in reason
        assert "Restart\nTTMT to try again" in reason
        assert "keyring-debug.log" in reason
        assert tab.grandstand.hero.blocked_button.text() == ""
        assert tab.grandstand.hero.blocked_button.isHidden() is True
    finally:
        tab.shutdown()
        tab.close()


def test_blocked_credentials_guard_official_launcher_at_runner_boundary(
        monkeypatch, qapp):
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    import tabs.launch_tab as launch_tab
    runner = MagicMock(return_value=True)
    monkeypatch.setattr(launch_tab, "run_official_ttr_launcher", runner)
    cred = MagicMock(keyring_available=False, keyring_probe_pending=True,
                     macos_unlock_state="denied")
    cred.get_accounts_metadata.return_value = []
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        assert tab.grandstand.hero.blocked_text() == (
            "🔒  Your accounts are locked\n"
            "Unlock to load your saved accounts for this session.")
        # The view is presentation and intent. Deliberately clear its entire
        # credential state while leaving the tab-owned dispatch state blocked.
        tab.grandstand.set_credential_state("ok")
        assert tab.grandstand.is_credential_blocked() is False
        tab.grandstand.official_launcher_requested.emit("ttr")
        runner.assert_not_called()

        cred.macos_unlock_state = "unlocked"
        cred.keyring_probe_pending = False
        cred.keyring_available = True
        tab._push_credential_state()
        tab.grandstand.official_launcher_requested.emit("ttr")
        runner.assert_called_once_with()
    finally:
        tab.shutdown()
        tab.close()


def _make_grandstand_launch_tab(monkeypatch, account_ids, *, blocked,
                                game="ttr"):
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    accounts = [
        SimpleNamespace(id=aid, game=game, label=aid, username=aid,
                        password="pw", launcher_token="")
        for aid in account_ids
    ]
    cred = MagicMock(
        keyring_available=not blocked,
        keyring_probe_pending=blocked,
        macos_unlock_state="denied" if blocked else "unlocked",
    )
    cred.get_accounts_metadata.return_value = accounts
    cred.get_account_metadata.side_effect = lambda index: accounts[index]
    cred.get_account.side_effect = lambda index: accounts[index]
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    return LaunchTab(cred_manager=cred, settings_manager=settings), cred


def test_a_direct_launch_signal_is_refused_while_blocked(monkeypatch, qapp):
    """Bypassing the UI must not bypass the guard."""
    import tabs.launch_tab as launch_tab

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=True, game="cc")
    engine_lookup = MagicMock(return_value="")
    party_dispatch = MagicMock()
    cc_gate = MagicMock(return_value=True)
    monkeypatch.setattr(launch_tab, "_cc_launch_gate", cc_gate)
    tab._get_engine_dir = engine_lookup
    tab._show_failure_dialog = MagicMock()
    tab._launch_party_account = party_dispatch
    try:
        tab.grandstand.launch_requested.emit("cc", "a")
        tab.grandstand.party_launch_requested.emit("cc", ["a"])
        engine_lookup.assert_not_called()
        cc_gate.assert_not_called()
        party_dispatch.assert_not_called()
        assert tab._party_timers == []
    finally:
        tab.shutdown()
        tab.close()


def test_a_queued_party_member_does_not_launch_after_blocking(
        monkeypatch, qapp):
    """The vault can lock mid-batch: a timer that fires after the block must
    not dispatch the account it was holding."""
    import tabs.launch_tab as launch_tab
    from PySide6.QtTest import QTest

    monkeypatch.setattr(launch_tab, "PARTY_STAGGER_MS", 1)
    tab, cred = _make_grandstand_launch_tab(
        monkeypatch, ["a", "b"], blocked=False)
    dispatched = MagicMock()
    tab._launch_party_account = dispatched
    try:
        tab.grandstand.party_launch_requested.emit("ttr", ["a", "b"])
        dispatched.assert_called_once_with("ttr", "a")

        cred.macos_unlock_state = "denied"
        cred.keyring_probe_pending = True
        cred.keyring_available = False
        tab._push_credential_state()
        QTest.qWait(20)

        dispatched.assert_called_once_with("ttr", "a")
        assert tab._party_pending == set()
    finally:
        tab.shutdown()
        tab.close()


def test_official_cc_launch_rechecks_blocking_after_the_gate(monkeypatch, qapp):
    """A credential transition inside the nested gate must stop dispatch."""
    import tabs.launch_tab as launch_tab

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False, game="cc")
    runner = MagicMock(return_value=True)

    def gate(_settings, parent=None):
        tab._set_grandstand_credential_state("blocked")
        return True

    monkeypatch.setattr(launch_tab, "_cc_launch_gate", gate)
    monkeypatch.setattr(launch_tab, "run_official_cc_launcher", runner)
    try:
        tab.grandstand.official_launcher_requested.emit("cc")
        runner.assert_not_called()
    finally:
        tab.shutdown()
        tab.close()


def test_direct_cc_launch_rechecks_blocking_after_the_gate(monkeypatch, qapp):
    """The account boundary must recheck after the Clash picker returns."""
    import tabs.launch_tab as launch_tab

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False, game="cc")
    engine_lookup = MagicMock(return_value="")

    def gate(_settings, parent=None):
        tab._set_grandstand_credential_state("blocked")
        return True

    monkeypatch.setattr(launch_tab, "_cc_launch_gate", gate)
    tab._get_engine_dir = engine_lookup
    tab._show_failure_dialog = MagicMock()
    try:
        tab.grandstand.launch_requested.emit("cc", "a")
        engine_lookup.assert_not_called()
    finally:
        tab.shutdown()
        tab.close()


def test_party_releases_delayed_members_if_first_launch_blocks(
        monkeypatch, qapp):
    """A re-entrant block during member one must leave no armed batch work."""
    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a", "b"], blocked=False)
    dispatched = MagicMock()

    def dispatch(game, account_id):
        dispatched(game, account_id)
        tab._set_grandstand_credential_state("blocked")

    tab._launch_party_account = dispatch
    try:
        tab.grandstand.party_launch_requested.emit("ttr", ["a", "b"])
        dispatched.assert_called_once_with("ttr", "a")
        assert tab._party_timers == []
        assert tab._party_pending == set()
        assert tab._party_gate_ok == set()
    finally:
        tab.shutdown()
        tab.close()
