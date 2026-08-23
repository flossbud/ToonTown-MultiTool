"""The eight launch states on a card, and the two visibility rules."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from utils.rendition_poses import RenditionPoseFetcher
from utils.widgets.grandstand.model import RosterEntry
from utils.widgets.grandstand.roster_card import (
    ACTION_MAP, URGENT_STATES, RosterCard,
)

ALL_STATES = ["idle", "logging_in", "launching", "loading", "queued",
              "need_2fa", "running", "failed"]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(RenditionPoseFetcher, "cached_pixmap",
                        lambda self, dna, pose: None)
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: None)


def _entry(aid="a", state="idle"):
    return RosterEntry(account_id=aid, game="ttr", label="Alt",
                       username="flossbud", toon_name="Flossbud", species="cat",
                       dna="7400", accent="#4a8fe7", footer="Primary",
                       portrait_mode="render", state=state, message="",
                       raw_error="")


@pytest.fixture
def card(qapp):
    c = RosterCard()
    c.set_entry(_entry())
    return c


def test_entry_state_is_applied_when_the_card_is_built(qapp):
    card = RosterCard()
    card.set_entry(_entry(state="running"))
    assert card.state() == "running"
    assert card.footer_text() == "Running"


def test_every_state_from_the_old_tile_is_handled():
    """The launcher's state machine is inherited, not reinvented — parity with
    utils/widgets/account_tile.py:55 is the requirement."""
    for state in ALL_STATES:
        assert state in ACTION_MAP


@pytest.mark.parametrize("state,label", [
    ("idle", "Launch"), ("loading", "Quit"), ("queued", "Cancel"),
    ("need_2fa", "Enter 2FA →"), ("running", "Quit"), ("failed", "Retry"),
])
def test_action_label_per_state(card, state, label):
    card.set_state(state)
    assert card.action_label() == label


@pytest.mark.parametrize("state", ["logging_in", "launching"])
def test_in_flight_states_offer_no_action(card, state):
    card.set_state(state)
    assert card.action_visible() is False


def test_idle_action_is_hidden_when_the_card_is_checked(card):
    """Spec Q7: checked launches with Play; unchecked launches alone.

    Hover first: the action joins the hover cluster (spec §4.6 — urgent states
    pin their action "instead of waiting for hover"), so without it both
    assertions would read False and the Q7 rule would be untested.
    """
    card.set_state("idle")
    card.enterEvent(None)
    card.set_selected(True)
    assert card.action_visible() is False
    card.set_selected(False)
    assert card.action_visible() is True


def test_idle_action_waits_for_hover(card):
    """An unchecked idle card is not a permanent Launch button."""
    card.set_state("idle")
    card.set_selected(False)
    assert card.action_visible() is False
    card.enterEvent(None)
    assert card.action_visible() is True
    card.leaveEvent(None)
    assert card.action_visible() is False


@pytest.mark.parametrize("state", ["need_2fa", "failed"])
def test_urgent_states_stay_visible_when_checked(card, state):
    card.set_selected(True)
    card.set_state(state)
    assert card.action_visible() is True


@pytest.mark.parametrize("state", ["need_2fa", "failed"])
def test_urgent_states_do_not_wait_for_hover(card, state):
    """Spec Q2: a card that needs the user must not hide its action."""
    assert state in URGENT_STATES
    assert card._hover is False
    card.set_state(state)
    assert card.action_visible() is True


def test_running_starts_the_dot_pulse_and_leaving_stops_it(card):
    assert card.dot._pulsing is False
    card.set_state("running")
    assert card.footer_text() == "Running"
    assert card.dot_visible() is True
    assert card.dot._pulsing is True
    card.set_state("idle")
    assert card.dot_visible() is False
    assert card.dot._pulsing is False


def test_the_action_never_covers_the_name_or_the_footer(card):
    """A pinned urgent action must not hide the account's identity."""
    card.set_state("failed", "boom")
    assert card.action_visible() is True
    assert not card.action.geometry().intersects(card.name.geometry())
    assert not card.action.geometry().intersects(card.footer.geometry())


def test_the_username_yields_to_the_action(card):
    card.set_state("idle")
    card.set_selected(False)
    assert card.user.isVisibleTo(card) is True
    card.enterEvent(None)
    assert card.action_visible() is True
    assert card.user.isVisibleTo(card) is False
    card.leaveEvent(None)
    assert card.user.isVisibleTo(card) is True


def test_pointer_event_applies_state_once(card):
    calls = []
    card._apply_state = lambda: calls.append("apply")
    card.enterEvent(None)
    assert calls == ["apply"]


def test_queue_position_reaches_the_footer(card):
    card.set_state("queued", "position 42")
    assert "42" in card.footer_text()


def test_failure_is_summarised_not_dumped(card):
    card.set_state("failed", "TTR API HTTP 401: Incorrect username or password",
                   raw="TTR API HTTP 401: ...")
    assert card.footer_text() == "Bad credentials"


def test_raw_error_is_retained_for_the_detail_view(card):
    card.set_state("failed", "boom", raw="full traceback here")
    assert card.raw_error() == "full traceback here"


def test_each_action_emits_its_own_signal(card):
    got = []
    card.cancel_clicked.connect(lambda i: got.append(("cancel", i)))
    card.quit_clicked.connect(lambda i: got.append(("quit", i)))
    card.enter_2fa_clicked.connect(lambda i: got.append(("2fa", i)))
    card.retry_clicked.connect(lambda i: got.append(("retry", i)))
    for state, tag in (("queued", "cancel"), ("running", "quit"),
                       ("need_2fa", "2fa"), ("failed", "retry")):
        card.set_state(state)
        card.action.click()
    assert got == [("cancel", "a"), ("quit", "a"), ("2fa", "a"), ("retry", "a")]


def test_idle_action_launches_that_account_alone(card):
    seen = []
    card.launch_clicked.connect(seen.append)
    card.set_state("idle")
    card.set_selected(False)
    card.action.click()
    assert seen == ["a"]


def test_state_survives_a_selection_change(card):
    card.set_state("running")
    card.set_selected(True)
    assert card.state() == "running"
    assert card.action_label() == "Quit"
