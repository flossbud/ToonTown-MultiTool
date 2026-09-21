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


def test_import_once_is_guarded_by_the_marker_even_when_the_first_import_was_partial(facade):
    f, store, pf, tmp_path = facade
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "dna1__portrait__512.png").write_bytes(PNG_SIGNATURE + b"old")  # "head" missing
    sm = _Settings()
    RecentToonsStore(sm).record("acc1", "Hiro", "ttr", "dna1")
    first = f.import_once(sm, str(flat))
    assert 0 < first < len(POSES)                              # partial: only "portrait" landed
    marker = os.path.join(store.toons_root(), ".imported")
    assert os.path.exists(marker)
    (flat / "dna1__head__512.png").write_bytes(PNG_SIGNATURE + b"new")   # now the rest becomes available
    assert f.import_once(sm, str(flat)) == 0                  # marker guards the second call
    assert store.missing_poses("ttr", "Hiro", "dna1") == ["head"]  # never copied in


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
    tab._render_seen = {}
    seen = []
    monkeypatch.setattr(f, "discovered", lambda g, n, d: seen.append((g, n, d)))
    mt.MultitoonTab._capture_account_toon(tab, "0x1", "Hiro", "dna1", laff=10)
    assert seen == [("ttr", "Hiro", "dna1")]
    mt.MultitoonTab._capture_account_toon(tab, "0x1", "Hiro", "", laff=10)   # no dna: nothing
    assert seen == [("ttr", "Hiro", "dna1")]


def test_discovery_hook_skips_the_window_lookup_on_unchanged_polls(facade, qapp, monkeypatch):
    f, store, pf, tmp_path = facade
    from tabs.multitoon import _tab as mt
    from utils.game_registry import GameRegistry
    monkeypatch.setattr(GameRegistry, "pid_for_window", staticmethod(lambda wid: None))
    monkeypatch.setattr(f, "discovered", lambda g, n, d: None)
    tab = mt.MultitoonTab.__new__(mt.MultitoonTab)
    tab._toon_capture_sink = None
    tab._last_captured_toon = {}
    tab._render_seen = {}

    calls = []
    monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                        lambda wid: (calls.append(wid), "ttr")[1])

    mt.MultitoonTab._capture_account_toon(tab, "0x1", "Hiro", "dna1", laff=10)
    mt.MultitoonTab._capture_account_toon(tab, "0x1", "Hiro", "dna1", laff=10)
    mt.MultitoonTab._capture_account_toon(tab, "0x1", "Hiro", "dna1", laff=10)
    assert len(calls) == 1                                     # unchanged: memoised, no lookup

    mt.MultitoonTab._capture_account_toon(tab, "0x1", "Hiro", "dna2", laff=10)
    assert len(calls) == 2                                     # new outfit: looked up again

    mt.MultitoonTab._capture_account_toon(tab, "0x2", "Hiro", "dna2", laff=10)
    assert len(calls) == 3                                     # same toon/dna, different window

    none_calls = []
    monkeypatch.setattr(GameRegistry.instance(), "get_game_for_window",
                        lambda wid: (none_calls.append(wid), None)[1])
    mt.MultitoonTab._capture_account_toon(tab, "0x3", "Hiro", "dna3", laff=10)
    mt.MultitoonTab._capture_account_toon(tab, "0x3", "Hiro", "dna3", laff=10)
    assert len(none_calls) == 2                                # a None resolution is never memoised


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
