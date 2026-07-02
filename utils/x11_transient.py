"""Confine a ghost-cursor overlay to its game window on X11/XWayland.

An EWMH window manager keeps a window whose WM_TRANSIENT_FOR points at a
parent stacked directly above that parent: raising the parent carries the
transient along, raising any unrelated window covers both, and minimizing
the parent minimizes the transient. Probed live on KWin Wayland (2026-07-02,
scratchpad ghost_probe): the constraint holds against XWayland AND
native-Wayland occluders, and a managed frameless window positions
pixel-identically to the override-redirect overlays it replaces.

Two probed facts shape this API:

- Qt's ``QWindow.setTransientParent(QWindow.fromWinId(...))`` never writes
  WM_TRANSIENT_FOR on xcb, and Qt rewrites/deletes the property on EVERY
  ``show()``. Confinement must therefore be (re)asserted AFTER each map,
  from outside Qt.
- ``_NET_WM_STATE`` changes on a mapped window only stick as ClientMessages
  to the root window (the WM owns the property post-map), so the
  skip-taskbar/pager/switcher and demands-attention states are sent that way.
- The transient constraint is only a LOWER bound, enforced when the WM
  restacks: a freshly MAPPED window still lands on top of the whole stack,
  above windows already raised over the game, and nothing ever lowers it
  (live symptom 2026-07-02: the glove floated over a file manager until its
  game window was next raised). So confinement ends with an explicit EWMH
  ``_NET_RESTACK_WINDOW`` (source=pager, detail=Above, sibling=game), which
  KWin honors in both directions -- verified on the live symptom itself.

GUI-thread only. This module keeps one lazily-opened python-xlib Display of
its own -- never the input backend's connection, which lives on capture
threads. All failures are soft: the caller falls back to unconfined ghosts.
"""
from __future__ import annotations

_display = None

# _NET_WM_STATE ClientMessage actions (EWMH)
_REMOVE, _ADD = 0, 1


def _get_display():
    global _display
    if _display is None:
        from Xlib import display as xdisplay
        _display = xdisplay.Display()
    return _display


def _drop_display() -> None:
    """Forget a (possibly dead) connection so the next call reopens."""
    global _display
    d, _display = _display, None
    if d is not None:
        try:
            d.close()
        except Exception:
            pass


def available() -> bool:
    """python-xlib importable and an X display reachable."""
    try:
        _get_display()
        return True
    except Exception:
        _drop_display()
        return False


def confine(ghost_wid: int, game_wid: int) -> bool:
    """Stack ghost_wid directly above game_wid: WM_TRANSIENT_FOR ->
    game_wid, skip-taskbar/pager/switcher, clear demands-attention, then
    restack the ghost to sit immediately above the game (see module
    docstring: the transient constraint alone never LOWERS a fresh map).
    Only valid on a MAPPED ghost window. Returns False on any X error; the
    connection is dropped for a lazy reopen."""
    try:
        from Xlib import X, Xatom
        from Xlib.protocol import event as xevent

        d = _get_display()
        ghost = d.create_resource_object("window", int(ghost_wid))
        ghost.change_property(d.intern_atom("WM_TRANSIENT_FOR"),
                              Xatom.WINDOW, 32, [int(game_wid)])

        root = d.screen().root
        redirect = X.SubstructureRedirectMask | X.SubstructureNotifyMask

        def send_message(type_name, data):
            ev = xevent.ClientMessage(
                window=ghost, client_type=d.intern_atom(type_name),
                data=(32, data))
            root.send_event(ev, event_mask=redirect)

        def send_state(action, *names):
            atoms = [d.intern_atom(n) for n in names]
            # data.l = [action, atom1, atom2, source(1=application), 0]
            send_message("_NET_WM_STATE", ([action] + atoms + [1, 0, 0])[:5])

        send_state(_ADD, "_NET_WM_STATE_SKIP_TASKBAR",
                   "_NET_WM_STATE_SKIP_PAGER")
        send_state(_ADD, "_KDE_NET_WM_STATE_SKIP_SWITCHER")
        send_state(_REMOVE, "_NET_WM_STATE_DEMANDS_ATTENTION")
        # data.l = [source(2=pager/user), sibling, detail, 0, 0]
        send_message("_NET_RESTACK_WINDOW",
                     [2, int(game_wid), X.Above, 0, 0])
        d.flush()
        return True
    except Exception:
        _drop_display()
        return False
