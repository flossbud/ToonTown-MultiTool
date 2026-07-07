from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from utils.widgets.primary_toon_slot import PrimaryToonSlot


def test_fixed_38px(qapp):
    w = PrimaryToonSlot(game="ttr")
    assert w.sizeHint() == QSize(38, 38)
    assert w.minimumSize() == QSize(38, 38)


def test_set_toon_marks_set(qapp):
    w = PrimaryToonSlot(game="ttr")
    w.set_toon(species="DOG", accent="#8ab6f0", slot_number=1)
    assert w.is_set() is True


def test_unset_is_default(qapp):
    w = PrimaryToonSlot(game="cc")
    assert w.is_set() is False


def test_clear_resets(qapp):
    w = PrimaryToonSlot(game="ttr")
    w.set_toon(species="DOG", accent="#8ab6f0", slot_number=1)
    w.clear()
    assert w.is_set() is False


def test_click_emits(qapp):
    w = PrimaryToonSlot(game="ttr")
    fired = []
    w.clicked.connect(lambda: fired.append(1))
    w._emit_click()
    assert fired == [1]


def test_paints_without_error_both_states(qapp):
    # grab() exercises paintEvent for set + unset; must not raise
    w = PrimaryToonSlot(game="ttr"); w.resize(38, 38)
    w.grab()
    w.set_toon(species="HORSE", accent=None, slot_number=2)  # accent None -> game accent
    w.grab()


def test_set_toon_none_species_is_unset_but_keeps_badge(qapp):
    w = PrimaryToonSlot(game="ttr")
    w.set_toon(species=None, accent=None, slot_number=3)
    assert w.is_set() is False
    w.grab()  # paints dashed + badge without error


def test_pose_ready_latches_after_load(qapp, monkeypatch):
    """Regression: once the portrait for the current DNA is loaded, a repeat
    pose_ready for that DNA must be a no-op.

    render_account_portrait fires a fetch as a side effect (set_dna ->
    fetcher.request), and a warm cache re-emits pose_ready via singleShot(0).
    So re-rendering inside _on_pose_ready re-arms the very signal that called
    it -- an event-loop-saturating feedback storm that pegged the main thread
    at ~130% CPU and dropped the whole app to ~15fps (Launch v2). This mirrors
    the radial ring's one-shot _loading latch."""
    import utils.overlay.radial_portrait as rp

    state = {"warm": False, "calls": 0}

    class _FakeRender:
        def __init__(self, warm):
            self.status = "complete" if warm else "pending"
            pm = QPixmap(38, 38)
            pm.fill(Qt.black)  # non-null -> has_portrait() True once assigned
            self.pixmap = pm

    def _fake_render(*args, **kwargs):
        state["calls"] += 1
        return _FakeRender(state["warm"])

    monkeypatch.setattr(rp, "render_account_portrait", _fake_render)

    dna = "74090202010000000000000000000000"
    w = PrimaryToonSlot(game="ttr")
    w.set_toon(toon_name="Moe", dna=dna, species="HORSE", slot_number=1)
    assert w.has_portrait() is False  # cold cache: silhouette still showing

    # The pose fetch completes and warms the disk cache; pose_ready arrives.
    state["warm"] = True
    state["calls"] = 0
    w._on_pose_ready(dna, "portrait", QPixmap(1, 1))
    assert w.has_portrait() is True   # real portrait now loaded
    assert state["calls"] == 1

    # That render re-fired the fetch, so pose_ready fires AGAIN with the warm
    # pixmap. It MUST NOT trigger another render, or the loop never terminates.
    w._on_pose_ready(dna, "portrait", QPixmap(1, 1))
    assert state["calls"] == 1, "pose_ready re-rendered after load -> feedback storm"
