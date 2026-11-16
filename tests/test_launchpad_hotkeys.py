"""Hotkeys in the launchpad shell: the Float UI cards toggle hides / shows
the strips, the two cluster-scale actions are neither grabbed nor listed,
and the classic window's registry is untouched."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from utils.hotkey_actions import ACTIONS, effective_bindings, make_hotkey_hook
from utils.hotkey_chords import parse_chord
from utils.hotkey_dispatch import build_dispatch
from utils.hotkey_wiring import _WithoutActions
from utils.settings_keys import HOTKEY_BINDINGS
from utils.widgets.launchpad import hotkeys


class _Settings:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.cbs = []

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        for cb in list(self.cbs):
            cb(key, value)

    def on_change(self, cb):
        self.cbs.append(cb)


class _Strips:
    def __init__(self):
        self.toggles = 0

    def toggle_user_hidden(self):
        self.toggles += 1


class _Session:
    def toggle_running(self): pass
    def toggle_keep_alive_all(self): pass
    def refresh(self): pass


def _dispatch(strips):
    return build_dispatch(mode_controller=hotkeys.StripsHotkeyMode(lambda: strips),
                          launch_tab=object(), settings_manager=_Settings(),
                          load_profile=lambda i: None, session=_Session())


# ── the list ────────────────────────────────────────────────────────────────

def test_shell_actions_drop_scaling_and_relabel_the_cards_toggle():
    acts = hotkeys.actions()
    ids = [a.id for a in acts]
    assert "overlay.scale_up" not in ids and "overlay.scale_down" not in ids
    toggle = acts[ids.index("overlay.toggle_cards")]
    assert toggle.label == "Hide / show strips"
    assert toggle.category == "Float strips"
    assert len(acts) == len(ACTIONS) - 2
    # The registry itself is untouched (the classic window lists it all).
    from utils.hotkey_actions import action_by_id
    assert action_by_id("overlay.toggle_cards").label == "Hide/Show cards"
    assert action_by_id("overlay.toggle_cards").category == "Float UI"


# ── dispatch ────────────────────────────────────────────────────────────────

def test_cards_toggle_hides_and_shows_the_strips():
    strips = _Strips()
    d = _dispatch(strips)
    d["overlay.toggle_cards"]()
    d["overlay.toggle_cards"]()
    assert strips.toggles == 2


def test_cards_toggle_is_a_no_op_until_the_strips_have_it():
    d = _dispatch(object())                 # a controller without the method
    d["overlay.toggle_cards"]()             # no error
    d = _dispatch(None)                     # strips could not be built
    d["overlay.toggle_cards"]()


def test_scale_actions_do_nothing():
    strips = _Strips()
    d = _dispatch(strips)
    d["overlay.scale_up"]()
    d["overlay.scale_down"]()
    assert strips.toggles == 0


# ── grabbing ────────────────────────────────────────────────────────────────

def test_excluded_actions_are_not_grabbed_even_when_bound():
    sm = _Settings({HOTKEY_BINDINGS: {"overlay.scale_up": "ctrl+alt+u",
                                      "overlay.scale_down": "ctrl+alt+d",
                                      "overlay.toggle_cards": "ctrl+alt+h"}})
    view = _WithoutActions(sm, hotkeys.HIDDEN)
    eff = effective_bindings(view)
    assert "overlay.scale_up" not in eff and "overlay.scale_down" not in eff
    assert eff["overlay.toggle_cards"] == "ctrl+alt+h"
    hook = make_hotkey_hook(view)
    up = parse_chord("ctrl+alt+u")
    assert hook(up.mods, up.keys) is None
    h = parse_chord("ctrl+alt+h")
    assert hook(h.mods, h.keys) == "overlay.toggle_cards"
    # The stored bindings are not rewritten; the classic window still sees them.
    assert effective_bindings(sm)["overlay.scale_up"] == "ctrl+alt+u"


def test_the_view_follows_binding_changes():
    sm = _Settings()
    view = _WithoutActions(sm, hotkeys.HIDDEN)
    hook = make_hotkey_hook(view)
    sm.set(HOTKEY_BINDINGS, {"overlay.scale_up": "ctrl+alt+u", "service.toggle": "ctrl+alt+s"})
    s = parse_chord("ctrl+alt+s")
    u = parse_chord("ctrl+alt+u")
    assert hook(s.mods, s.keys) == "service.toggle"
    assert hook(u.mods, u.keys) is None


def test_a_corrupt_store_still_excludes():
    view = _WithoutActions(_Settings({HOTKEY_BINDINGS: ["not", "a", "dict"]}), hotkeys.HIDDEN)
    assert "overlay.scale_up" not in effective_bindings(view)


# ── the Settings sheet and the old page ─────────────────────────────────────

@pytest.fixture
def quiet(monkeypatch):
    import utils.widgets.settings_rows as sr
    monkeypatch.setattr(sr, "find_engine_path", lambda: None)
    monkeypatch.setattr(sr, "find_cc_engine_path", lambda: None)
    monkeypatch.setattr(sr, "discover_cc_installs", lambda: [])
    monkeypatch.setattr("services.cc_login_service.discover_cc_installs", lambda: [])


def test_settings_sheet_lists_the_shell_actions(qapp, quiet):
    from utils.widgets.launchpad.settings_sheet import SettingsSheet
    s = SettingsSheet(_Settings(), is_dark=True)
    ids = set(s.rows._hotkey_rows)
    assert ids == {a.id for a in hotkeys.actions()}
    assert "overlay.scale_up" not in ids
    row_titles = [r.label_widget.text() for r in s._cards["features"].rows()
                  if getattr(r, "label_widget", None) is not None]
    assert "Float strips - Hide / show strips" in row_titles
    assert not any("Scale cluster" in t for t in row_titles)
    assert not any(t.startswith("Float UI") for t in row_titles)


def test_sheet_conflict_with_a_hidden_action_does_not_crash(qapp, quiet, monkeypatch):
    """A chord a hidden scale action still holds is free in this shell: no
    prompt, no lookup of a row that is not there."""
    from PySide6.QtWidgets import QMessageBox
    import utils.widgets.settings_rows as sr
    from utils.widgets.launchpad.settings_sheet import SettingsSheet
    sm = _Settings({HOTKEY_BINDINGS: {"overlay.scale_up": "ctrl+alt+u"}})
    s = SettingsSheet(sm, is_dark=True)
    asked = []
    monkeypatch.setattr(sr.QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a) or QMessageBox.Yes))
    s.rows._on_hotkey_chord("service.toggle", "ctrl+alt+u")
    assert asked == []
    assert sm.data[HOTKEY_BINDINGS]["service.toggle"] == "ctrl+alt+u"


def test_sheet_conflict_prompt_names_the_shell_label(qapp, quiet, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    import utils.widgets.settings_rows as sr
    from utils.widgets.launchpad.settings_sheet import SettingsSheet
    sm = _Settings({HOTKEY_BINDINGS: {"overlay.toggle_cards": "ctrl+alt+h"}})
    s = SettingsSheet(sm, is_dark=True)
    texts = []
    monkeypatch.setattr(sr.QMessageBox, "question",
                        staticmethod(lambda p, t, text, *a, **k: texts.append(text) or QMessageBox.No))
    s.rows._on_hotkey_chord("service.toggle", "ctrl+alt+h")
    assert texts and "Hide / show strips" in texts[0]


def test_old_settings_page_still_lists_every_action(qapp, quiet):
    from tests._settings_rows_harness import RowsUnderTest
    rows = RowsUnderTest(_Settings())
    assert set(rows._hotkey_rows) == {a.id for a in ACTIONS}
