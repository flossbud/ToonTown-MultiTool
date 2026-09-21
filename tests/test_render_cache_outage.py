# tests/test_render_cache_outage.py
"""End to end, offline: a stalled origin must not blank a toon we have already
rendered, and a brand-new toon must complete on recovery without a restart."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from concurrent.futures import Future

import pytest
from PySide6.QtGui import QColor

from tests._render_fixtures import complete_set, real_png
from utils.recent_toons import RecentToonsStore
from utils.rendition_poses import DownloadError
from utils.render_prefetcher import RenderPrefetcher
from utils.toon_render_store import ToonRenderStore
from utils.toon_renders import PREVIOUS_LOOK_TOOLTIP, ToonRenders
from utils.widgets.grandstand.model import CARD_POSE, RosterEntry
from utils.widgets.grandstand.roster_card import RosterCard


class _Immediate:
    def submit(self, fn, *a):
        f = Future()
        try:
            f.set_result(fn(*a))
        except Exception as exc:                        # noqa: BLE001
            f.set_exception(exc)
        return f


class _Origin:
    """Scripted rendition server: stalled until `.recover()`."""
    def __init__(self, tmp_path):
        self.stalled = True
        self.tmp = tmp_path
        self.calls = 0
        self.asked = []                      # every (dna, pose) the client requested
    def __call__(self, dna, pose):
        self.calls += 1
        self.asked.append((dna, pose))
        if self.stalled:
            raise DownloadError("server", 524, "origin timeout")
        p = str(self.tmp / f"origin-{dna}-{pose}.png")
        real_png(p, "#00ff00")
        return open(p, "rb").read()
    def recover(self):
        self.stalled = False


class _Settings:
    def __init__(self):
        self.d = {}
    def get(self, k, default=None):
        return self.d.get(k, default)
    def set(self, k, v):
        self.d[k] = v


def _pixel(pixmap):
    return pixmap.toImage().pixelColor(0, 0)


def _entry(name, dna):
    return RosterEntry(account_id=name.lower(), game="ttr", label=name, username=name,
                       toon_name=name, species="dog", dna=dna, accent="#4a8fe7",
                       footer="Primary", portrait_mode="render", state="idle",
                       message="", raw_error="")


@pytest.fixture
def world(qapp, tmp_path):
    store = ToonRenderStore(str(tmp_path / "renders"))
    origin = _Origin(tmp_path)
    # One in flight: with a synchronous executor, N in flight means N extra
    # attempts land before the breaker's third failure is delivered.
    pf = RenderPrefetcher(store, downloader=origin, executor=_Immediate(), max_in_flight=1)
    facade = ToonRenders(store, pf)
    ToonRenders.install_for_tests(facade)
    yield facade, store, pf, origin
    ToonRenders.install_for_tests(None)


def _drain(qapp, pf, rounds=40):
    for _ in range(rounds):
        qapp.processEvents()
        if pf.pending_count == 0 and pf.in_flight_count == 0:
            break


def test_a_known_toon_keeps_its_previous_look_through_an_outage(world, qapp):
    facade, store, pf, origin = world
    complete_set(store, "ttr", "Hiro", "old-outfit", "#ff0000")
    facade.discovered("ttr", "Hiro", "new-outfit")          # 13 downloads, all 524
    _drain(qapp, pf)
    assert pf.breaker_open is True
    card = RosterCard()
    card.set_entry(_entry("Hiro", "new-outfit"))
    assert card.portrait_pixmap() is not None               # NOT a silhouette
    assert card.portrait_tier() == "previous"
    assert card.toolTip() == PREVIOUS_LOOK_TOOLTIP
    origin.recover()
    pf.fire_probe_now()
    _drain(qapp, pf)
    assert pf.breaker_open is False
    assert store.current_dna("ttr", "Hiro") == "new-outfit"
    assert card.portrait_tier() == "current"                # swapped in, no restart
    assert card.toolTip() == ""


def test_a_never_seen_toon_shows_a_silhouette_then_completes_on_recovery(world, qapp):
    facade, store, pf, origin = world
    facade.discovered("ttr", "Blue Cat", "dna-new")
    _drain(qapp, pf)
    assert pf.breaker_open is True
    card = RosterCard()
    card.set_entry(_entry("Blue Cat", "dna-new"))
    assert card.portrait_pixmap() is None                   # nothing ever rendered
    origin.recover()
    pf.fire_probe_now()
    _drain(qapp, pf)
    assert card.portrait_pixmap() is not None
    assert card.portrait_tier() == "current"


def test_the_breaker_stops_the_hammering(world, qapp):
    facade, store, pf, origin = world
    for name in ("A", "B", "C", "D"):
        facade.discovered("ttr", name, f"dna-{name}")
    _drain(qapp, pf)
    # 4 toons x 13 poses = 52 wanted. Only BREAKER_THRESHOLD attempts were
    # made before the breaker opened, and nothing was dropped.
    from utils.render_prefetcher import BREAKER_THRESHOLD
    assert pf.breaker_open is True
    assert origin.calls == BREAKER_THRESHOLD
    assert pf.pending_count == 52


def test_the_day_of_2026_09_21_a_partial_flat_cache_and_a_cold_origin(world, qapp, tmp_path):
    """The user's exact first run. The legacy flat cache holds only the poses
    the old surfaces ever asked for -- head and portrait -- for the toon's live
    outfit, and the origin answers nothing. import_once copies the two files;
    the set is a candidate (2 of 13). The card must paint the head that is on
    disk, not a silhouette, keep painting it through the outage, and swap to
    "current" once the origin recovers -- all without a restart."""
    facade, store, pf, origin = world
    flat = tmp_path / "flat"
    for pose in ("head", "portrait"):
        real_png(str(flat / f"live-dna__{pose}__512.png"), "#ff0000")
    sm = _Settings()
    RecentToonsStore(sm).record("acc1", "Hiro", "ttr", "live-dna")
    assert facade.import_once(sm, str(flat)) == 2
    assert store.current_dna("ttr", "Hiro") is None         # 2/13: not promoted
    assert store.candidate_dna("ttr", "Hiro") == "live-dna"
    on_disk = tmp_path / "renders" / "toons" / "ttr" / "hiro" / "live-dna" / "head.png"
    assert on_disk.is_file()                                # what the user saw sitting there

    card = RosterCard()
    card.set_entry(_entry("Hiro", "live-dna"))
    assert card.portrait_pixmap() is not None               # head.png is on disk: paint it
    assert _pixel(card.portrait_pixmap()) == QColor("#ff0000")   # the toon's own head
    assert card.portrait_tier() == "candidate"
    assert card.toolTip() == ""                             # no previous look to speak of

    facade.sweep_remembered(sm)                             # the other 11: every one a 524
    _drain(qapp, pf)
    assert pf.breaker_open is True
    assert card.portrait_pixmap() is not None               # still painting through the outage
    assert card.portrait_tier() == "candidate"

    origin.recover()
    pf.fire_probe_now()
    _drain(qapp, pf)
    assert pf.breaker_open is False
    assert store.current_dna("ttr", "Hiro") == "live-dna"
    assert card.portrait_tier() == "current"
    assert card.toolTip() == ""
    # The origin was asked only for the eleven poses the import could not
    # supply; the imported head is the one still painted.
    assert {p for _, p in origin.asked} == set(store.poses) - {"head", "portrait"}
    assert _pixel(card.portrait_pixmap()) == QColor("#ff0000")
