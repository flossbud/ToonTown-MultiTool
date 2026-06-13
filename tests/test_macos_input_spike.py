import collections
import dataclasses
import importlib.util
import pathlib
import sys
import types

import pytest

_SPIKE = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "macos_input_spike.py"
_spec = importlib.util.spec_from_file_location("macos_input_spike", _SPIKE)
spike = importlib.util.module_from_spec(_spec)
# Register before exec so the frozen dataclass's annotation resolution can find
# the module namespace (dataclasses looks up sys.modules[cls.__module__]).
sys.modules[_spec.name] = spike
_spec.loader.exec_module(spike)


# ── Task 2: module imports cleanly without PyObjC ────────────────────────────
def test_module_imports_without_pyobjc():
    # The module must import on any platform: PyObjC is imported lazily, never
    # at module top level, so the pure-logic helpers are testable on Linux CI.
    assert hasattr(spike, "main")
    assert callable(spike.main)


def test_main_no_args_and_unknown_return_2():
    assert spike.main([]) == 2
    assert spike.main(["bogus-command"]) == 2


@pytest.mark.parametrize("cmd,func", [
    ("list", "cmd_list"), ("inject", "cmd_inject"), ("loop", "cmd_loop"),
    ("type", "cmd_type"), ("map", "cmd_map"),
])
def test_main_routes_every_command_and_forwards_args(monkeypatch, cmd, func):
    # Routing is verified independently of each command's real body: every known
    # command dispatches to its handler and forwards the remaining argv.
    calls = []
    monkeypatch.setattr(spike, func, lambda rest: (calls.append(rest), 0)[1])
    assert spike.main([cmd, "x", "y"]) == 0
    assert calls == [["x", "y"]]


# ── Task 8: preflight fallback + cmd_list branching (monkeypatched, no PyObjC) ─
def test_preflight_screen_recording_true_when_api_absent(monkeypatch):
    # Older macOS lacks CGPreflightScreenCaptureAccess -> tolerant default True.
    monkeypatch.setattr(spike, "_quartz", lambda: types.SimpleNamespace())
    assert spike.preflight_screen_recording() is True


def test_preflight_screen_recording_reflects_api_when_present(monkeypatch):
    monkeypatch.setattr(spike, "_quartz",
                        lambda: types.SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: False))
    assert spike.preflight_screen_recording() is False
    monkeypatch.setattr(spike, "_quartz",
                        lambda: types.SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: True))
    assert spike.preflight_screen_recording() is True


def _stub_preflights(monkeypatch, *, post=True, listen=True, screen=True):
    monkeypatch.setattr(spike, "preflight_post_access", lambda: post)
    monkeypatch.setattr(spike, "preflight_listen_access", lambda: listen)
    monkeypatch.setattr(spike, "preflight_screen_recording", lambda: screen)


def test_cmd_list_no_windows_screen_recording_hint(monkeypatch, capsys):
    _stub_preflights(monkeypatch, screen=False)
    monkeypatch.setattr(spike, "frontmost_pid", lambda: 555)
    monkeypatch.setattr(spike, "enumerate_windows", lambda: [])
    assert spike.cmd_list([]) == 1
    assert "Screen Recording" in capsys.readouterr().out


def test_cmd_list_no_windows_launch_hint(monkeypatch, capsys):
    _stub_preflights(monkeypatch, screen=True)
    monkeypatch.setattr(spike, "frontmost_pid", lambda: 555)
    monkeypatch.setattr(spike, "enumerate_windows", lambda: [])
    assert spike.cmd_list([]) == 1
    assert "Launch Toontown Rewritten" in capsys.readouterr().out


def test_cmd_list_marks_frontmost_window(monkeypatch, capsys):
    _stub_preflights(monkeypatch)
    recs = [
        spike.WindowRecord(101, 11, "Toontown Rewritten", (0, 0, 800, 600), "com.x"),
        spike.WindowRecord(202, 22, "Toontown Rewritten", (0, 0, 800, 600), "com.x"),
    ]
    monkeypatch.setattr(spike, "frontmost_pid", lambda: 202)
    monkeypatch.setattr(spike, "enumerate_windows", lambda: recs)
    assert spike.cmd_list([]) == 0
    out = capsys.readouterr().out
    assert "pid=101" in out and "pid=202" in out
    # Exactly the frontmost (202) line carries the marker.
    front_lines = [ln for ln in out.splitlines() if "<FRONT>" in ln]
    assert len(front_lines) == 1 and "pid=202" in front_lines[0]


# ── Task 9: pid re-validation + tagged posting (fake Quartz, no PyObjC) ───────
def _ttr(pid, wid, bundle="com.x"):
    return spike.WindowRecord(pid, wid, "Toontown Rewritten", (0, 0, 800, 600), bundle)


def test_pid_alive_and_ttr_matches_and_checks_bundle(monkeypatch):
    monkeypatch.setattr(spike, "enumerate_windows", lambda: [_ttr(101, 11, "com.ttr")])
    assert spike.pid_alive_and_ttr(101, 11) is True                      # no bundle check
    assert spike.pid_alive_and_ttr(101, 11, "com.ttr") is True           # bundle matches
    assert spike.pid_alive_and_ttr(101, 11, "com.evil") is False         # PID reused
    assert spike.pid_alive_and_ttr(101, 99) is False                     # window gone
    assert spike.pid_alive_and_ttr(999, 11) is False                     # pid gone


class _FakeQuartz:
    kCGEventSourceUserData = "ud"
    kCGEventSourceStateCombinedSessionState = "combined"
    kCGEventSourceStatePrivate = "private"

    def __init__(self):
        self.posts = []
        self.tagged = []
        self.flagged = []

    def CGEventSourceCreate(self, state):
        return ("src", state)

    def CGEventCreateKeyboardEvent(self, src, vk, down):
        return {"src": src, "vk": vk, "down": down}

    def CGEventSetIntegerValueField(self, ev, field, val):
        self.tagged.append((field, val))

    def CGEventSetFlags(self, ev, flags):
        self.flagged.append(flags)

    def CGEventPostToPid(self, pid, ev):
        self.posts.append((pid, ev))


def test_post_key_refuses_without_access(monkeypatch):
    monkeypatch.setattr(spike, "_quartz", lambda: _FakeQuartz())
    monkeypatch.setattr(spike, "preflight_post_access", lambda: False)
    assert spike.post_key(101, 11, "w", True) is False


def test_post_key_refuses_stale_target(monkeypatch):
    fq = _FakeQuartz()
    monkeypatch.setattr(spike, "_quartz", lambda: fq)
    monkeypatch.setattr(spike, "preflight_post_access", lambda: True)
    monkeypatch.setattr(spike, "enumerate_windows", lambda: [])  # target gone
    assert spike.post_key(101, 11, "w", True) is False
    assert fq.posts == []


def test_post_key_happy_path_tags_and_posts(monkeypatch):
    fq = _FakeQuartz()
    monkeypatch.setattr(spike, "_quartz", lambda: fq)
    monkeypatch.setattr(spike, "preflight_post_access", lambda: True)
    monkeypatch.setattr(spike, "enumerate_windows", lambda: [_ttr(101, 11, "com.ttr")])
    assert spike.post_key(101, 11, "w", False, state_name="private", flags=0x20000,
                          expected_bundle="com.ttr") is True
    assert fq.posts and fq.posts[0][0] == 101
    ev = fq.posts[0][1]
    assert ev["vk"] == spike.vk_for_key("w")
    assert ev["down"] is False                                  # down forwarded
    assert ev["src"] == ("src", "private")                     # source selected
    assert (fq.kCGEventSourceUserData, spike.SPIKE_EVENT_TAG) in fq.tagged
    assert fq.flagged == [0x20000]                             # flags applied


def test_event_source_maps_states_and_rejects_hid(monkeypatch):
    monkeypatch.setattr(spike, "_quartz", lambda: _FakeQuartz())
    assert spike._event_source("none") is None
    assert spike._event_source("combined") == ("src", "combined")
    assert spike._event_source("private") == ("src", "private")
    with pytest.raises(KeyError):
        spike._event_source("hid")


# ── Task 10: _parse_opts (pure arg parser) ───────────────────────────────────
def test_parse_opts_defaults_and_overrides():
    defaults = {"key": (str, "w"), "reps": (int, 30), "state": (str, "combined")}
    pos, opts = spike._parse_opts(["10", "20", "--key", "a", "--reps", "5"], defaults)
    assert pos == ["10", "20"]
    assert opts == {"key": "a", "reps": 5, "state": "combined"}


def test_parse_opts_unknown_flag_raises():
    with pytest.raises(SystemExit):
        spike._parse_opts(["--bogus", "1"], {"key": (str, "w")})


def test_parse_opts_missing_value_raises():
    with pytest.raises(SystemExit):
        spike._parse_opts(["--key"], {"key": (str, "w")})
    # A following flag is not silently consumed as the value.
    with pytest.raises(SystemExit):
        spike._parse_opts(["--key", "--reps"], {"key": (str, "w"), "reps": (int, 1)})


def test_cmd_inject_rejects_bad_args_before_pyobjc():
    # These early returns must not touch enumerate_windows (no PyObjC needed).
    assert spike.cmd_inject(["1"]) == 2                         # wrong arg count
    assert spike.cmd_inject(["1", "2", "--state", "hid"]) == 2  # invalid state
    assert spike.cmd_inject(["5", "5"]) == 2                    # identical pids


# ── Task 11b: _modifier_mask + cmd_type early validation ─────────────────────
def test_modifier_mask_ors_flags(monkeypatch):
    fakeq = types.SimpleNamespace(
        kCGEventFlagMaskShift=0x1, kCGEventFlagMaskControl=0x2, kCGEventFlagMaskAlternate=0x4)
    monkeypatch.setattr(spike, "_quartz", lambda: fakeq)
    assert spike._modifier_mask([]) == 0
    assert spike._modifier_mask(["shift"]) == 0x1
    assert spike._modifier_mask(["shift", "option"]) == 0x5


def test_cmd_type_rejects_bad_args_before_pyobjc():
    assert spike.cmd_type(["123"]) == 2                                  # wrong arg count
    assert spike.cmd_type(["123", "hi", "--state", "hid"]) == 2          # invalid state
    assert spike.cmd_type(["123", "hi", "--mods", "command"]) == 2       # invalid modifier


# ── Task 3: keycode map ──────────────────────────────────────────────────────
def test_vk_for_key_movement_and_specials():
    assert spike.vk_for_key("w") == 0x0D
    assert spike.vk_for_key("a") == 0x00
    assert spike.vk_for_key("s") == 0x01
    assert spike.vk_for_key("d") == 0x02
    assert spike.vk_for_key("up") == 0x7E
    assert spike.vk_for_key("down") == 0x7D
    assert spike.vk_for_key("left") == 0x7B
    assert spike.vk_for_key("right") == 0x7C
    assert spike.vk_for_key("return") == 0x24
    assert spike.vk_for_key("escape") == 0x35
    assert spike.vk_for_key("delete") == 0x33
    assert spike.vk_for_key("space") == 0x31


def test_vk_for_key_is_case_insensitive():
    assert spike.vk_for_key("W") == spike.vk_for_key("w")


def test_vk_for_key_unknown_raises():
    with pytest.raises(KeyError):
        spike.vk_for_key("f24-nonexistent")


# ── Task 4: TTR window identification ────────────────────────────────────────
def _win(pid, num, name, x=0, y=0, w=800, h=600, title=None):
    d = {
        "kCGWindowOwnerPID": pid,
        "kCGWindowNumber": num,
        "kCGWindowOwnerName": name,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h},
    }
    if title is not None:
        d["kCGWindowName"] = title
    return d


def test_identify_ttr_windows_matches_owner_name():
    info = [
        _win(101, 11, "Toontown Rewritten", w=800, h=600),
        _win(202, 22, "Finder"),
        _win(101, 12, "Toontown Rewritten", w=640, h=480, title="TTR"),
    ]
    recs = spike.identify_ttr_windows(info)
    assert [(r.pid, r.window_id) for r in recs] == [(101, 11), (101, 12)]
    assert recs[0].bounds == (0, 0, 800, 600)
    assert recs[0].owner == "Toontown Rewritten"


def test_identify_ttr_windows_ignores_zero_size_and_missing_fields():
    info = [
        _win(101, 11, "Toontown Rewritten", w=0, h=0),   # zero-size: skip
        {"kCGWindowOwnerName": "Toontown Rewritten"},     # no pid/number: skip
    ]
    assert spike.identify_ttr_windows(info) == []


def test_identify_ttr_windows_records_are_immutable():
    rec = spike.identify_ttr_windows([_win(101, 11, "Toontown Rewritten")])[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.pid = 999


def test_identify_ttr_windows_bundle_id_defaults_none():
    rec = spike.identify_ttr_windows([_win(101, 11, "Toontown Rewritten")])[0]
    assert rec.bundle_id is None


def test_identify_ttr_windows_suffix_matches_but_not_midstring():
    info = [
        _win(101, 11, "Toontown Rewritten (Beta)"),  # suffix: matches
        _win(202, 22, "Not Toontown Rewritten Yet"),  # mid-string: excluded
    ]
    recs = spike.identify_ttr_windows(info)
    assert [r.pid for r in recs] == [101]


# ── Task 5: pynput callback compat shim ──────────────────────────────────────
def test_call_pynput_handler_one_arg_version():
    seen = []
    cb = spike.call_pynput_handler(lambda key, injected: seen.append((key, injected)))
    cb("KEY")                      # pynput 1.7 style
    assert seen == [("KEY", False)]


def test_call_pynput_handler_two_arg_version():
    seen = []
    cb = spike.call_pynput_handler(lambda key, injected: seen.append((key, injected)))
    cb("KEY", True)               # pynput 1.8 style
    assert seen == [("KEY", True)]


# ── Task 6: echo-guard tag predicate ─────────────────────────────────────────
def test_is_spike_event_matches_tag():
    assert spike.is_spike_event(spike.SPIKE_EVENT_TAG) is True


def test_is_spike_event_rejects_other_values():
    assert spike.is_spike_event(0) is False
    assert spike.is_spike_event(12345) is False


# ── Task 7: port -> PID -> window resolver ───────────────────────────────────
_Conn = collections.namedtuple("_Conn", "pid laddr status")
_Addr = collections.namedtuple("_Addr", "ip port")


def test_resolve_port_pid_window_maps_ttr_ports():
    windows = [
        spike.WindowRecord(pid=101, window_id=11, owner="Toontown Rewritten", bounds=(0, 0, 800, 600)),
        spike.WindowRecord(pid=202, window_id=22, owner="Toontown Rewritten", bounds=(0, 0, 800, 600)),
    ]
    conns = [
        _Conn(pid=101, laddr=_Addr("127.0.0.1", 7000), status="LISTEN"),
        _Conn(pid=202, laddr=_Addr("::1", 7001), status="LISTEN"),
        _Conn(pid=999, laddr=_Addr("127.0.0.1", 8080), status="LISTEN"),  # not TTR
        _Conn(pid=101, laddr=_Addr("127.0.0.1", 5555), status="ESTABLISHED"),  # not listening
    ]
    mapping = spike.resolve_port_pid_window(conns, windows)
    assert mapping == {7000: (101, 11), 7001: (202, 22)}


def test_resolve_port_pid_window_ignores_no_laddr():
    windows = [spike.WindowRecord(pid=101, window_id=11, owner="Toontown Rewritten", bounds=(0, 0, 1, 1))]
    conns = [_Conn(pid=101, laddr=(), status="LISTEN")]
    assert spike.resolve_port_pid_window(conns, windows) == {}


def test_resolve_port_pid_window_excludes_non_loopback():
    windows = [spike.WindowRecord(pid=101, window_id=11, owner="Toontown Rewritten", bounds=(0, 0, 1, 1))]
    conns = [
        _Conn(pid=101, laddr=_Addr("0.0.0.0", 7000), status="LISTEN"),     # wildcard: excluded
        _Conn(pid=101, laddr=_Addr("192.168.1.5", 7001), status="LISTEN"), # LAN: excluded
        _Conn(pid=101, laddr=_Addr("127.0.0.1", 7002), status="LISTEN"),   # loopback: kept
        _Conn(pid=101, laddr=_Addr("127.0.0.53", 7003), status="LISTEN"),  # 127/8 loopback: kept
    ]
    assert spike.resolve_port_pid_window(conns, windows) == {7002: (101, 11), 7003: (101, 11)}
