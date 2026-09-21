"""The flag routes the launcher's view, and says so in the log."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from unittest.mock import MagicMock

from utils.widgets.grandstand.party import LaunchParty
from utils.widgets.grandstand.view import (
    HERO_H, SELECTOR_H, STAMP_PREFIX, GrandstandView, grandstand_enabled,
)


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
    assert grandstand_enabled() is False


@pytest.mark.parametrize("value,expected", [("1", True), ("0", False), ("", False)])
def test_flag_reads_the_env_var(monkeypatch, value, expected):
    monkeypatch.setenv("TTMT_GRANDSTAND", value)
    assert grandstand_enabled() is expected


def test_init_emits_the_startup_stamp(qapp):
    """CLAUDE.local.md running-code proof: never let the operator validate
    without evidence of which path is live."""
    lines = []
    GrandstandView(LaunchParty(None), log=lines.append)
    assert lines, "no stamp emitted"
    assert lines[0].startswith(STAMP_PREFIX)
    assert "milestone" in lines[0]


def test_stack_fits_the_content_band(qapp):
    """main.py: 860 - HEADER_H(112) - NAV_BAND_H(60) = 688, no scrolling."""
    v = GrandstandView(LaunchParty(None))
    v.resize(880, 688)
    v.show()
    qapp.processEvents()
    assert v.selector.height() == SELECTOR_H
    assert v.hero.height() == HERO_H
    assert v.shelf.height() > 0
    total = (v.selector.height() + v.hero.height() + v.shelf.height())
    assert total <= 688


def test_set_accounts_is_callable_before_any_wiring(qapp):
    v = GrandstandView(LaunchParty(None))
    v.set_accounts("ttr", [])
    v.set_account_state("ttr", "nobody", "idle")   # unknown id must not raise


def test_theme_is_forwarded_to_the_crew_lineup(qapp):
    v = GrandstandView(LaunchParty(None))

    v.apply_theme(False)

    assert v.hero.crew_area._is_dark is False


def test_declares_every_signal_the_spec_names(qapp):
    v = GrandstandView(LaunchParty(None))
    for name in ("game_changed", "party_changed", "star_changed",
                 "launch_requested", "party_launch_requested", "edit_requested",
                 "cancel_requested", "quit_requested", "enter_2fa_requested",
                 "retry_requested", "add_account_requested", "manage_requested",
                 "official_launcher_requested"):
        assert hasattr(v, name), f"missing signal {name}"


def test_layout_mode_does_not_resurrect_the_old_launcher(qapp, monkeypatch):
    """main.py calls this on resize; on the flagged path it must do nothing."""
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    from utils.settings_manager import SettingsManager
    from tabs.launch_tab import LaunchTab
    tab = LaunchTab(settings_manager=SettingsManager())
    try:
        assert getattr(tab, "_sections_container", None) is None
        for mode in ("full", "compact", "full"):
            tab.set_layout_mode(mode)
            assert getattr(tab, "_sections_container", None) is None
    finally:
        tab.shutdown()


def test_legacy_sections_are_hidden_on_the_flagged_path(qapp, monkeypatch):
    """Live-validated defect: both LaunchSections were parented to the scroll
    widget unconditionally and, being in no layout, painted at (0,0) over the
    Grandstand stack. The container test could not see this — the sections are
    visible independently of the container."""
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    from utils.settings_manager import SettingsManager
    from tabs.launch_tab import LaunchTab
    tab = LaunchTab(settings_manager=SettingsManager())
    try:
        tab.show()
        qapp.processEvents()
        assert tab.grandstand.isVisible() is True        # the baseline is real
        assert tab.ttr_section.isVisible() is False
        assert tab.cc_section.isVisible() is False
        for mode in ("full", "compact", "full"):
            tab.set_layout_mode(mode)
            tab.refresh_theme()
            qapp.processEvents()
            assert tab.ttr_section.isVisible() is False
            assert tab.cc_section.isVisible() is False
    finally:
        tab.shutdown()
        tab.close()


def test_legacy_sections_still_show_when_the_flag_is_off(qapp, monkeypatch):
    """The other direction: with the flag unset the old launcher is untouched."""
    monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
    from utils.settings_manager import SettingsManager
    from tabs.launch_tab import LaunchTab
    tab = LaunchTab(settings_manager=SettingsManager())
    try:
        tab.show()
        qapp.processEvents()
        assert tab.ttr_section.isVisible() is True
        assert tab.cc_section.isVisible() is True
    finally:
        tab.shutdown()
        tab.close()


def test_populated_demo_fixtures_feed_the_grandstand_shelf(
        qapp, monkeypatch):
    """With both flags set the shelf shows the fixture accounts, and each
    card carries its fixture state — the way every card state is put on
    screen for milestone validation."""
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    monkeypatch.setenv("TTMT_DEMO_LAUNCH_TAB", "populated")
    from tabs.launch_tab import LaunchTab
    from utils.launch_tab_demo_mode import get_demo_fixtures

    monkeypatch.setattr(LaunchTab, "_start_keyring_probe", lambda self: None)
    cred = MagicMock(keyring_available=True, keyring_probe_pending=False)
    cred.get_accounts_metadata.return_value = []
    settings = MagicMock()
    settings.get.side_effect = lambda _key, default=None: default
    tab = LaunchTab(cred_manager=cred, settings_manager=settings)
    try:
        fixtures = get_demo_fixtures()
        assert fixtures is not None
        for game in ("ttr", "cc"):
            if tab.grandstand.active_game() != game:
                tab.grandstand.selector.game_clicked.emit(game)
            cards = tab.grandstand.shelf.cards()
            assert [(card.entry().label, card.state()) for card in cards] == [
                (fixture["label"], fixture["state"])
                for fixture in fixtures[game]
            ]
        # The failure detail rides along with the state, not just its name.
        failed = next(f for f in fixtures["ttr"] if f["state"] == "failed")
        tab.grandstand.selector.game_clicked.emit("ttr")
        card = next(c for c in tab.grandstand.shelf.cards()
                    if c.entry().label == failed["label"])
        assert card.raw_error() == failed["raw"]
    finally:
        tab.shutdown()
        tab.close()


def test_layout_mode_keeps_the_old_launcher_when_flag_is_off(qapp, monkeypatch):
    """The legacy launcher retains compact/full switching until cut-over."""
    monkeypatch.delenv("TTMT_GRANDSTAND", raising=False)
    from utils.settings_manager import SettingsManager
    from tabs.launch_tab import LaunchTab
    tab = LaunchTab(settings_manager=SettingsManager())
    try:
        original = tab._sections_container
        assert original is not None
        tab.set_layout_mode("full")
        assert tab._sections_container is not None
        assert tab._sections_container is not original
        assert tab._layout_mode == "full"
    finally:
        tab.shutdown()
