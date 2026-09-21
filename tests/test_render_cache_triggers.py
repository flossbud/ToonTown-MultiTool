"""Discovery feeds the prefetcher; startup imports once and sweeps remembered toons."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest

from utils.recent_toons import RecentToonsStore
from utils.render_prefetcher import RenderPrefetcher
from utils.toon_render_store import PNG_SIGNATURE, ToonRenderStore
from utils.toon_renders import ToonRenders

POSES = ("portrait", "head")


class _Settings:
    def __init__(self):
        self.d = {}
    def get(self, k, default=None):
        return self.d.get(k, default)
    def set(self, k, v):
        self.d[k] = v


class _Immediate:
    def submit(self, fn, *a):
        from concurrent.futures import Future
        f = Future()
        try:
            f.set_result(fn(*a))
        except Exception as exc:                        # noqa: BLE001
            f.set_exception(exc)
        return f


@pytest.fixture
def facade(qapp, tmp_path):
    store = ToonRenderStore(str(tmp_path / "cache"), poses=POSES)
    pf = RenderPrefetcher(store, downloader=lambda d, p: PNG_SIGNATURE + b"x",
                          executor=_Immediate(), max_in_flight=1)
    f = ToonRenders(store, pf)
    ToonRenders.install_for_tests(f)
    yield f, store, pf, tmp_path
    ToonRenders.install_for_tests(None)


def test_all_records_walks_every_account():
    sm = _Settings()
    rt = RecentToonsStore(sm)
    rt.record("acc1", "Hiro", "ttr", "dna1")
    rt.record("acc1", "Hiro Alt", "ttr", "dna1b")
    rt.record("acc2", "Blue Cat", "ttr", "dna2")
    got = sorted((aid, r.toon_name, r.dna) for aid, r in rt.all_records())
    assert got == [("acc1", "Hiro", "dna1"), ("acc1", "Hiro Alt", "dna1b"),
                   ("acc2", "Blue Cat", "dna2")]


def test_import_once_runs_exactly_once(facade):
    f, store, pf, tmp_path = facade
    flat = tmp_path / "flat"
    flat.mkdir()
    for pose in POSES:
        (flat / f"dna1__{pose}__512.png").write_bytes(PNG_SIGNATURE + b"old")
    sm = _Settings()
    RecentToonsStore(sm).record("acc1", "Hiro", "ttr", "dna1")
    assert f.import_once(sm, str(flat)) == 2
    assert store.current_dna("ttr", "Hiro") == "dna1"
    (flat / "dna1__head__512.png").write_bytes(PNG_SIGNATURE + b"changed")
    assert f.import_once(sm, str(flat)) == 0                  # marker file honoured


def test_sweep_remembered_queues_missing_work_only(facade, qapp):
    f, store, pf, tmp_path = facade
    sm = _Settings()
    rt = RecentToonsStore(sm)
    rt.record("acc1", "Hiro", "ttr", "dna1")
    rt.record("acc2", "NoDna", "ttr", "")
    assert f.sweep_remembered(sm) == 1
    for _ in range(20):
        qapp.processEvents()
    assert store.current_dna("ttr", "Hiro") == "dna1"


def test_discovery_reaches_the_prefetcher_with_the_windows_game(facade, qapp, monkeypatch):
    f, store, pf, tmp_path = facade
    from tabs.multitoon import _tab as mt
    from utils.game_registry import GameRegistry
    monkeypatch.setattr(GameRegistry, "pid_for_window", staticmethod(lambda wid: None))
    monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window", lambda wid: "ttr")
    tab = mt.MultitoonTab.__new__(mt.MultitoonTab)
    tab._toon_capture_sink = None
    tab._last_captured_toon = {}
    seen = []
    monkeypatch.setattr(f, "discovered", lambda g, n, d: seen.append((g, n, d)))
    mt.MultitoonTab._capture_account_toon(tab, "0x1", "Hiro", "dna1", laff=10)
    assert seen == [("ttr", "Hiro", "dna1")]
    mt.MultitoonTab._capture_account_toon(tab, "0x1", "Hiro", "", laff=10)   # no dna: nothing
    assert seen == [("ttr", "Hiro", "dna1")]


def test_discovered_is_memoised_per_toon_until_the_dna_changes(facade):
    f, store, pf, tmp_path = facade
    calls = []
    monkeypatch_target = f.prefetcher
    orig_discovered = monkeypatch_target.discovered
    monkeypatch_target.discovered = lambda g, n, d: calls.append((g, n, d))
    try:
        f.discovered("ttr", "Hiro", "dna1")
        f.discovered("ttr", "Hiro", "dna1")
        assert calls == [("ttr", "Hiro", "dna1")]           # second call: memoised, not forwarded
        f.discovered("ttr", "Hiro", "dna2")
        assert calls == [("ttr", "Hiro", "dna1"), ("ttr", "Hiro", "dna2")]
        f.discovered("ttr", "Blue Cat", "dna1")
        assert calls == [("ttr", "Hiro", "dna1"), ("ttr", "Hiro", "dna2"),
                          ("ttr", "Blue Cat", "dna1")]
    finally:
        monkeypatch_target.discovered = orig_discovered
