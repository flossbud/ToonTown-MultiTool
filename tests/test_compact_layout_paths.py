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
