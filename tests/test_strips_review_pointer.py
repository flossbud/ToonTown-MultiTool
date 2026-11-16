"""Broken X11 probes relinquish their resources and can reconnect."""
from utils.strips.popovers.pointer_watch import PointerWatch, _X11Probe


def test_probe_closes_display_even_if_ungrab_fails():
    closed = []
    probe = _X11Probe.__new__(_X11Probe)
    class Display:
        def close(self):
            closed.append(True)
    probe.d = Display()
    def fail(_):
        raise OSError('broken connection')
    probe.grab_escape = fail
    probe.close()
    assert closed == [True]


class Probe:
    broken = False
    closed = False
    def buttons_down(self):
        if self.broken:
            raise OSError('connection lost')
        return False
    def escape_pressed(self):
        return False
    def grab_escape(self, on):
        pass
    def close(self):
        self.closed = True


def test_poll_failure_dismisses_and_discards_dead_probe(qapp, monkeypatch):
    probe = Probe()
    watch = PointerWatch(probe=probe)
    escaped = []
    watch.escape.connect(lambda: escaped.append(True))
    watch.watch(lambda _: True)
    probe.broken = True
    watch.tick()
    assert escaped == [True]
    assert probe.closed
    assert not watch.is_watching()
    replacement = Probe()
    monkeypatch.setattr('utils.strips.popovers.pointer_watch._make_probe', lambda: replacement)
    watch.watch(lambda _: True)
    assert watch._probe is replacement
    assert watch.is_watching()
    watch.shutdown()
    watch.shutdown()
    assert replacement.closed
