import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_prewarm_is_a_noop(render_cache, monkeypatch):
    """Since the per-toon render cache every remembered toon's poses are
    prefetched at discovery and by the startup sweep: prewarm must not
    raise and must not fetch - not through the legacy fetcher, not through
    the cache - even for accounts that carry a DNA."""
    from utils.rendition_poses import RenditionPoseFetcher
    from utils.radial_menu_model import RingAccount
    from utils.overlay.radial_portrait import prewarm_account_poses
    facade, store, pf = render_cache

    reqs = []
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: reqs.append((dna, pose)),
                        raising=True)

    prewarm_account_poses([], None)             # must not raise, must not fetch
    accounts = [
        RingAccount("a1", "ttr", "A", "Toon A", "dna-a", True),
        RingAccount("a2", "ttr", "B", None,     "",      True),   # placeholder
        RingAccount("a3", "cc",  "C", "Toon C", "",      True),   # empty dna
        RingAccount("a4", "ttr", "D", "Toon D", "dna-d", True),
    ]
    prewarm_account_poses(accounts, customizations=None)

    assert reqs == []
    assert pf.pending_count == 0
    assert store.candidate_dna("ttr", "Toon A") is None
