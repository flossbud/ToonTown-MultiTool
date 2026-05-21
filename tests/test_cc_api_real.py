"""Orchestration tests for the rewritten cc_api.

Mocks CCLauncher.get_stdout_path_for_pid + the window->PID resolver,
points cc_api at a tempfile with canned content, asserts CCToonInfo
fields end-to-end.
"""

import threading
from pathlib import Path

import pytest

from utils import cc_api
from utils.cc_toon_info import CCToonInfo


CANNED_LOG = """
:audio: Using default OpenAL device
__handleAvatarChooserDone: 101194667, 'Flossbud', ('dss', 'ls', 'm', 'f', (0.0, 0.403921, 0.647058, 1.0), (1.0, 1.0, 1.0, 1.0), (0.0, 0.403921, 0.647058, 1.0), (0.0, 0.403921, 0.647058, 1.0), 263, 27, 236, 27, 155, 27, (0.0, 0.403921, 0.647058, 1.0), 0, 0), 0
:ToontownClientRepository: enterPlayGame hoodId:2000 zoneId:2000 avId:101194667
"""


def _sync_threaded_call(num_slots, window_ids):
    """Call cc_api.get_toon_data_threaded and block until the callback
    fires. Returns the list[CCToonInfo | None] passed to the callback."""
    done = threading.Event()
    captured: list = []

    def cb(infos):
        captured.extend(infos)
        done.set()

    cc_api.get_toon_data_threaded(num_slots, window_ids, cb)
    assert done.wait(timeout=5.0), "callback never fired"
    return captured


def test_returns_filled_toon_info_when_stdout_available(tmp_path, monkeypatch):
    log = tmp_path / "stdout.log"
    log.write_text(CANNED_LOG)

    monkeypatch.setattr(cc_api, "_resolve_pid_for_window", lambda wid: 12345)
    monkeypatch.setattr(
        cc_api, "_get_stdout_path_for_pid", lambda pid: log if pid == 12345 else None
    )

    infos = _sync_threaded_call(1, ["window_a"])
    assert len(infos) == 1
    info = infos[0]
    assert isinstance(info, CCToonInfo)
    assert info.name == "Flossbud"
    assert info.head_code == "dss"
    assert info.species_letter == "d"
    assert info.species_name == "DOG"
    assert info.species_emoji == "\U0001f436"
    assert info.playground == "Toontown Central"
    # zone_id == hood_id -> no specific street
    assert info.zone_name is None


def test_returns_empty_info_when_no_stdout_path(monkeypatch):
    monkeypatch.setattr(cc_api, "_resolve_pid_for_window", lambda wid: 12345)
    monkeypatch.setattr(cc_api, "_get_stdout_path_for_pid", lambda pid: None)

    infos = _sync_threaded_call(1, ["window_b"])
    assert len(infos) == 1
    # All fields None -- external-launch degradation
    assert infos[0].name is None
    assert infos[0].playground is None


def test_returns_empty_info_when_pid_unresolvable(monkeypatch):
    monkeypatch.setattr(cc_api, "_resolve_pid_for_window", lambda wid: None)

    infos = _sync_threaded_call(1, ["window_c"])
    assert len(infos) == 1
    assert infos[0].name is None


def test_returns_none_for_padding_slots(monkeypatch):
    monkeypatch.setattr(cc_api, "_resolve_pid_for_window", lambda wid: None)

    # Caller asks for 4 slots but only passes 1 window
    infos = _sync_threaded_call(4, ["window_d"])
    assert len(infos) == 4
    # Slot 0 has a window (Nones from no PID); 1-3 are None
    assert isinstance(infos[0], CCToonInfo)
    assert infos[1] is None
    assert infos[2] is None
    assert infos[3] is None


def test_zone_name_resolves_when_zone_table_has_entry(tmp_path, monkeypatch):
    from utils import cc_zones
    monkeypatch.setitem(cc_zones.ZONE_ID_TO_NAME, 2100, "Loopy Lane")

    log = tmp_path / "stdout.log"
    log.write_text(
        CANNED_LOG
        + ":ToontownClientRepository: enterPlayGame hoodId:2000 zoneId:2100 avId:101194667\n"
    )

    monkeypatch.setattr(cc_api, "_resolve_pid_for_window", lambda wid: 12345)
    monkeypatch.setattr(cc_api, "_get_stdout_path_for_pid", lambda pid: log)

    infos = _sync_threaded_call(1, ["window_e"])
    assert infos[0].playground == "Toontown Central"
    assert infos[0].zone_name == "Loopy Lane"
