"""Tests for _card_body_path (pure geometry) and the _CompactLayout path accessors."""
import tempfile
import pytest


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", d)
    monkeypatch.setenv("TTMT_CONFIG_DIR", d)
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    yield


def test_card_body_path_nonempty(qapp):
    from tabs.multitoon._compact_layout import _card_body_path
    p = _card_body_path(330.0, 232.0, "tr")
    assert not p.isEmpty()


def test_card_body_path_all_cutouts(qapp):
    """All four cutout directions produce non-empty, valid paths."""
    from tabs.multitoon._compact_layout import _card_body_path
    for cutout in ("tl", "tr", "bl", "br"):
        p = _card_body_path(330.0, 232.0, cutout)
        assert not p.isEmpty(), f"Empty path for cutout={cutout!r}"


def test_card_body_paths_accessor_importable(qapp):
    """card_body_paths and emblem_path exist on _CompactLayout (compile check)."""
    from tabs.multitoon._compact_layout import _CompactLayout
    assert callable(getattr(_CompactLayout, "card_body_paths", None)), (
        "_CompactLayout.card_body_paths not found"
    )
    assert callable(getattr(_CompactLayout, "emblem_path", None)), (
        "_CompactLayout.emblem_path not found"
    )


def test_card_sizing_constants_sourced_from_card_metrics(qapp):
    """The card SIZING constants derive from CardMetrics(1.0), so the value
    object is the single source of truth (framed mode byte-for-byte unchanged)."""
    import tabs.multitoon._compact_layout as cl
    from utils.overlay.card_metrics import CardMetrics

    m = CardMetrics(1.0)
    assert cl.PORTRAIT == m.portrait
    assert cl.PORTRAIT_RING == m.portrait_ring
    assert cl.EMBLEM == m.emblem
    assert cl.CTRL_W == m.ctrl_w
    assert cl.CARD_PAD == m.card_pad
    assert cl.CARD_MIN_H == m.card_min_h
    assert cl.GRID_GAP == m.grid_gap


def test_portrait_frame_size_comes_from_card_metrics(qapp):
    """A built _PortraitFrame takes its fixed size from the canonical metrics."""
    from tabs.multitoon._compact_layout import _PortraitFrame
    from utils.overlay.card_metrics import CardMetrics

    frame = _PortraitFrame()
    portrait = CardMetrics(1.0).portrait
    assert frame.width() == portrait
    assert frame.height() == portrait
