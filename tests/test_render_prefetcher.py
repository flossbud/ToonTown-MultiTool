# tests/test_render_prefetcher.py
"""Queue order, in-flight cap, breaker trip/probe/close, signals — with a
synchronous executor and a scripted downloader. No network."""
import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from concurrent.futures import Future, ThreadPoolExecutor

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

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


def test_sweep_refills_a_gap_in_a_current_set(rig, qapp):
    """A current set with a lost or corrupt file is refilled by the sweep,
    not only by an on-screen want: noting a current DNA must still walk
    `missing_poses` (13 stats per toon per sweep) rather than return early."""
    store, dl, pf, landed, promoted, breaker = rig
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    assert store.current_dna("ttr", "Hiro") == "dna1"
    os.remove(store.path_for("ttr", "Hiro", "dna1", "waving"))
    dl.calls.clear()
    pf.sweep([("ttr", "Hiro", "dna1")])
    assert ("ttr", "Hiro", "dna1", "waving") in pf._queue or \
           ("ttr", "Hiro", "dna1", "waving") in pf._in_flight
    _drain(qapp, pf)
    assert dl.calls == [("dna1", "waving")]                       # the gap, and only the gap
    assert store.missing_poses("ttr", "Hiro", "dna1") == []
    assert landed[-1] == ("ttr", "Hiro", "waving")


def test_in_flight_cap_is_respected(qapp, tmp_path):
    """A blocking executor exposes the cap: only max_in_flight submitted."""
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    submitted = []

    class _Hold:
        def submit(self, fn, *a):
            submitted.append(a)
            return Future()                             # never completes

    pf = RenderPrefetcher(store, downloader=_Downloader(), executor=_Hold(), max_in_flight=1)
    # A never-rendered outfit sends one canary regardless of the cap, so land
    # one pose first: the remaining two then compete for the single slot.
    store.note_dna("ttr", "Hiro", "dna1")
    with open(store.path_for("ttr", "Hiro", "dna1", "waving"), "wb") as f:
        f.write(PNG)
    store.mark_landed("ttr", "Hiro", "dna1", "waving")
    pf.discovered("ttr", "Hiro", "dna1")
    qapp.processEvents()
    assert len(submitted) == 1
    assert pf.pending_count == 1
    assert pf.in_flight_count == 1


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
    assert order == [("Sleepy", "head")]              # the sweep's canary
    # simulate the in-flight one finishing so the next pops
    pf._on_result("ttr", "Sleepy", "dnaS", "head", PNG, None)
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
    assert promoted == [("ttr", "Hiro")]              # 2 landed + 1 refused: complete
    assert store.current_dna("ttr", "Hiro") == "dna1"


def test_a_refused_final_pose_still_promotes_the_set(qapp, tmp_path):
    """Complete means every pose landed OR was refused, with at least one
    landed. When the refusal is the LAST result in, the 4xx branch is the
    only place left that can promote -- it must not just mark and move on."""
    store = ToonRenderStore(str(tmp_path), poses=("head", "portrait"))
    dl = _Downloader({("dna1", "head"): PNG, ("dna1", "portrait"): "client"})
    pf = RenderPrefetcher(store, downloader=dl, executor=_Immediate(), max_in_flight=1)
    landed, promoted = [], []
    pf.render_landed.connect(lambda g, n, p: landed.append((g, n, p)))
    pf.set_promoted.connect(lambda g, n: promoted.append((g, n)))
    pf.discovered("ttr", "Hiro", "dna1")             # head first (enqueued first), then portrait
    _drain(qapp, pf)
    assert dl.calls == [("dna1", "head"), ("dna1", "portrait")]
    assert landed == [("ttr", "Hiro", "head")]
    assert promoted == [("ttr", "Hiro")]
    assert store.current_dna("ttr", "Hiro") == "dna1"
    assert store.candidate_dna("ttr", "Hiro") is None


def test_an_outfit_refused_for_every_pose_is_dropped_and_nothing_promotes(rig, qapp):
    store, dl, pf, landed, promoted, breaker = rig
    dl.default = "client"
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    assert len(dl.calls) == len(POSES)                # each pose asked exactly once
    assert landed == []
    assert store.candidate_dna("ttr", "Hiro") is None   # abandoned, not pending forever
    assert store.current_dna("ttr", "Hiro") is None
    # Nothing was promoted, but the drop changed what consumers should show
    # (no outfit is pending any more), and it is announced exactly once.
    assert promoted == [("ttr", "Hiro")]
    assert pf.breaker_open is False and breaker == []
    assert pf.pending_count == 0 and pf.in_flight_count == 0


def test_a_dropped_dead_candidate_is_announced_so_the_previous_look_tooltip_clears(qapp, tmp_path):
    """`promote_if_complete` returns False both for "nothing changed" and for
    "abandoned an all-refused candidate". Only the second changes the served
    look (the facade's tier goes back from "previous" to "current"), and no
    consumer would repaint for it without a signal."""
    from tests._render_fixtures import complete_set
    from utils.toon_renders import ToonRenders
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    dl = _Downloader(default="client")
    pf = RenderPrefetcher(store, downloader=dl, executor=_Immediate(), max_in_flight=1)
    facade = ToonRenders(store, pf)
    promoted = []
    pf.set_promoted.connect(lambda g, n: promoted.append((g, n)))
    complete_set(store, "ttr", "Hiro", "dna1", "#ff0000", poses=POSES)
    pf.discovered("ttr", "Hiro", "dna2")
    assert facade.pixmap_for("ttr", "Hiro", "head")[1] == "previous"    # pending: tooltip case
    _drain(qapp, pf)
    assert store.candidate_dna("ttr", "Hiro") is None
    assert store.current_dna("ttr", "Hiro") == "dna1"
    assert promoted == [("ttr", "Hiro")]
    assert facade.pixmap_for("ttr", "Hiro", "head")[1] == "current"

    # And a landing that leaves the candidate still pending is silent as before.
    store.note_dna("ttr", "Hiro", "dna3")
    pf._on_result("ttr", "Hiro", "dna3", "head", PNG, None)
    assert store.candidate_dna("ttr", "Hiro") == "dna3"
    assert promoted == [("ttr", "Hiro")]


def test_breaker_opens_after_three_consecutive_failures_and_stops_downloading(rig, qapp):
    store, dl, pf, landed, promoted, breaker = rig
    dl.default = "timeout"
    pf.discovered("ttr", "Hiro", "dna1")
    pf.discovered("ttr", "Blue", "dna2")
    _drain(qapp, pf)
    assert pf.breaker_open is True
    assert breaker == [True]
    assert len(dl.calls) == BREAKER_THRESHOLD            # exactly three attempts, then silence
    assert pf.pending_count == 2                          # one canary per outfit re-queued;
                                                          # the other poses wait on them
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
    pf.discovered("ttr", "Blue", "dna2")              # queued behind the breaker, untried,
                                                      # so it is probed before Hiro's retries
    dl.outcomes[("dna2", "head")] = "client"          # the probe (Blue's canary): refused
    dl.default = PNG                                  # everything after it succeeds
    pf.fire_probe_now()                               # the only manual probe
    _drain(qapp, pf)
    assert dl.calls[BREAKER_THRESHOLD] == ("dna2", "head")          # the 404 probe
    assert dl.calls[BREAKER_THRESHOLD + 1] == ("dna2", "portrait")  # released and probed next, unprompted
    assert pf.breaker_open is False
    assert breaker == [True, False]
    assert "head" not in store.missing_poses("ttr", "Blue", "dna2")
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
    pf.discovered("ttr", "Hiro", "dna1")             # Hiro's canary (head) in flight
    pf.discovered("ttr", "Blue", "dna2")             # Blue's canary in flight beside it
    straggler = submitted[0]
    timeout = DownloadError("timeout")
    for _ in range(BREAKER_THRESHOLD):                # Blue's canary fails three times -> open
        pf._on_result("ttr", "Blue", "dna2", "head", None, timeout)
    assert pf.breaker_open is True
    assert ("ttr", "Hiro", "dna1", "head") in pf._in_flight        # the straggler is still out
    assert pf._probe.isActive()
    pf.fire_probe_now()                               # timer fires with the straggler out
    assert pf._probe.isActive()                       # re-armed, not dropped
    pf._on_result(*straggler, None, timeout)          # the straggler fails too
    assert pf.breaker_open is True
    assert ("ttr", "Hiro", "dna1", "head") not in pf._in_flight
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
    assert pf.pending_count == 1                      # B's canary; the rest wait on it
    # A's held download lands: real bytes for an outfit the store no longer tracks.
    pf._on_result(*submitted[0], PNG, None)
    toon_dir = store.toon_dir("ttr", "Hiro")
    assert not os.path.isdir(os.path.join(toon_dir, "dnaA"))
    with open(os.path.join(toon_dir, "manifest.json")) as f:
        assert "dnaA" not in json.load(f)["sets"]
    assert landed == []
    assert submitted[1][2] == "dnaB"                  # the pump moved on to B


class _ThreadRecordingDownloader(_Downloader):
    """Same scripting as `_Downloader`, plus a record of which OS thread ran
    each call — so a test can prove downloads happen off the GUI thread."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.call_threads = []

    def __call__(self, dna, pose):
        self.call_threads.append(threading.get_ident())
        return super().__call__(dna, pose)


def test_results_from_a_pool_thread_are_delivered_on_the_gui_thread(qapp, tmp_path):
    """Every other test drives the worker synchronously on the GUI thread via
    `_Immediate`. With a real `ThreadPoolExecutor`, `_worker` actually runs on
    a pool thread, and only the `_result` signal's `Qt.QueuedConnection`
    (declared in `utils/render_prefetcher.py`) hands the outcome back to
    `_on_result` — and therefore every public signal — on the GUI thread."""
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    dl = _ThreadRecordingDownloader()
    executor = ThreadPoolExecutor(max_workers=2)
    pf = RenderPrefetcher(store, downloader=dl, executor=executor, max_in_flight=2)
    landed_threads = []
    promoted = []
    # Qt.DirectConnection here on purpose: PySide's AutoConnection marshals a
    # signal back to its *owning QObject's* thread (pf lives on the GUI
    # thread) even for a plain-lambda receiver, which would silently hide a
    # broken `_result` connection type. Direct makes this recorder run on
    # whatever thread actually calls emit(), so it reports the real thread
    # `_on_result`'s body (and this emit) executed on.
    pf.render_landed.connect(
        lambda g, n, p: landed_threads.append(threading.get_ident()), Qt.DirectConnection)
    pf.set_promoted.connect(lambda g, n: promoted.append((g, n)))
    try:
        pf.discovered("ttr", "Pool Toon", "dna1")

        deadline = time.monotonic() + 5.0
        while len(promoted) < 1 and time.monotonic() < deadline:
            QTest.qWait(20)
        assert len(promoted) == 1, (
            f"set_promoted never arrived within 5s; promoted={promoted!r}, "
            f"calls={dl.calls!r}"
        )

        main_id = threading.main_thread().ident
        assert dl.call_threads, "downloader was never invoked"
        assert all(t != main_id for t in dl.call_threads), (
            "a download ran on the GUI thread instead of a pool thread: "
            f"{dl.call_threads!r} (main={main_id})"
        )
        assert landed_threads, "render_landed never fired"
        assert all(t == main_id for t in landed_threads), (
            "render_landed was delivered off the GUI thread: "
            f"{landed_threads!r} (main={main_id})"
        )
        assert len(landed_threads) == len(POSES)
        assert store.current_dna("ttr", "Pool Toon") == "dna1"
    finally:
        executor.shutdown(wait=True)


def test_the_probe_timer_fires_the_probe_without_being_poked(qapp, tmp_path):
    """Nobody calls `fire_probe_now()` in production — the single-shot probe
    `QTimer`'s own `timeout` signal must drive it (wired in `__init__` as
    `self._probe.timeout.connect(self.fire_probe_now)`)."""
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    dl = _Downloader()
    dl.outcomes[("dna1", "portrait")] = "server"        # the cold pose: 5xx
    pf = RenderPrefetcher(store, downloader=dl, executor=_Immediate(),
                           max_in_flight=1, backoff_s=(0.02,))
    breaker = []
    promoted = []
    pf.breaker_changed.connect(breaker.append)
    pf.set_promoted.connect(lambda g, n: promoted.append((g, n)))

    pf.discovered("ttr", "Timer Toon", "dna1")
    _drain(qapp, pf)
    assert pf.breaker_open is True
    calls_at_open = len(dl.calls)

    dl.outcomes.pop(("dna1", "portrait"))               # origin recovers

    # Deliberately never call fire_probe_now() — only the timer may.
    deadline = time.monotonic() + 3.0
    while pf.breaker_open and time.monotonic() < deadline:
        QTest.qWait(20)
    assert pf.breaker_open is False, (
        "breaker never closed within 3s; the probe timer's timeout -> "
        "fire_probe_now wiring looks broken"
    )

    assert len(dl.calls) > calls_at_open, "the timer never fired another probe"
    assert breaker[-1] is False
    _drain(qapp, pf)
    assert store.current_dna("ttr", "Timer Toon") == "dna1"


# ── 2026-09-22: a warm pose starved behind cold siblings ───────────────────

_KATSURO = ("portrait", "portrait-delighted", "portrait-grin", "head")
_COLD_PORTRAITS = {("dna1", p): "timeout" for p in _KATSURO[:3]}   # head stays warm (PNG)


def test_a_wanted_warm_pose_lands_even_when_cold_siblings_open_the_breaker(qapp, tmp_path):
    """Seen live: Katsuro's `head` was a Cloudflare edge HIT (0.1 s) while
    every portrait pose was cold. The card wanted `head` before the hook had
    reported the DNA, the three cold portraits opened the breaker, and the
    retried cold pose was the only thing the probe ever tried. `head` never
    landed although one request would have fetched it."""
    store = ToonRenderStore(str(tmp_path), poses=_KATSURO)
    dl = _Downloader(_COLD_PORTRAITS)
    pf = RenderPrefetcher(store, downloader=dl, executor=_Immediate(), max_in_flight=1)
    landed = []
    pf.render_landed.connect(lambda g, n, p: landed.append(p))

    pf.want("ttr", "Katsuro", "head")            # the card mounts first...
    pf.discovered("ttr", "Katsuro", "dna1")       # ...the hook reports the DNA later
    _drain(qapp, pf)

    assert "head" in landed
    assert dl.calls[0] == ("dna1", "head")         # the on-screen pose goes first
    assert pf.breaker_open is True                 # the cold ones still tripped it


def test_a_want_arriving_while_the_breaker_is_open_is_probed_at_once(qapp, tmp_path):
    """Roboroni (all cold) opened the breaker first; Katsuro's card then
    wanted its warm `head`. That must not wait for the backoff timer: an
    on-screen need is the most valuable probe there is."""
    poses = ("portrait", "head")
    store = ToonRenderStore(str(tmp_path), poses=poses)
    dl = _Downloader({("dnaR", "portrait"): "timeout", ("dnaR", "head"): "timeout",
                      ("dnaK", "portrait"): "timeout"})       # Katsuro head warm
    pf = RenderPrefetcher(store, downloader=dl, executor=_Immediate(), max_in_flight=1)
    landed = []
    pf.render_landed.connect(lambda g, n, p: landed.append((n, p)))

    pf.discovered("ttr", "Roboroni", "dnaR")
    _drain(qapp, pf)
    assert pf.breaker_open is True and landed == []

    pf.want("ttr", "Katsuro", "head")            # pending: DNA unknown yet
    pf.discovered("ttr", "Katsuro", "dnaK")
    _drain(qapp, pf)                              # no fire_probe_now(): the want itself must probe

    assert ("Katsuro", "head") in landed


def test_a_failed_pose_is_retried_only_after_every_untried_pose(qapp, tmp_path):
    """The probe is worth most when it tries something new. A pose that
    already failed goes to the back, never ahead of an untried one."""
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    dl = _Downloader({("dna1", "portrait"): "timeout"})
    pf = RenderPrefetcher(store, downloader=dl, executor=_Immediate(), max_in_flight=1)
    # Partly landed (waving), so both remaining poses queue at once rather
    # than one canary holding the other back.
    store.note_dna("ttr", "Hiro", "dna1")
    with open(store.path_for("ttr", "Hiro", "dna1", "waving"), "wb") as f:
        f.write(PNG)
    store.mark_landed("ttr", "Hiro", "dna1", "waving")
    pf.discovered("ttr", "Hiro", "dna1")
    _drain(qapp, pf)
    assert dl.calls[:2] == [("dna1", "portrait"), ("dna1", "head")]


# ── canary: one request finds out whether the origin draws an outfit ────────

def _held():
    submitted = []

    class _Hold:
        def submit(self, fn, *a):
            submitted.append(a)
            return Future()

    return submitted, _Hold()


def test_a_never_rendered_outfit_sends_one_canary_and_holds_the_rest(qapp, tmp_path):
    """Roboroni, 2026-09-22: thirteen hanging requests taught us nothing the
    first one had not. Under an open breaker each probe retries ONE pose, so
    thirteen queued poses per cold toon meant a given toon was re-tried about
    once an hour; one canary per outfit means within one backoff period."""
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    submitted, hold = _held()
    pf = RenderPrefetcher(store, downloader=_Downloader(), executor=hold, max_in_flight=3)
    pf.discovered("ttr", "Roboroni", "dnaR")
    qapp.processEvents()
    assert [(a[1], a[3]) for a in submitted] == [("Roboroni", "head")]   # CARD_POSE, one request
    assert pf.pending_count == 0                                        # nothing else queued
    pf._on_result("ttr", "Roboroni", "dnaR", "head", PNG, None)        # the origin draws it
    qapp.processEvents()
    assert sorted(a[3] for a in submitted[1:]) == sorted(p for p in POSES if p != "head")


def test_a_wanted_pose_is_the_canary(qapp, tmp_path):
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    submitted, hold = _held()
    pf = RenderPrefetcher(store, downloader=_Downloader(), executor=hold, max_in_flight=3)
    pf.want("ttr", "Roboroni", "portrait")           # a badge asked before discovery
    pf.discovered("ttr", "Roboroni", "dnaR")
    qapp.processEvents()
    assert [(a[1], a[3]) for a in submitted] == [("Roboroni", "portrait")]


def test_a_refused_canary_releases_the_rest(qapp, tmp_path):
    """A 4xx is an answer — the origin knows the outfit and refuses that one
    pose — so the others must be tried, not held forever."""
    store = ToonRenderStore(str(tmp_path), poses=POSES)
    dl = _Downloader({("dnaR", "head"): "client"})
    pf = RenderPrefetcher(store, downloader=dl, executor=_Immediate(), max_in_flight=1)
    pf.discovered("ttr", "Roboroni", "dnaR")
    _drain(qapp, pf)
    assert dl.calls[0] == ("dnaR", "head")
    assert sorted(dl.calls[1:]) == sorted(("dnaR", p) for p in POSES if p != "head")
    assert store.current_dna("ttr", "Roboroni") == "dnaR"   # 2 landed + 1 refused: complete
