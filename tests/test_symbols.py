import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_M_returns_misc_when_triangles_render(qapp, monkeypatch):
    """When the BMP-triangle test passes, M() returns the misc arg."""
    import utils.symbols
    monkeypatch.setattr(utils.symbols, "_USE_TRIANGLE", True)
    assert utils.symbols.M("▶", ">") == "▶"


def test_M_returns_fallback_when_triangles_dont_render(qapp, monkeypatch):
    """When the BMP-triangle test fails, M() returns the fallback."""
    import utils.symbols
    monkeypatch.setattr(utils.symbols, "_USE_TRIANGLE", False)
    assert utils.symbols.M("▶", ">") == ">"


def test_M_is_independent_of_S(qapp, monkeypatch):
    """M() must not be gated by the emoji-support flag (that's what S() uses)."""
    import utils.symbols
    monkeypatch.setattr(utils.symbols, "_USE_EMOJI", False)
    monkeypatch.setattr(utils.symbols, "_USE_TRIANGLE", True)
    assert utils.symbols.M("▼", "v") == "▼"
