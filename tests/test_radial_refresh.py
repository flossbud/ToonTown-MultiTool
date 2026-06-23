import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _acct(aid, dna, name="Toon"):
    from utils.radial_menu_model import RingAccount
    return RingAccount(aid, "ttr", aid.upper(), name, dna, True, False)


def _patch_render(monkeypatch, warmed):
    """render_account_portrait fake: 'complete' once a dna is in `warmed`."""
    from utils.overlay import radial_portrait
    from utils.overlay.radial_portrait import PortraitRender

    def fake(game, toon_name, dna, customizations, diameter):
        pm = QPixmap(diameter, diameter); pm.fill()
        if not dna:
            status = "no_pose"
        elif dna in warmed:
            status = "complete"
        else:
            status = "pending"
        return PortraitRender(pm, status)

    monkeypatch.setattr(radial_portrait, "render_account_portrait", fake, raising=True)


def test_set_accounts_marks_pending(qapp, monkeypatch):
    from utils.overlay.radial_menu import RadialMenuWidget
    _patch_render(monkeypatch, warmed=set())
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a"), _acct("a2", "")])  # a2 empty dna
    assert menu._loading == {"a1"}


def test_pose_ready_refreshes_matching_dna(qapp, monkeypatch):
    from utils.overlay.radial_menu import RadialMenuWidget
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a")])
    assert menu._loading == {"a1"}
    warmed.add("dna-a")
    menu._on_pose_ready("dna-a", "portrait", QPixmap(8, 8))
    assert "a1" not in menu._loading


def test_pose_ready_ignores_non_matching_dna(qapp, monkeypatch):
    from utils.overlay.radial_menu import RadialMenuWidget
    _patch_render(monkeypatch, warmed=set())
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a")])
    menu._on_pose_ready("dna-OTHER", "portrait", None)
    assert menu._loading == {"a1"}


def test_pose_ready_noop_when_not_accounts_state(qapp, monkeypatch):
    from utils.overlay.radial_menu import RadialMenuWidget
    _patch_render(monkeypatch, warmed=set())
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a")])
    menu._state = "main"
    menu._on_pose_ready("dna-a", "portrait", None)   # must not crash / not refresh
    assert menu._loading == {"a1"}


def test_pose_ready_signal_fans_out_to_shared_dna(qapp, monkeypatch):
    # Exercises the REAL pose_ready connection wired in __init__ (the prior
    # tests call _on_pose_ready directly, so a dropped/mis-typed connection
    # would slip through) AND the intended shared-DNA fan-out: two accounts
    # wearing the same costume both refresh from a single pose arrival.
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.rendition_poses import RenditionPoseFetcher
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-shared"), _acct("a2", "dna-shared")])
    assert menu._loading == {"a1", "a2"}
    warmed.add("dna-shared")
    # Same-thread emit -> the __init__ connection runs _on_pose_ready synchronously.
    RenditionPoseFetcher.instance().pose_ready.emit("dna-shared", "portrait", QPixmap(8, 8))
    assert menu._loading == set()
    menu.deleteLater()
    qapp.processEvents()


def test_pose_ready_failure_clears_loading_without_refetch(qapp, monkeypatch):
    # A failed fetch (pixmap=None) must stop the spinner (clear _loading) and
    # must NOT re-render -- re-rendering calls set_dna, which re-fires the fetch
    # as a side effect, looping into a retry storm. A later ring-open retries.
    from utils.overlay.radial_menu import RadialMenuWidget
    from utils.overlay import radial_portrait
    from utils.overlay.radial_portrait import PortraitRender

    calls = []

    def fake(game, toon_name, dna, customizations, diameter):
        calls.append(dna)
        pm = QPixmap(diameter, diameter); pm.fill()
        return PortraitRender(pm, "pending" if dna else "no_pose")

    monkeypatch.setattr(radial_portrait, "render_account_portrait", fake, raising=True)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a")])
    assert menu._loading == {"a1"}
    n = len(calls)                                   # renders so far (set_accounts)
    menu._on_pose_ready("dna-a", "portrait", None)   # fetch-failure signal
    assert menu._loading == set()                    # spinner stopped
    assert len(calls) == n                           # NO re-render -> no refetch loop


def test_kill_switch_still_refreshes(qapp, monkeypatch):
    # Animation disabled -> no clock, but pose_ready must still swap the pixmap
    # and clear the loading flag (live-refresh calls update() directly).
    from utils.overlay.radial_menu import RadialMenuWidget
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu._anim_enabled = False
    menu.set_accounts([_acct("a1", "dna-a")])
    assert menu._loading == {"a1"}
    warmed.add("dna-a")
    menu._on_pose_ready("dna-a", "portrait", QPixmap(8, 8))
    assert "a1" not in menu._loading
