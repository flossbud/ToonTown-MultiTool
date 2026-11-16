"""Blocked credentials, advisory bars, empty rosters, deletions, theme."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt

from tabs.launch_tab import LaunchTab
from utils.credential_copy import KEYRING_WARNING_COPY
from utils.widgets.grandstand.card_shelf import CardShelf
from utils.widgets.grandstand.draft import MODE_ADD, MODE_EDIT, AccountDraft
from utils.widgets.grandstand.model import RosterEntry
from utils.widgets.grandstand.party import LaunchParty
from utils.widgets.grandstand.view import GrandstandView


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


def test_a_short_window_scrolls_the_tab_rather_than_clipping_the_cards(
        monkeypatch, qapp):
    """Live 2026-09-21: the cards' bottom borders were cut off. The shelf's
    scroll area (vertical bar OFF) reported a minimum height of a few rows of
    nothing, so on a short window the layout squeezed it below its 244 px
    strip and the 216 px cards ran past the viewport — measured at 852x640:
    viewport 190, card bottoms at 232 — while the tab's outer scroll area,
    which nothing below it constrained, never engaged (maximum 0). The shelf
    now floors its scroll area at the strip (plus the horizontal bar when it
    shows), so the outer area scrolls instead."""
    from PySide6.QtCore import QPoint, QRect
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    accounts = [
        SimpleNamespace(id=aid, game="ttr", label=aid, username=aid,
                        password="pw", launcher_token="")
        for aid in ("a", "b", "c", "d")
    ]
    cred = MagicMock(keyring_available=True, keyring_probe_pending=False)
    cred.get_accounts_metadata.side_effect = lambda: list(accounts)
    cred.get_account_metadata.side_effect = lambda index: accounts[index]
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        tab.resize(852, 640)
        tab.show()
        qapp.processEvents()
        qapp.processEvents()
        shelf = tab.grandstand.shelf
        viewport = shelf.scroll.viewport()
        strip_min = shelf._strip.minimumSizeHint().height()
        assert strip_min == 234                      # cards 216 + 6 + 12
        cards = shelf.cards()
        assert len(cards) == 4
        for card in cards:
            origin = card.mapTo(viewport, QPoint(0, 0))
            box = QRect(origin, card.size())
            assert viewport.rect().contains(box), (
                f"card {card.account_id()} runs to {box.bottom() + 1} in a "
                f"{viewport.height()} px viewport")
        assert viewport.height() >= strip_min
        overflow = tab._scroll.verticalScrollBar().maximum()
        assert overflow > 0                          # the outer area took over
        # The defect, in this window: without the floor the outer area stays
        # at 0 and the shelf loses exactly those `overflow` pixels, leaving a
        # viewport shorter than the strip (190 < 244 at 852x640).
        assert viewport.height() - overflow < strip_min
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


def _recent_toons_store():
    from utils.recent_toons import RecentToonsStore
    values = {}
    return RecentToonsStore(SimpleNamespace(
        get=lambda key, default=None: values.get(key, default),
        set=lambda key, value: values.__setitem__(key, value)))


def test_capture_repaints_only_when_it_changes_what_the_card_shows(
        monkeypatch, qapp):
    """Captures arrive on every laff tick of every running toon. A rebuild on
    each one would discard hover and focus mid-play (the discipline Finding
    7(b) restored), so only a capture that changes a drawn value repaints."""
    from utils.toon_capture_bridge import ToonCaptureBridge

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False)
    try:
        tab._recent_toons = _recent_toons_store()
        tab._toon_bridge = ToonCaptureBridge(tab._recent_toons)
        tab._render_current_view("ttr")
        tab._toon_bridge.record_launch(4242, "ttr", "a")

        tab.capture_toon(4242, "Flossbud", "7400", species="cat", laff=15)
        card = tab.grandstand.shelf.card_for("a")
        assert card.name_text() == "Flossbud"

        tab.capture_toon(4242, "Flossbud", "7400", species="cat", laff=16)
        assert tab.grandstand.shelf.card_for("a") is card       # laff only
        assert tab._recent_toons.get("a").laff == 16            # still recorded

        tab.capture_toon(4242, "Hiro", "7401", species="dog", laff=16)
        after = tab.grandstand.shelf.card_for("a")
        assert after is not card
        assert after.name_text() == "Hiro"
    finally:
        tab.shutdown()
        tab.close()


def test_unflagged_capture_records_without_repainting(monkeypatch, qapp):
    """The legacy launcher painted nothing on capture; its tiles are rebuilt
    by set_page, so a repaint per laff tick would thrash them."""
    from utils.toon_capture_bridge import ToonCaptureBridge

    tab, _cred = _make_launch_tab(
        monkeypatch, ["a"], blocked=False, flagged=False)
    try:
        assert not hasattr(tab, "grandstand")
        tab._recent_toons = _recent_toons_store()
        tab._toon_bridge = ToonCaptureBridge(tab._recent_toons)
        tab._toon_bridge.record_launch(4242, "ttr", "a")
        render_section = MagicMock()
        tab._render_section = render_section
        tab._render_grandstand = MagicMock()

        tab.capture_toon(4242, "Flossbud", "7400", species="cat", laff=15)

        render_section.assert_not_called()
        tab._render_grandstand.assert_not_called()
        assert tab._recent_toons.get("a").toon_name == "Flossbud"
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
        assert entry.pose == "waving"                 # saved pose survives on the entry
        lineup = tab.grandstand.hero.crew_area.slots()
        assert lineup[0].pose == "portrait"           # but the stage draws STAGE_POSE
        assert lineup[0].treatment == "bust"
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
                                game="ttr", logger=None):
    return _make_launch_tab(monkeypatch, account_ids, blocked=blocked,
                            game=game, flagged=True, logger=logger)


def _make_launch_tab(monkeypatch, account_ids, *, blocked, game="ttr",
                     flagged, logger=None):
    """`flagged=False` builds the legacy launcher (flag unset, nothing
    mounted) from the same accounts, for the unflagged pin tests.

    `logger`, when given, makes self.log route only to logger.append_log —
    matching the real Debug tab wiring, instead of the no-logger fallback
    (self.log prints directly when self.logger is falsy)."""
    if flagged:
        monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    else:
        monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
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
    return LaunchTab(cred_manager=cred, settings_manager=settings,
                     logger=logger), cred


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


# ── nested loops on the remaining launch paths ──────────────────────────────

def test_direct_cc_launch_bails_if_the_account_left_during_the_gate(
        monkeypatch, qapp):
    """The roster can be rebuilt while the Clash picker is open (the keyring
    probe completing does exactly that). A slot and index resolved before the
    gate are stale afterwards: an index that now points at a different
    account would launch that account's credentials under this card."""
    import tabs.launch_tab as launch_tab

    tab, cred = _make_grandstand_launch_tab(
        monkeypatch, ["a", "b"], blocked=False, game="cc")
    engine_lookup = MagicMock(return_value="")

    def gate(_settings, parent=None):
        del cred.get_accounts_metadata.return_value[0]     # "a" is gone
        tab._reconcile_slots()
        return True

    monkeypatch.setattr(launch_tab, "_cc_launch_gate", gate)
    tab._get_engine_dir = engine_lookup
    tab._show_failure_dialog = MagicMock()
    try:
        tab.grandstand.launch_requested.emit("cc", "a")
        engine_lookup.assert_not_called()
        cred.get_account.assert_not_called()
    finally:
        tab.shutdown()
        tab.close()


def test_direct_cc_launch_bails_if_shutdown_began_during_the_gate(
        monkeypatch, qapp):
    import tabs.launch_tab as launch_tab

    tab, cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False, game="cc")
    engine_lookup = MagicMock(return_value="")

    def gate(_settings, parent=None):
        tab.shutdown()
        return True

    monkeypatch.setattr(launch_tab, "_cc_launch_gate", gate)
    tab._get_engine_dir = engine_lookup
    tab._show_failure_dialog = MagicMock()
    try:
        tab.grandstand.launch_requested.emit("cc", "a")
        engine_lookup.assert_not_called()
        cred.get_account.assert_not_called()
    finally:
        tab.close()


def test_direct_cc_launch_does_not_kill_a_game_started_during_the_gate(
        monkeypatch, qapp, tmp_path):
    """A global hotkey is not blocked by the picker. If it started this
    account while the gate was open, the click that predates it must not
    fall through to the relaunch-kills-the-running-game branch. The engine
    is real here so that branch is reachable: nothing short of the recheck
    stands between the gate and the kill."""
    import tabs.launch_tab as launch_tab

    engine_dir = tmp_path / "cc"
    engine_dir.mkdir()
    (engine_dir / launch_tab.get_cc_engine_executable_name()).touch()
    tab, cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False, game="cc")
    launcher = SimpleNamespace(is_running=lambda: True, kill=MagicMock())

    def gate(_settings, parent=None):
        tab._slots["cc"]["a"].launcher = launcher
        return True

    monkeypatch.setattr(launch_tab, "_cc_launch_gate", gate)
    tab._get_engine_dir = lambda game: str(engine_dir)
    tab._make_launchers = MagicMock()
    tab._show_failure_dialog = MagicMock()
    try:
        tab.grandstand.launch_requested.emit("cc", "a")
        launcher.kill.assert_not_called()
        tab._make_launchers.assert_not_called()
    finally:
        tab._slots["cc"]["a"].launcher = None
        tab.shutdown()
        tab.close()


class _FakeMessageBox:
    """QMessageBox stand-in whose modal exec runs a caller-supplied side
    effect, the way a real nested loop lets the world move on."""
    Warning = object()
    AcceptRole = object()
    RejectRole = object()
    during_exec = staticmethod(lambda: None)
    choose = "Open official launcher"

    def __init__(self, *args, **kwargs):
        self._buttons = {}
        self._clicked = None

    def setIcon(self, *_):
        pass

    def setWindowTitle(self, *_):
        pass

    def setText(self, *_):
        pass

    def setInformativeText(self, *_):
        pass

    def addButton(self, text, _role):
        self._buttons[text] = object()
        return self._buttons[text]

    def exec(self):
        type(self).during_exec()
        self._clicked = self._buttons.get(type(self).choose)

    def clickedButton(self):
        return self._clicked


def test_cc_patch_fallback_cannot_skip_the_blocked_guard(monkeypatch, qapp):
    """The vault can lock while the update-failed box is open. The offer must
    reach the official launcher through the guarded boundary, never directly."""
    import PySide6.QtWidgets as qtw
    import tabs.launch_tab as launch_tab

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False, game="cc")
    runner = MagicMock(return_value=True)
    monkeypatch.setattr(launch_tab, "run_official_cc_launcher", runner)
    monkeypatch.setattr(launch_tab, "_cc_launch_gate",
                        lambda _settings, parent=None: True)

    class Box(_FakeMessageBox):
        during_exec = staticmethod(
            lambda: tab._set_grandstand_credential_state("blocked"))

    monkeypatch.setattr(qtw, "QMessageBox", Box)
    try:
        tab._offer_cc_launcher_fallback("a", "patch failed")
        runner.assert_not_called()
    finally:
        tab.shutdown()
        tab.close()


def test_cc_patch_fallback_opens_the_launcher_through_the_boundary(
        monkeypatch, qapp):
    """Same offer, nothing changes while the box is open: the launcher runs,
    with the boundary's own install gate consulted on the way."""
    import PySide6.QtWidgets as qtw
    import tabs.launch_tab as launch_tab

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False, game="cc")
    runner = MagicMock(return_value=True)
    gate = MagicMock(return_value=True)
    monkeypatch.setattr(launch_tab, "run_official_cc_launcher", runner)
    monkeypatch.setattr(launch_tab, "_cc_launch_gate", gate)
    monkeypatch.setattr(qtw, "QMessageBox", _FakeMessageBox)
    try:
        tab._offer_cc_launcher_fallback("a", "patch failed")
        gate.assert_called_once()
        runner.assert_called_once_with(settings_manager=tab.settings_manager)
    finally:
        tab.shutdown()
        tab.close()


@pytest.mark.parametrize("answer", [("123456", True), ("", False)])
def test_2fa_prompt_ignores_a_worker_that_superseded_the_asker(
        monkeypatch, qapp, answer):
    """A relaunch during the code dialog installs a new worker on the slot.
    The dialog's answer belongs to the worker that asked: the newcomer must
    receive neither the token nor a cancellation, and its state must stand."""
    import tabs.launch_tab as launch_tab

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False)
    asker = MagicMock(name="asker")
    newcomer = MagicMock(name="newcomer")
    slot = tab._slots["ttr"]["a"]
    slot.worker = asker
    slot.state = "logging_in"
    status = MagicMock(wraps=tab._update_status)
    tab._update_status = status

    def get_text(*_args, **_kwargs):
        slot.worker = newcomer
        return answer

    monkeypatch.setattr(launch_tab.QInputDialog, "getText",
                        staticmethod(get_text))
    try:
        tab._prompt_2fa("ttr", "a", "Two-Factor Authentication required")
        newcomer.submit_2fa.assert_not_called()
        newcomer.cancel.assert_not_called()
        asker.submit_2fa.assert_not_called()
        asker.cancel.assert_not_called()
        status.assert_not_called()
        assert slot.state == "logging_in"
        assert tab._pending_2fa == set()
    finally:
        slot.worker = None
        tab.shutdown()
        tab.close()


@pytest.mark.parametrize("answer", [("123456", True), ("", False)])
def test_2fa_prompt_answers_the_worker_that_asked(monkeypatch, qapp, answer):
    import tabs.launch_tab as launch_tab

    tab, _cred = _make_grandstand_launch_tab(
        monkeypatch, ["a"], blocked=False)
    asker = MagicMock(name="asker")
    slot = tab._slots["ttr"]["a"]
    slot.worker = asker
    monkeypatch.setattr(launch_tab.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: answer))
    try:
        tab._prompt_2fa("ttr", "a", "Two-Factor Authentication required")
        token, ok = answer
        if ok:
            asker.submit_2fa.assert_called_once_with(token)
            asker.cancel.assert_not_called()
        else:
            asker.cancel.assert_called_once_with()
            assert slot.state == "idle"
            assert slot.message == "2FA cancelled"
    finally:
        slot.worker = None
        tab.shutdown()
        tab.close()


@pytest.mark.parametrize("answer", [("123456", True), ("", False)])
def test_unflagged_2fa_prompt_answers_whichever_worker_the_slot_holds(
        monkeypatch, qapp, answer):
    """Base behaviour, pinned for the legacy launcher: the answer goes to the
    worker on the slot when the dialog closes, even one that superseded the
    asker; a dismissal resets the slot to idle. The identity guard is a
    flagged-path rule only."""
    import tabs.launch_tab as launch_tab

    tab, _cred = _make_launch_tab(
        monkeypatch, ["a"], blocked=False, flagged=False)
    assert not hasattr(tab, "grandstand")
    asker = MagicMock(name="asker")
    newcomer = MagicMock(name="newcomer")
    slot = tab._slots["ttr"]["a"]
    slot.worker = asker
    slot.state = "logging_in"

    def get_text(*_args, **_kwargs):
        slot.worker = newcomer
        return answer

    monkeypatch.setattr(launch_tab.QInputDialog, "getText",
                        staticmethod(get_text))
    try:
        tab._prompt_2fa("ttr", "a", "Two-Factor Authentication required")
        token, ok = answer
        asker.submit_2fa.assert_not_called()
        asker.cancel.assert_not_called()
        if ok:
            newcomer.submit_2fa.assert_called_once_with(token)
            newcomer.cancel.assert_not_called()
            assert slot.state == "logging_in"
        else:
            newcomer.cancel.assert_called_once_with()
            assert slot.state == "idle"
            assert slot.message == "2FA cancelled"
    finally:
        slot.worker = None
        tab.shutdown()
        tab.close()


# ── account sheet wiring (sub-project C) ────────────────────────────────────

def _stub_editor(monkeypatch):
    """Replace the legacy AccountEditor with a recorder. A real QDialog's
    exec() would block the test in a nested event loop, and before Task 1's
    wiring lands the gear still opens that dialog."""
    import tabs.launch_tab as launch_tab

    class EditorStub:
        opened = []

        def __init__(self, *args, **kwargs):
            EditorStub.opened.append(kwargs)
            self.account_saved = MagicMock()

        def exec(self):
            return 0

    monkeypatch.setattr(launch_tab, "AccountEditor", EditorStub)
    return EditorStub


def _mutating_update(accounts):
    """A cred_manager.update_account that edits the metadata the rig hands
    back, so a re-render shows the change the way the real store would."""
    def update(index, label, username, password):
        accounts[index].label = label
        accounts[index].username = username
        if password is not None:
            accounts[index].password = password
    return update


def _open_sheet_via_gear(tab, aid="a"):
    tab.grandstand.shelf.card_for(aid).gear_clicked.emit(aid)
    return tab.grandstand.account_sheet


def test_gear_opens_the_account_sheet_prefilled_from_the_store(
        monkeypatch, qapp, capsys):
    _stub_editor(monkeypatch)
    tab, _cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        sheet = _open_sheet_via_gear(tab)
        assert tab.grandstand.in_focus_mode() is True
        d = sheet.draft()
        assert (d.mode, d.id, d.game) == (MODE_EDIT, "a", "ttr")
        assert (d.label, d.username, d.password) == ("a", "a", "pw")
        assert d.keyring_has_password is True and d.keyring_readable is True
        assert sheet.password_input.text() == "pw"
        # Running-code stamp: the live validator greps for this exact line.
        assert "[Grandstand] sheet: account a" in capsys.readouterr().out
    finally:
        tab.shutdown()
        tab.close()


def test_sheet_save_writes_through_update_account_and_updates_the_card(
        monkeypatch, qapp):
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a", "b"], blocked=False)
    cred.update_account.side_effect = _mutating_update(
        cred.get_accounts_metadata.return_value)
    try:
        sheet = _open_sheet_via_gear(tab, "b")
        sheet.label_input.setText("Gag alt")
        tab.grandstand.sheet.save_button.click()
        cred.update_account.assert_called_once_with(
            1, label="Gag alt", username="b", password="pw")
        assert tab.grandstand.in_focus_mode() is False
        assert tab.grandstand.shelf.card_for("b").entry().label == "Gag alt"
        assert tab.grandstand.shelf.card_for("b").name_text() == "Gag alt"
    finally:
        tab.shutdown()
        tab.close()


def test_a_blank_password_keeps_the_stored_one(monkeypatch, qapp):
    """Today's semantics: update_account(password=None) preserves the keyring
    entry, so a label change never demands retyping the password."""
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        sheet = _open_sheet_via_gear(tab)
        sheet.password_input.setText("")
        tab.grandstand.sheet.save_button.click()
        cred.update_account.assert_called_once_with(
            0, label="a", username="a", password=None)
        assert tab.grandstand.in_focus_mode() is False
    finally:
        tab.shutdown()
        tab.close()


def test_saving_a_whitespace_password_never_overwrites_the_stored_one(
        monkeypatch, qapp):
    """validate() strips, so "   " is a savable draft. If the save site did
    not strip too it would write three spaces over a good keyring entry."""
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        sheet = _open_sheet_via_gear(tab)
        assert tab.grandstand.in_focus_mode() is True
        sheet.password_input.setText("   ")
        tab.grandstand.sheet.save_button.click()
        cred.update_account.assert_called_once_with(
            0, label="a", username="a", password=None)
    finally:
        tab.shutdown()
        tab.close()


def test_sheet_save_refuses_a_blank_username(monkeypatch, qapp):
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        sheet = _open_sheet_via_gear(tab)
        sheet.username_input.setText("   ")
        tab.grandstand.sheet.save_button.click()
        cred.update_account.assert_not_called()
        assert sheet.username_error.isVisibleTo(sheet) is True
        assert sheet.username_error.text() == "Username is required"
        assert tab.grandstand.in_focus_mode() is True
    finally:
        tab.shutdown()
        tab.close()


def test_back_drops_the_draft_without_writing(monkeypatch, qapp):
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        sheet = _open_sheet_via_gear(tab)
        assert tab.grandstand.in_focus_mode() is True     # the sheet is open,
        sheet.label_input.setText("changed")              # so the edit lands
        tab.grandstand.sheet.back_button.click()
        cred.update_account.assert_not_called()
        assert tab.grandstand.in_focus_mode() is False
        assert tab.grandstand.shelf.card_for("a").entry().label == "a"
    finally:
        tab.shutdown()
        tab.close()


def test_an_unreadable_keyring_opens_the_sheet_with_an_empty_password(
        monkeypatch, qapp):
    """Spec §4: keyring unavailable -> empty field, keyring_has_password
    False, keyring_readable False, and a blank Save keeps what is stored."""
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    cred.keyring_available = False
    try:
        sheet = _open_sheet_via_gear(tab)
        d = sheet.draft()
        assert d.password == "" and d.keyring_has_password is False
        assert d.keyring_readable is False
        assert sheet.password_helper.isVisibleTo(sheet) is True
        assert sheet.password_helper.text() == "Stored password can't be read right now"
        tab.grandstand.sheet.save_button.click()
        cred.update_account.assert_called_once_with(
            0, label="a", username="a", password=None)
    finally:
        tab.shutdown()
        tab.close()


def test_the_pencil_still_opens_todays_editor(monkeypatch, qapp):
    """Sub-project B owns the appearance surface; until then the pencil is
    untouched and the sheet's cross-link routes to the same place."""
    EditorStub = _stub_editor(monkeypatch)
    tab, _cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        tab.grandstand.shelf.card_for("a").edit_clicked.emit("a")
        assert len(EditorStub.opened) == 1
        assert EditorStub.opened[0]["mode"] == "edit"
        assert tab.grandstand.in_focus_mode() is False
        _open_sheet_via_gear(tab)
        assert tab.grandstand.in_focus_mode() is True    # the gear did NOT
        assert len(EditorStub.opened) == 1                # open the editor
        tab.grandstand.sheet.header.cross_link.click()
        assert len(EditorStub.opened) == 2
        assert EditorStub.opened[1]["mode"] == "edit"
    finally:
        tab.shutdown()
        tab.close()


def test_the_cross_link_hands_the_dialog_what_was_typed(monkeypatch, qapp):
    """Whole-branch review I4: the cross-link drops the draft on its way out,
    so unless the typed values ride along they vanish with no warning — the
    dialog would open on the stored account and the user would retype."""
    EditorStub = _stub_editor(monkeypatch)
    tab, _cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        sheet = _open_sheet_via_gear(tab)
        sheet.label_input.setText("Gag grind alt")
        sheet.username_input.setText("floss2")
        sheet.password_input.setText("typed-pw")
        tab.grandstand.sheet.header.cross_link.click()
        assert len(EditorStub.opened) == 1
        opened = EditorStub.opened[0]
        assert opened["initial_label"] == "Gag grind alt"
        assert opened["initial_username"] == "floss2"
        assert opened["initial_password"] == "typed-pw"
        assert opened["mode"] == "edit" and opened["game"] == "ttr"
        assert tab.grandstand.in_focus_mode() is False     # the draft still goes
    finally:
        tab.shutdown()
        tab.close()


def test_the_cross_link_closes_the_sheet_before_the_legacy_editor_opens(
        monkeypatch, qapp):
    """The dialog edits the sheet's own three fields. Left open behind it,
    the sheet would still hold the pre-dialog label, and a Save afterwards
    would write that stale label back over what the dialog just saved."""
    EditorStub = _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        _open_sheet_via_gear(tab)
        assert tab.grandstand.in_focus_mode() is True
        tab.grandstand.sheet.header.cross_link.click()
        assert len(EditorStub.opened) == 1                # the dialog ran
        assert tab.grandstand.in_focus_mode() is False    # over the roster
        # Nothing is left behind that could still write: the draft is gone,
        # so the footer's Save is inert.
        tab.grandstand.sheet.save_button.click()
        cred.update_account.assert_not_called()
    finally:
        tab.shutdown()
        tab.close()


def test_unflagged_tab_never_reaches_the_sheet_handler(monkeypatch, qapp):
    """Every LaunchTab change is gated by _grandstand_mounted()."""
    tab, cred = _make_launch_tab(monkeypatch, ["a"], blocked=False, flagged=False)
    try:
        assert tab._grandstand_mounted() is False
        draft = AccountDraft(id="a", game="ttr", mode=MODE_EDIT, label="x",
                             username="a", password="pw", keyring_has_password=True)
        tab._on_account_save("ttr", draft)
        cred.update_account.assert_not_called()
    finally:
        tab.shutdown()
        tab.close()


# ── add mode (sub-project C, Task 3) ────────────────────────────────────────

def _mutating_add(accounts):
    """A cred_manager.add_account that appends to the rig's metadata list
    and reports success, the way the real store does."""
    def add(label, username, password, game):
        accounts.append(SimpleNamespace(
            id=f"n{len(accounts)}", game=game, label=label, username=username,
            password=password, launcher_token=""))
        return True
    return add


def test_add_account_opens_the_sheet_in_add_mode(monkeypatch, qapp, capsys):
    _stub_editor(monkeypatch)
    tab, _cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        tab.grandstand.shelf.add_tile.click()
        assert tab.grandstand.in_focus_mode() is True
        sheet = tab.grandstand.account_sheet
        d = sheet.draft()
        assert (d.mode, d.id, d.game) == (MODE_ADD, "", "ttr")
        assert (d.label, d.username, d.password) == ("", "", "")
        assert sheet.danger_field.isVisibleTo(sheet) is False
        assert "[Grandstand] sheet: account add" in capsys.readouterr().out
    finally:
        tab.shutdown()
        tab.close()


def test_add_mode_save_calls_add_account_and_shows_the_new_card(monkeypatch, qapp):
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    cred.add_account.side_effect = _mutating_add(cred.get_accounts_metadata.return_value)
    try:
        tab.grandstand.shelf.add_tile.click()
        sheet = tab.grandstand.account_sheet
        sheet.label_input.setText("Alt")
        sheet.username_input.setText("newbie")
        sheet.password_input.setText("secret")
        tab.grandstand.sheet.save_button.click()
        cred.add_account.assert_called_once_with(
            label="Alt", username="newbie", password="secret", game="ttr")
        assert tab.grandstand.in_focus_mode() is False
        assert [c.account_id() for c in tab.grandstand.shelf.cards()] == ["a", "n1"]
        assert tab.grandstand.shelf.card_for("n1").name_text() == "Alt"
    finally:
        tab.shutdown()
        tab.close()


def test_add_mode_requires_username_and_password(monkeypatch, qapp):
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        tab.grandstand.shelf.add_tile.click()
        tab.grandstand.sheet.save_button.click()
        cred.add_account.assert_not_called()
        assert tab.grandstand.in_focus_mode() is True
        assert tab.grandstand.account_sheet.errors() == {
            "username": "Username is required",
            "password": "Password is required"}
    finally:
        tab.shutdown()
        tab.close()


def test_a_refused_add_keeps_the_sheet_open(monkeypatch, qapp, capsys):
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    cred.add_account.return_value = False
    try:
        tab.grandstand.shelf.add_tile.click()
        sheet = tab.grandstand.account_sheet
        sheet.username_input.setText("newbie")
        sheet.password_input.setText("secret")
        tab.grandstand.sheet.save_button.click()
        cred.add_account.assert_called_once()
        assert tab.grandstand.in_focus_mode() is True
        assert sheet.draft().username == "newbie"
        assert [c.account_id() for c in tab.grandstand.shelf.cards()] == ["a"]
        assert "[Launch] Could not add TTR account." in capsys.readouterr().out
    finally:
        tab.shutdown()
        tab.close()


def test_the_ceiling_keeps_the_sheet_closed(monkeypatch, qapp):
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(
        monkeypatch, [f"a{i}" for i in range(16)], blocked=False)
    try:
        tab.grandstand.shelf.add_tile.click()
        assert tab.grandstand.in_focus_mode() is False
        cred.add_account.assert_not_called()
    finally:
        tab.shutdown()
        tab.close()


def test_unflagged_add_still_opens_todays_editor(monkeypatch, qapp):
    EditorStub = _stub_editor(monkeypatch)
    tab, _cred = _make_launch_tab(monkeypatch, ["a"], blocked=False, flagged=False)
    try:
        tab._on_add_account("ttr")
        assert len(EditorStub.opened) == 1
        assert EditorStub.opened[0]["mode"] == "add"
        assert EditorStub.opened[0]["game"] == "ttr"
    finally:
        tab.shutdown()
        tab.close()


# ── remove (sub-project C, Task 4) ──────────────────────────────────────────

def _confirm(monkeypatch, accepted: bool):
    import tabs.launch_tab as launch_tab

    class Dialog:
        DialogCode = SimpleNamespace(Accepted=1, Rejected=0)
        shown = []

        def __init__(self, *args, **kwargs):
            Dialog.shown.append(kwargs)

        def exec(self):
            return self.DialogCode.Accepted if accepted else self.DialogCode.Rejected

    monkeypatch.setattr(launch_tab, "ConfirmDialog", Dialog)
    return Dialog


def _mutating_delete(accounts):
    def delete(index):
        removed = accounts.pop(index)
        return removed.id, ""
    return delete


def test_remove_confirms_then_deletes_and_closes_the_sheet(monkeypatch, qapp):
    _stub_editor(monkeypatch)
    dialog = _confirm(monkeypatch, accepted=True)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a", "b"], blocked=False)
    cred.delete_account.side_effect = _mutating_delete(
        cred.get_accounts_metadata.return_value)
    try:
        sheet = _open_sheet_via_gear(tab, "a")
        sheet.remove_button.click()
        assert len(dialog.shown) == 1
        assert dialog.shown[0]["title"] == "Delete a?"
        cred.delete_account.assert_called_once_with(0)
        assert tab.grandstand.in_focus_mode() is False
        assert [c.account_id() for c in tab.grandstand.shelf.cards()] == ["b"]
    finally:
        tab.shutdown()
        tab.close()


def test_a_declined_confirm_keeps_the_sheet_and_the_account(monkeypatch, qapp):
    _stub_editor(monkeypatch)
    _confirm(monkeypatch, accepted=False)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        sheet = _open_sheet_via_gear(tab, "a")
        sheet.label_input.setText("kept")
        sheet.remove_button.click()
        cred.delete_account.assert_not_called()
        assert tab.grandstand.in_focus_mode() is True
        assert sheet.draft().label == "kept"
    finally:
        tab.shutdown()
        tab.close()


def test_an_account_removed_underneath_closes_the_open_sheet(monkeypatch, qapp):
    """Manage, another tab: the roster re-renders without the account and
    the sheet for it must not survive (spec §4)."""
    _stub_editor(monkeypatch)
    tab, cred = _make_grandstand_launch_tab(monkeypatch, ["a", "b"], blocked=False)
    try:
        _open_sheet_via_gear(tab, "a")
        cred.get_accounts_metadata.return_value.pop(0)
        tab._reconcile_slots()
        tab._render_grandstand("ttr")
        assert tab.grandstand.in_focus_mode() is False
        assert tab.grandstand.account_sheet.is_open() is False
    finally:
        tab.shutdown()
        tab.close()


def test_unflagged_tab_never_reaches_the_remove_handler(monkeypatch, qapp):
    _confirm(monkeypatch, accepted=True)
    tab, cred = _make_launch_tab(monkeypatch, ["a"], blocked=False, flagged=False)
    try:
        tab._on_account_remove("ttr", "a")
        cred.delete_account.assert_not_called()
    finally:
        tab.shutdown()
        tab.close()


# ── toon chosen (sub-project C, Task 6) ─────────────────────────────────────

def test_toon_chosen_sets_the_primary_and_rebuilds_card_hero_and_sheet(
        monkeypatch, qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from utils.widgets.grandstand.roster_card import CARD_H, CARD_W

    _stub_editor(monkeypatch)
    tab, _cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        tab._recent_toons = _recent_toons_store()
        tab._recent_toons.record("a", "Flossbud", "ttr", "7400", species="cat")
        tab._recent_toons.record("a", "Pepper", "ttr", "7401", species="dog")
        tab._render_current_view("ttr")
        assert tab.grandstand.shelf.card_for("a").name_text() == "Pepper"   # newest
        tab.grandstand.shelf.card_for("a").clicked.emit("a")
        before = tab.grandstand.hero.crew_area.slot_for("a")

        sheet = _open_sheet_via_gear(tab)
        assert sheet.frow_name_text() == "Pepper"
        sheet.choose_button.click()
        assert tab.grandstand.browser_open() is True
        card = tab.grandstand.browser.card_for("Flossbud")
        QTest.mouseClick(card, Qt.LeftButton, pos=QPoint(CARD_W // 2, CARD_H // 2))

        assert tab._recent_toons.primary_name("a") == "Flossbud"
        assert tab.grandstand.browser_open() is False
        assert tab.grandstand.in_focus_mode() is True
        assert sheet.frow_name_text() == "Flossbud"
        assert sheet.preview.name_text() == "Flossbud"
        assert tab.grandstand.shelf.card_for("a").name_text() == "Flossbud"
        assert tab.grandstand.shelf.card_for("a").footer_text() == "Primary"
        after = tab.grandstand.hero.crew_area.slot_for("a")
        assert after is not before and after.toon_name == "Flossbud"
    finally:
        tab.shutdown()
        tab.close()


def _renamed_toon_store():
    """The user's real shape: one toon renamed, so two records share a DNA,
    and the stored primary still names the one unique_toons merges away."""
    store = _recent_toons_store()
    store.record("a", "Blue Cat", "ttr", "7400", species="cat")
    store.record("a", "Katsuro", "ttr", "7400", species="cat")   # newest first
    store.set_primary("a", "Blue Cat")
    return store


def test_opening_the_sheet_heals_a_primary_a_rename_merged_away(
        monkeypatch, qapp, capsys):
    """Whole-branch review I1: RecentToonsStore.get resolves the primary from
    the raw list, the sheet and the browser from the deduped one, so the card
    said "Blue Cat" while the frow, the preview and the browser's check all
    said "Katsuro" — and the browser's checked card is inert, so the new UI
    could not repair it. LaunchTab is the only writer, so it heals the store."""
    _stub_editor(monkeypatch)
    tab, _cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        tab._recent_toons = _renamed_toon_store()
        tab._render_current_view("ttr")
        assert tab.grandstand.shelf.card_for("a").name_text() == "Blue Cat"
        capsys.readouterr()

        sheet = _open_sheet_via_gear(tab)
        assert tab._recent_toons.primary_name("a") == "Katsuro"
        assert sheet.frow_name_text() == "Katsuro"
        assert sheet.preview.name_text() == "Katsuro"
        assert tab.grandstand.shelf.card_for("a").name_text() == "Katsuro"
        sheet.choose_button.click()
        assert tab.grandstand.browser.current_card().toon_name() == "Katsuro"
        assert ("[Launch] TTR account 1: primary toon renamed to Katsuro."
                in capsys.readouterr().out)
    finally:
        tab.shutdown()
        tab.close()


def test_the_repair_line_reaches_stdout_even_with_a_real_debug_logger(
        monkeypatch, qapp, capsys):
    """M2 (re-review): with a real logger attached, self.log routes only to
    logger.append_log — the Debug tab drops it unless logging is switched
    on, so this must print plainly too, the way the Grandstand sheet stamps
    and utils/toon_renders.py do. (The I1 test above passes a bare LaunchTab,
    whose self.log falls back to print() on its own when logger is None —
    that fallback would mask a dropped print here, so this test pins a
    logger explicitly.)"""
    _stub_editor(monkeypatch)
    tab, _cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False,
                                             logger=MagicMock())
    try:
        tab._recent_toons = _renamed_toon_store()
        tab._render_current_view("ttr")
        capsys.readouterr()

        sheet = _open_sheet_via_gear(tab)
        sheet.choose_button.click()
        assert ("[Launch] TTR account 1: primary toon renamed to Katsuro."
                in capsys.readouterr().out)
    finally:
        tab.shutdown()
        tab.close()


def test_a_primary_that_still_exists_is_never_rewritten(monkeypatch, qapp):
    """The control: the repair is for a ghost only. A healthy primary must
    not be touched, or every sheet open would write to the store."""
    _stub_editor(monkeypatch)
    tab, _cred = _make_grandstand_launch_tab(monkeypatch, ["a"], blocked=False)
    try:
        tab._recent_toons = _recent_toons_store()
        tab._recent_toons.record("a", "Flossbud", "ttr", "7400", species="cat")
        tab._recent_toons.record("a", "Pepper", "ttr", "7401", species="dog")
        tab._recent_toons.set_primary("a", "Flossbud")
        writes = []
        real = tab._recent_toons.set_primary
        tab._recent_toons.set_primary = lambda aid, name: (
            writes.append((aid, name)), real(aid, name))[1]

        sheet = _open_sheet_via_gear(tab)
        assert writes == []
        assert tab._recent_toons.primary_name("a") == "Flossbud"
        assert sheet.frow_name_text() == "Flossbud"
    finally:
        tab.shutdown()
        tab.close()


def test_unflagged_tab_never_reaches_the_toon_handler(monkeypatch, qapp):
    tab, _cred = _make_launch_tab(monkeypatch, ["a"], blocked=False, flagged=False)
    try:
        tab._recent_toons = _recent_toons_store()
        tab._recent_toons.record("a", "Flossbud", "ttr", "7400")
        tab._on_toon_chosen("ttr", "a", "Flossbud")
        assert tab._recent_toons.primary_name("a") is None
    finally:
        tab.shutdown()
        tab.close()
