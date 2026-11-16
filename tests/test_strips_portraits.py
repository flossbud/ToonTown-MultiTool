"""Portraits for the strips come from the launcher's render store, never on
a paint path, and fall back to the silhouette."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from services.toon_session_fake import DEMO_KEYSET_IDS, FakeToonSession
from utils.overlay.backend import OverlayBackend
from utils.strips.attach import AttachStrategy
from utils.strips.controller import StripController
from utils.strips.follow import StripFollower
from utils.strips.portraits import PortraitProvider


class Renders(QObject):
    render_landed = Signal(str, str, str)
    set_promoted = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.have = {}
        self.asked = []

    def pixmap_for(self, game, name, pose):
        self.asked.append((game, name, pose))
        pm = self.have.get((game, name, pose))
        return (pm, "current") if pm is not None else None


class Looks:
    def __init__(self):
        self.entries = {}

    def get(self, game, name):
        return self.entries.get((game, name), {})


def pixmap(colour):
    pm = QPixmap(64, 64)
    pm.fill(QColor(colour))
    return pm


@pytest.fixture
def toons(qapp):
    demo = FakeToonSession.demo().toons()
    return {t.name: replace(t, dna="t" * 20) if t.game == "ttr" else t for t in demo}


def test_no_render_means_silhouette(toons):
    provider = PortraitProvider(Renders(), Looks())
    assert provider.pixmap(toons["Flossbud"]) is None


def test_clash_and_unnamed_and_dna_less_toons_never_ask(toons):
    renders = Renders()
    provider = PortraitProvider(renders, Looks())
    assert provider.pixmap(toons["Moe"]) is None                       # Corporate Clash
    assert provider.pixmap(replace(toons["Hector"], dna=None)) is None
    assert provider.pixmap(replace(toons["Hector"], name=None)) is None
    assert renders.asked == []


def test_lookup_is_remembered_until_a_render_lands(toons):
    renders = Renders()
    provider = PortraitProvider(renders, Looks())
    changed = []
    provider.changed.connect(lambda g, n: changed.append((g, n)))
    toon = toons["Flossbud"]
    assert provider.pixmap(toon) is None
    assert provider.pixmap(toon) is None
    assert len(renders.asked) == 1                    # asked once, not per repaint
    blue = pixmap("#0000ff")
    renders.have[("ttr", "Flossbud", "portrait")] = blue
    assert provider.pixmap(toon) is None              # still the remembered answer
    renders.render_landed.emit("ttr", "Flossbud", "portrait")
    assert changed == [("ttr", "Flossbud")]
    assert provider.pixmap(toon) is blue
    assert len(renders.asked) == 2


def test_pose_comes_from_the_looks_store(toons):
    renders, looks = Renders(), Looks()
    provider = PortraitProvider(renders, looks)
    provider.pixmap(toons["Hector"])
    assert renders.asked[-1] == ("ttr", "Hector", "portrait")
    from utils.rendition_poses import POSE_NAMES
    other = next(p for p in POSE_NAMES if p != "portrait")
    looks.entries[("ttr", "Hector")] = {"pose": other}
    provider.forget("ttr", "Hector")
    provider.pixmap(toons["Hector"])
    assert renders.asked[-1] == ("ttr", "Hector", other)


def test_framing_comes_from_the_looks_store(toons):
    looks = Looks()
    provider = PortraitProvider(Renders(), looks)
    assert provider.frame(toons["Hector"]) == (1.0, 0.0, 0.0, 0.0)
    looks.entries[("ttr", "Hector")] = {"portrait": {"transform": {
        "zoom": 1.5, "offset_x": 0.1, "offset_y": -0.2, "rotate": 15}}}
    assert provider.frame(toons["Hector"]) == (1.5, 0.1, -0.2, 15.0)
    looks.entries[("ttr", "Hector")] = {"portrait": {"transform": {"zoom": "big"}}}
    assert provider.frame(toons["Hector"]) == (1.0, 0.0, 0.0, 0.0)


class _Session(FakeToonSession):
    """The fake, with a looks store like the real session has."""
    looks = Looks()

    @property
    def customizations(self):
        return self.looks


def test_strip_repaints_when_its_render_arrives(qapp, toons, monkeypatch):
    renders = Renders()
    from utils import toon_renders
    monkeypatch.setattr(toon_renders.ToonRenders, "_instance", renders)
    session = _Session([replace(toons["Flossbud"], window_id="7", slot=0)], running=True)
    rects = {"7": (100, 50, 800, 600)}

    class Backend(OverlayBackend):
        pass

    class Strategy(AttachStrategy):
        logical_native = True

    follower = StripFollower(Strategy(), Backend(), geometry_fn=rects.get, scale=1.0)
    controller = StripController(session, follower, keyset_ids=DEMO_KEYSET_IDS)
    controller.start()
    follower.tracker.stop()
    follower.tracker.sample_now(), follower.tracker.sample_now()
    QApplication.processEvents()
    strip = follower.surface("7").strip
    assert strip.model().portrait is None
    red = pixmap("#ff0000")
    renders.have[("ttr", "Flossbud", "portrait")] = red
    renders.set_promoted.emit("ttr", "Flossbud")
    QApplication.processEvents()
    assert strip.model().portrait is red
    # A beans update does not look the portrait up again.
    asked = len(renders.asked)
    session.update_toon("7", beans=999)
    QApplication.processEvents()
    assert len(renders.asked) == asked and strip.model().portrait is red
    # The looks editor saved a new pose: looked up again.
    controller.customization_changed("ttr", "Flossbud")
    assert len(renders.asked) == asked + 1
    controller.shutdown()
