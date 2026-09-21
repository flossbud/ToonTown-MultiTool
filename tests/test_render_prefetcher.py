# tests/test_render_prefetcher.py
"""Queue order, in-flight cap, breaker trip/probe/close, signals — with a
synchronous executor and a scripted downloader. No network."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from concurrent.futures import Future

import pytest

from utils.rendition_poses import DownloadError
from utils.render_prefetcher import (
    BACKOFF_S, BREAKER_THRESHOLD, PRIORITY_DISCOVERED, PRIORITY_SWEEP,
    PRIORITY_WANT, RenderPrefetcher,
)
from utils.toon_render_store import PNG_SIGNATURE, ToonRenderStore

POSES = ("portrait", "head", "waving")
PNG = PNG_SIGNATURE + b"ok"


class _Immediate:
    """Runs submit() synchronously. The prefetcher's result signal is queued,
    so delivery still happens on processEvents — deterministic ordering."""
    def submit(self, fn, *a):
        f = Future()
        try:
            f.set_result(fn(*a))
        except Exception as exc:                        # noqa: BLE001
            f.set_exception(exc)
        return f


class _Downloader:
    """Scripted: `outcomes[(dna, pose)]` is PNG bytes or a DownloadError kind."""
    def __init__(self, outcomes=None, default=PNG):
        self.outcomes = dict(outcomes or {})
        self.default = default
        self.calls = []

    def __call__(self, dna, pose):
        self.calls.append((dna, pose))
        out = self.outcomes.get((dna, pose), self.default)
        if isinstance(out, str):
            raise DownloadError(out, 524 if out == "server" else (404 if out == "client" else None))
        return out


@pytest.fixture
def rig(qapp, tmp_path):
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    dl = _Downloader()
    # max_in_flight=1 makes the attempt count deterministic: with a
    # synchronous executor, N in flight means N attempts land per pump.
    pf = RenderPrefetcher(store, downloader=dl, executor=_Immediate(), max_in_flight=1)
    landed, promoted, breaker = [], [], []
    pf.render_landed.connect(lambda g, n, p: landed.append((g, n, p)))
    pf.set_promoted.connect(lambda g, n: promoted.append((g, n)))
    pf.breaker_changed.connect(breaker.append)
    return store, dl, pf, landed, promoted, breaker


def _drain(qapp, pf, rounds=20):
    for _ in range(rounds):
        qapp.processEvents()
        if pf.pending_count == 0 and pf.in_flight_count == 0:
            break


def test_discovery_fetches_every_missing_pose_and_promotes(rig, qapp):
    store, dl, pf, landed, promoted, breaker = rig
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    assert sorted(p for _, p in dl.calls) == sorted(POSES)
    assert sorted(landed) == sorted(("ttr", "Hiro", p) for p in POSES)
    assert promoted == [("ttr", "Hiro")]
    assert store.current_dna("ttr", "Hiro") == "dna1"
    assert breaker == []


def test_discovery_of_the_current_dna_downloads_nothing(rig, qapp):
    store, dl, pf, *_ = rig
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    dl.calls.clear()
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    assert dl.calls == []


def test_in_flight_cap_is_respected(qapp, tmp_path):
    """A blocking executor exposes the cap: only max_in_flight submitted."""
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    submitted = []

    class _Hold:
        def submit(self, fn, *a):
            submitted.append(a)
            return Future()                             # never completes

    pf = RenderPrefetcher(store, downloader=_Downloader(), executor=_Hold(), max_in_flight=2)
    pf.discovered("ttr", "Hiro", "dna1")
    qapp.processEvents()
    assert len(submitted) == 2
    assert pf.pending_count == 1
    assert pf.in_flight_count == 2


def test_want_jumps_ahead_of_sweep_work(qapp, tmp_path):
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    submitted = []

    class _Hold:
        def submit(self, fn, *a):
            submitted.append(a)
            return Future()

    pf = RenderPrefetcher(store, downloader=_Downloader(), executor=_Hold(), max_in_flight=1)
    pf.sweep([("ttr", "Sleepy", "dnaS")])            # 3 sweep-priority items, 1 goes in flight
    pf.discovered("ttr", "Hiro", "dna1")             # 3 discovered-priority items queued
    pf.want("ttr", "Hiro", "head")                   # bumps that one to the front
    order = [(a[1], a[3]) for a in submitted]        # (name, pose) submitted so far
    assert order == [("Sleepy", "portrait")]
    # simulate the in-flight one finishing so the next pops
    pf._on_result("ttr", "Sleepy", "dnaS", "portrait", PNG, None)
    qapp.processEvents()
    assert (submitted[1][1], submitted[1][3]) == ("Hiro", "head")


def test_a_4xx_marks_the_pose_failed_and_is_not_a_breaker_event(rig, qapp):
    store, dl, pf, landed, promoted, breaker = rig
    dl.outcomes[("dna1", "waving")] = "client"
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    assert pf.breaker_open is False
    assert breaker == []
    assert "waving" not in store.missing_poses("ttr", "Hiro", "dna1")
    assert promoted == []                             # 2/3 landed: not complete


def test_breaker_opens_after_three_consecutive_failures_and_stops_downloading(rig, qapp):
    store, dl, pf, landed, promoted, breaker = rig
    dl.default = "timeout"
    pf.discovered("ttr", "Hiro", "dna1")
    pf.discovered("ttr", "Blue", "dna2")
    _drain(qapp, pf)
    assert pf.breaker_open is True
    assert breaker == [True]
    assert len(dl.calls) == BREAKER_THRESHOLD            # exactly three attempts, then silence
    assert pf.pending_count == 6                          # everything re-queued, nothing dropped
    assert pf.probe_interval_ms == BACKOFF_S[0] * 1000


def test_probe_backs_off_then_one_success_closes_and_drains(rig, qapp):
    store, dl, pf, landed, promoted, breaker = rig
    dl.default = "server"
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    assert pf.breaker_open is True
    for i, expected in enumerate(BACKOFF_S[1:] + (BACKOFF_S[-1],)):
        pf.fire_probe_now()                               # one probe download
        _drain(qapp, pf)
        assert pf.breaker_open is True
        assert pf.probe_interval_ms == expected * 1000    # 60, 120, 300, 300 (capped)
    dl.default = PNG                                      # origin recovers
    pf.fire_probe_now()
    _drain(qapp, pf)
    assert pf.breaker_open is False
    assert breaker == [True, False]
    assert store.current_dna("ttr", "Hiro") == "dna1"     # queue drained, set complete
    assert promoted == [("ttr", "Hiro")]


def test_invalidate_requeues_the_current_set_at_high_priority(rig, qapp):
    store, dl, pf, landed, promoted, breaker = rig
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    dl.calls.clear()
    pf.invalidate("ttr", "Hiro")
    assert pf.pending_count + pf.in_flight_count <= len(POSES)
    _drain(qapp, pf)
    assert sorted(p for _, p in dl.calls) == sorted(POSES)
    assert store.current_dna("ttr", "Hiro") == "dna1"
    assert promoted == [("ttr", "Hiro"), ("ttr", "Hiro")]


def test_corrupt_bytes_count_as_a_failure_not_a_landing(rig, qapp):
    store, dl, pf, landed, promoted, breaker = rig
    dl.outcomes[("dna1", "head")] = b"not png"
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    assert ("ttr", "Hiro", "head") not in landed
    assert "head" in store.missing_poses("ttr", "Hiro", "dna1")


def test_a_4xx_probe_probes_the_next_item_instead_of_stranding_the_breaker(rig, qapp):
    """A 4xx is an answer, not a stall: it cannot close the breaker (only a
    success may) but it must not leave it open with no probe and no timer."""
    store, dl, pf, landed, promoted, breaker = rig
    dl.default = "timeout"
    pf.discovered("ttr", "Hiro", "dna1")              # one cold pose trips the breaker
    _drain(qapp, pf)
    assert pf.breaker_open is True
    pf.discovered("ttr", "Blue", "dna2")              # queued behind the breaker...
    pf.want("ttr", "Blue", "head")                    # ...and first in line after the probe
    dl.outcomes[("dna1", "portrait")] = "client"      # the probe: server refuses the pose
    dl.default = PNG                                  # everything after it succeeds
    pf.fire_probe_now()                               # the only manual probe
    _drain(qapp, pf)
    assert dl.calls[BREAKER_THRESHOLD] == ("dna1", "portrait")      # the 404 probe
    assert dl.calls[BREAKER_THRESHOLD + 1] == ("dna2", "head")      # probed next, unprompted
    assert pf.breaker_open is False
    assert breaker == [True, False]
    assert "portrait" not in store.missing_poses("ttr", "Hiro", "dna1")
    assert store.current_dna("ttr", "Blue") == "dna2"               # queue drained
    assert pf.pending_count == 0

    # Degenerate: the 404 probe was the only queued item. Nothing is left to
    # probe and the origin answered, so the breaker closes on an empty queue.
    store.note_dna("ttr", "Solo", "dna3")
    for pose in ("head", "waving"):
        store.mark_failed("ttr", "Solo", "dna3", pose)   # only portrait is missing
    dl.default = "timeout"
    pf.discovered("ttr", "Solo", "dna3")
    _drain(qapp, pf)
    assert pf.breaker_open is True
    assert pf.pending_count == 1
    dl.outcomes[("dna3", "portrait")] = "client"
    pf.fire_probe_now()
    _drain(qapp, pf)
    assert pf.breaker_open is False
    assert pf.pending_count == 0
    assert breaker == [True, False, True, False]


def test_probe_timer_re_arms_while_a_straggler_is_in_flight(qapp, tmp_path):
    """Open with a download still out: the probe timer must never be left
    stopped with no probe in flight — that state can only be woken by hand."""
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    submitted = []

    class _Hold:
        def submit(self, fn, *a):
            submitted.append(a)
            return Future()

    pf = RenderPrefetcher(store, downloader=_Downloader(), executor=_Hold(), max_in_flight=2)
    pf.discovered("ttr", "Hiro", "dna1")             # portrait + head in flight, waving queued
    straggler = submitted[0]
    timeout = DownloadError("timeout")
    for _ in range(BREAKER_THRESHOLD):                # head fails three times -> open
        pf._on_result("ttr", "Hiro", "dna1", "head", None, timeout)
    assert pf.breaker_open is True
    assert pf.in_flight_count == 1                    # the straggler is still out
    assert pf._probe.isActive()
    pf.fire_probe_now()                               # timer fires with the straggler out
    assert pf._probe.isActive()                       # re-armed, not dropped
    pf._on_result(*straggler, None, timeout)          # the straggler fails too
    assert pf.breaker_open is True
    assert pf.in_flight_count == 0
    assert pf._probe.isActive()
    assert not (pf.breaker_open and not pf._probe.isActive() and pf._probe_key is None)


def test_outfit_change_mid_download_purges_and_ignores_the_old_dna(qapp, tmp_path):
    """The store dropped set A the moment B was noted; the prefetcher must not
    fetch A's remaining poses ahead of B nor write A's in-flight bytes back."""
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    submitted = []

    class _Hold:
        def submit(self, fn, *a):
            submitted.append(a)
            return Future()

    pf = RenderPrefetcher(store, downloader=_Downloader(), executor=_Hold(), max_in_flight=1)
    landed = []
    pf.render_landed.connect(lambda g, n, p: landed.append((g, n, p)))
    pf.discovered("ttr", "Hiro", "dnaA")             # A/portrait in flight, A/head + A/waving queued
    assert [a[2] for a in submitted] == ["dnaA"]
    pf.discovered("ttr", "Hiro", "dnaB")             # outfit changed before A finished
    assert store.candidate_dna("ttr", "Hiro") == "dnaB"
    assert all(k[2] == "dnaB" for k in pf._queue)    # A's queued work is gone
    assert pf.pending_count == len(POSES)
    # A's held download lands: real bytes for an outfit the store no longer tracks.
    pf._on_result(*submitted[0], PNG, None)
    toon_dir = store.toon_dir("ttr", "Hiro")
    assert not os.path.isdir(os.path.join(toon_dir, "dnaA"))
    with open(os.path.join(toon_dir, "manifest.json")) as f:
        assert "dnaA" not in json.load(f)["sets"]
    assert landed == []
    assert submitted[1][2] == "dnaB"                  # the pump moved on to B
