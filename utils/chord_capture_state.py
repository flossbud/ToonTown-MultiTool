"""Global "a hotkey chord capture is recording" flag.

While a ChordCaptureButton is recording, every layer that normally
interprets keyboard input must stand down, or the capture fights the
app's own machinery:

- the darwin session tap must not suppress fresh keydowns (a suppressed
  event never reaches the key window, so the capture widget would never
  see the chord - and route_all would broadcast it to the toons);
- the router must not enqueue keydowns (a recorded 'w' is a chord key,
  not movement);
- hotkey providers must not FIRE a currently-bound chord the user is
  re-recording (pressing ctrl+1 to rebind it must not load profile 1).

This module is the single source of that mode. It is deliberately pure
(no Qt, no platform imports) so the tap thread, the router thread and
the GUI thread can all read it; a CPython bool read/write is atomic and
the consumers are all fail-open.

Listeners fire on EDGES only (False->True / True->False), on the thread
that called set_active (the GUI thread - the capture button). The input
service registers one to drain held keys when a capture begins, so a
key physically held across the mode flip can never strand a synthetic
hold in a game client (the V2 stuck-key class).
"""
from __future__ import annotations

from typing import Callable

_active = False
_listeners: list[Callable[[bool], None]] = []


def is_active() -> bool:
    return _active


def set_active(value: bool) -> None:
    global _active
    value = bool(value)
    if value == _active:
        return
    _active = value
    for cb in list(_listeners):
        try:
            cb(value)
        except Exception:  # noqa: BLE001 - a listener must never break capture
            pass


def register(cb: Callable[[bool], None]) -> None:
    if cb not in _listeners:
        _listeners.append(cb)


def unregister(cb: Callable[[bool], None]) -> None:
    try:
        _listeners.remove(cb)
    except ValueError:
        pass
