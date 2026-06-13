import collections
import importlib
import sys

mp = importlib.import_module("utils.macos_ttr_ports")

_Addr = collections.namedtuple("Addr", "ip port")
_Conn = collections.namedtuple("Conn", "laddr status")


def test_port_to_host_pid_filters_listen_and_range(monkeypatch):
    procs = {
        4242: [_Conn(_Addr("127.0.0.1", 1547), "LISTEN"),
               _Conn(_Addr("127.0.0.1", 5555), "ESTABLISHED")],
        4243: [_Conn(_Addr("127.0.0.1", 1548), "LISTEN")],
    }
    monkeypatch.setattr(mp, "_listen_ports_for_pid",
                        lambda pid: [c.laddr.port for c in procs.get(pid, [])
                                     if c.status == "LISTEN"])
    out = mp.port_to_host_pid([4242, 4243], lo=1024, hi=65535)
    assert out == {1547: 4242, 1548: 4243}


def test_port_to_host_pid_excludes_out_of_range(monkeypatch):
    monkeypatch.setattr(mp, "_listen_ports_for_pid",
                        lambda pid: [80, 1547, 70000])
    out = mp.port_to_host_pid([4242], lo=1547, hi=1552)
    assert out == {1547: 4242}  # 80 and 70000 filtered by range


def test_listen_ports_for_pid_filters_loopback_and_listen(monkeypatch):
    """_listen_ports_for_pid keeps only loopback-address LISTEN ports."""
    _FakeAddr = collections.namedtuple("Addr", "ip port")
    _FakeConn = collections.namedtuple("Conn", "laddr status")

    fake_conns = [
        _FakeConn(_FakeAddr("127.0.0.1", 1547), "LISTEN"),    # keep
        _FakeConn(_FakeAddr("::1",       1548), "LISTEN"),    # keep (IPv6 loopback)
        _FakeConn(_FakeAddr("127.0.0.1", 9999), "ESTABLISHED"),  # drop (not LISTEN)
        _FakeConn(_FakeAddr("0.0.0.0",   8080), "LISTEN"),    # drop (not loopback)
        _FakeConn(_FakeAddr("192.168.1.1", 1549), "LISTEN"),  # drop (not loopback)
    ]

    class FakeProc:
        def net_connections(self, kind):
            return fake_conns

    class FakePsutil:
        @staticmethod
        def Process(pid):
            return FakeProc()

    # _listen_ports_for_pid does `import psutil` lazily at call time, so patching
    # sys.modules is enough -- no module reload needed.
    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)

    result = mp._listen_ports_for_pid(4242)
    assert sorted(result) == [1547, 1548]


def test_listen_ports_for_pid_returns_empty_on_error(monkeypatch):
    """A psutil failure (e.g. NoSuchProcess) yields [] rather than raising into
    ttr_api's port->pid loop."""
    class _Boom:
        @staticmethod
        def Process(pid):
            raise RuntimeError("no such process")

    monkeypatch.setitem(sys.modules, "psutil", _Boom)
    assert mp._listen_ports_for_pid(999999) == []
