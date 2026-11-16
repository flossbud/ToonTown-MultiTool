"""Hotkeys in the launchpad shell (TTMT_NEXT_UI=1).

The registry (utils/hotkey_actions.ACTIONS) still carries the old Float UI
actions. In this shell:
- "overlay.toggle_cards" means hide / show the float strips (the strips'
  StripController.toggle_user_hidden), listed as "Hide / show strips" under
  "Float strips";
- "overlay.scale_up" / "overlay.scale_down" do not exist: they are left out
  of the bindings that get grabbed (so their chords stay free for the
  games) and out of the Settings sheet.
The classic window keeps the registry as it is.
"""
from __future__ import annotations

from dataclasses import replace

HIDDEN = ("overlay.scale_up", "overlay.scale_down")
STRIPS_TOGGLE = "overlay.toggle_cards"
STRIPS_TOGGLE_LABEL = "Hide / show strips"
STRIPS_CATEGORY = "Float strips"


def actions() -> tuple:
    """The hotkey actions this shell lists, in registry order."""
    from utils.hotkey_actions import ACTIONS
    out = []
    for action in ACTIONS:
        if action.id in HIDDEN:
            continue
        if action.id == STRIPS_TOGGLE:
            action = replace(action, label=STRIPS_TOGGLE_LABEL, category=STRIPS_CATEGORY)
        out.append(action)
    return tuple(out)


class StripsHotkeyMode:
    """What utils.hotkey_dispatch sees as its mode controller in this shell:
    the Float UI's "hide / show cards" becomes hide / show the strips. Every
    call looks the strips' method up when it fires, so it works the moment
    the controller has toggle_user_hidden() and is a no-op before."""

    is_radial_open = False

    def __init__(self, strips_getter):
        self._strips = strips_getter

    def _toggle(self):
        strips = self._strips()
        fn = getattr(strips, "toggle_user_hidden", None) if strips is not None else None
        return fn if callable(fn) else None

    @property
    def is_active(self) -> bool:
        return self._toggle() is not None

    def toggle_cards_hidden(self, animate: bool = True) -> None:
        fn = self._toggle()
        if fn is not None:
            fn()
