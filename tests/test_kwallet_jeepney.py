import sys
import pytest

if sys.platform != "linux":
    pytest.skip("KWallet backend is Linux-only", allow_module_level=True)

from utils.kwallet_jeepney import detect_kwallet_variant


def test_detect_returns_none_when_no_daemon(monkeypatch):
    """When neither kwalletd6 nor kwalletd5 owns its bus name, detection returns None."""
    import utils.kwallet_jeepney as kj
    monkeypatch.setattr(kj, "_session_bus_owns", lambda name: False)
    assert detect_kwallet_variant() is None


def test_detect_prefers_kwalletd6(monkeypatch):
    """If both daemons are present, kwalletd6 wins."""
    import utils.kwallet_jeepney as kj
    owners = {"org.kde.kwalletd6": True, "org.kde.kwalletd5": True}
    monkeypatch.setattr(kj, "_session_bus_owns", owners.get)
    assert detect_kwallet_variant() == ("org.kde.kwalletd6", "/modules/kwalletd6")


def test_detect_falls_back_to_kwalletd5(monkeypatch):
    """If only kwalletd5 is owned, fall back to it."""
    import utils.kwallet_jeepney as kj
    owners = {"org.kde.kwalletd6": False, "org.kde.kwalletd5": True}
    monkeypatch.setattr(kj, "_session_bus_owns", owners.get)
    assert detect_kwallet_variant() == ("org.kde.kwalletd5", "/modules/kwalletd5")
