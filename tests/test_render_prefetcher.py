# tests/test_render_prefetcher.py
"""Queue order, in-flight cap, breaker trip/probe/close, signals — with a
synchronous executor and a scripted downloader. No network."""
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
