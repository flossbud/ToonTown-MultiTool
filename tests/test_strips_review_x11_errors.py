"""Request completion and BadWindow handling on a private X server."""
import os
import select
import shutil
import subprocess

import pytest

from utils import x11_transient


@pytest.fixture
def xdisplay(monkeypatch):
    pytest.importorskip('Xlib')
    if not shutil.which('Xvfb'):
        pytest.skip('private Xvfb required')
    from Xlib import display
    read_fd, write_fd = os.pipe()
    server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0',
                               '800x600x24', '-nolisten', 'tcp'],
                              pass_fds=(write_fd,), stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    os.close(write_fd)
    d = None
    try:
        assert select.select([read_fd], [], [], 5)[0], 'Xvfb did not become ready'
        number = os.read(read_fd, 32).decode().strip()
        d = display.Display(':' + number)
        monkeypatch.setattr(x11_transient, '_display', d)
        yield d
    finally:
        if d is not None:
            try:
                d.close()
            except Exception:
                pass
        os.close(read_fd)
        server.terminate()
        server.wait(5)


def window(d):
    from Xlib import X
    return d.screen().root.create_window(0, 0, 100, 100, 0, X.CopyFromParent,
                                          X.InputOutput, X.CopyFromParent)


@pytest.mark.parametrize('destroyed', ['overlay', 'game'])
def test_destroyed_window_returns_false_without_unhandled_x_error(xdisplay, destroyed):
    d = xdisplay
    overlay, game = window(d), window(d)
    (overlay if destroyed == 'overlay' else game).destroy()
    d.sync()
    unhandled = []
    def handler(*args):
        unhandled.append(args)
    d.set_error_handler(handler)
    assert x11_transient.confine(overlay.id, game.id) is False
    assert d.display.error_handler is handler
    assert unhandled == []


def test_valid_confine_keeps_property_messages_and_error_handler(xdisplay):
    from Xlib import X, Xatom
    d = xdisplay
    overlay, game = window(d), window(d)
    root = d.screen().root
    root.change_attributes(event_mask=X.SubstructureNotifyMask)
    overlay.map()
    game.map()
    d.sync()
    while d.pending_events():
        d.next_event()
    handler = lambda *_: None
    d.set_error_handler(handler)
    assert x11_transient.confine(overlay.id, game.id) is True
    assert d.display.error_handler is handler
    prop = overlay.get_full_property(d.intern_atom('WM_TRANSIENT_FOR'), Xatom.WINDOW)
    assert list(prop.value) == [game.id]
    events = []
    while d.pending_events():
        event = d.next_event()
        if event.type == X.ClientMessage:
            events.append(event)
    assert [d.get_atom_name(e.client_type) for e in events] == [
        '_NET_WM_STATE', '_NET_WM_STATE', '_NET_WM_STATE', '_NET_RESTACK_WINDOW']
    assert list(events[-1].data[1]) == [2, game.id, X.Above, 0, 0]
