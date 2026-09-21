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


def _acct(aid, dna, name="Toon", game="ttr"):
    from utils.radial_menu_model import RingAccount
    return RingAccount(aid, game, aid.upper(), name, dna, True)


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


def test_render_landed_refreshes_matching_toon(qapp, monkeypatch):
    from utils.overlay.radial_menu import RadialMenuWidget
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a")])
    assert menu._loading == {"a1"}
    warmed.add("dna-a")
    menu._on_render_landed("ttr", "Toon", "portrait")
    assert "a1" not in menu._loading


def test_render_landed_ignores_other_toons(qapp, monkeypatch):
    # The cache is process-wide and keyed by (game, name): a landing for
    # another toon, or for the same name under another game, is not ours.
    from utils.overlay.radial_menu import RadialMenuWidget
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a")])
    warmed.add("dna-a")         # a re-render WOULD complete - it must not run
    menu._on_render_landed("ttr", "Other", "portrait")
    menu._on_render_landed("cc", "Toon", "portrait")
    assert menu._loading == {"a1"}


def test_render_landed_noop_when_not_accounts_state(qapp, monkeypatch):
    from utils.overlay.radial_menu import RadialMenuWidget
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a")])
    warmed.add("dna-a")         # a re-render WOULD complete - it must not run
    menu._state = "main"
    menu._on_render_landed("ttr", "Toon", "portrait")   # must not crash / not refresh
    assert menu._loading == {"a1"}


def test_render_landed_signal_fans_out_to_same_toon(qapp, monkeypatch, render_cache):
    # Exercises the REAL render_landed connection wired in __init__ (the prior
    # tests call _on_render_landed directly, so a dropped/mis-typed connection
    # would slip through) AND the intended fan-out: two ring entries for the
    # same toon both refresh from a single landing.
    from utils.overlay.radial_menu import RadialMenuWidget
    facade, store, pf = render_cache
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-shared"), _acct("a2", "dna-shared")])
    assert menu._loading == {"a1", "a2"}
    warmed.add("dna-shared")
    # Same-thread emit -> the __init__ connection runs _on_render_landed synchronously.
    pf.render_landed.emit("ttr", "Toon", "portrait")
    assert menu._loading == set()
    menu.deleteLater()
    qapp.processEvents()


def test_set_promoted_signal_refreshes_pending_accounts(qapp, monkeypatch, render_cache):
    # A toon's set being promoted (all poses landed at once, or a startup
    # import) must fill a pending portrait exactly like a single landing.
    from utils.overlay.radial_menu import RadialMenuWidget
    facade, store, pf = render_cache
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a"), _acct("b1", "dna-b", name="Blue")])
    assert menu._loading == {"a1", "b1"}
    warmed.update({"dna-a", "dna-b"})
    pf.set_promoted.emit("ttr", "Toon")
    assert menu._loading == {"b1"}
    menu.deleteLater()
    qapp.processEvents()


def test_destroyed_menu_never_hears_the_cache(qapp, monkeypatch, render_cache):
    # Both connections are receiver-owned: once the menu is destroyed the
    # process-wide facade's signals must not reach it at all. A lambda slot
    # would outlive the ring, run the re-render and then raise inside the
    # emit on `self.update()` of a deleted widget.
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent
    from utils.overlay import radial_portrait
    from utils.overlay.radial_menu import RadialMenuWidget
    facade, store, pf = render_cache
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a")])
    assert menu._loading == {"a1"}
    warmed.add("dna-a")
    calls = []
    real = radial_portrait.render_account_portrait
    monkeypatch.setattr(radial_portrait, "render_account_portrait",
                        lambda *a: (calls.append(a), real(*a))[1], raising=True)
    menu.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not shiboken6.isValid(menu)
    pf.render_landed.emit("ttr", "Toon", "portrait")
    pf.set_promoted.emit("ttr", "Toon")
    assert calls == []


def test_render_landed_for_a_pending_toon_does_not_grow_the_fetch_queue(qapp, render_cache):
    # Re-rendering a still-pending account goes back through set_dna ->
    # discovered/want. The prefetcher dedupes, so repeated landings for a
    # toon whose wanted pose is still missing must not pile up fetch work
    # (the legacy path looped into a retry storm here).
    from utils.overlay.radial_menu import RadialMenuWidget
    from tests._render_fixtures import real_png
    facade, store, pf = render_cache
    menu = RadialMenuWidget(emblem_diameter=120)
    menu.set_accounts([_acct("a1", "dna-a")])
    assert menu._loading == {"a1"}
    n = pf.pending_count
    assert n > 0
    # A pose we do not show lands; ours ("portrait") is still missing.
    real_png(store.path_for("ttr", "Toon", "dna-a", "waving"))
    assert store.mark_landed("ttr", "Toon", "dna-a", "waving")
    menu._on_render_landed("ttr", "Toon", "waving")
    menu._on_render_landed("ttr", "Toon", "waving")
    assert menu._loading == {"a1"}
    assert pf.pending_count == n               # nothing was added


def test_kill_switch_still_refreshes(qapp, monkeypatch):
    # Animation disabled -> no clock, but a landing must still swap the pixmap
    # and clear the loading flag (live-refresh calls update() directly).
    from utils.overlay.radial_menu import RadialMenuWidget
    warmed = set()
    _patch_render(monkeypatch, warmed)
    menu = RadialMenuWidget(emblem_diameter=120)
    menu._anim_enabled = False
    menu.set_accounts([_acct("a1", "dna-a")])
    assert menu._loading == {"a1"}
    warmed.add("dna-a")
    menu._on_render_landed("ttr", "Toon", "portrait")
    assert "a1" not in menu._loading
