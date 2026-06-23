import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_prewarm_requests_only_dna_accounts(qapp, monkeypatch):
    from utils.rendition_poses import RenditionPoseFetcher
    from utils.radial_menu_model import RingAccount
    from utils.overlay.radial_portrait import prewarm_account_poses

    reqs = []
    monkeypatch.setattr(RenditionPoseFetcher, "request",
                        lambda self, dna, pose: reqs.append((dna, pose)),
                        raising=True)

    accounts = [
        RingAccount("a1", "ttr", "A", "Toon A", "dna-a", True, False),
        RingAccount("a2", "ttr", "B", None,     "",      True, False),  # placeholder
        RingAccount("a3", "cc",  "C", "Toon C", "",      True, False),  # empty dna
        RingAccount("a4", "ttr", "D", "Toon D", "dna-d", True, False),
    ]
    prewarm_account_poses(accounts, customizations=None)

    assert [d for d, _ in reqs] == ["dna-a", "dna-d"]
    assert all(pose == "portrait" for _, pose in reqs)  # resolve_pose({}, "portrait")
