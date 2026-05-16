import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_has_update_banner_and_checker(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Force install method = SOURCE so the first-launch default writes True
    from utils.install_method import InstallMethod
    monkeypatch.setattr("utils.install_method.detect", lambda: InstallMethod.SOURCE)
    # Prevent the startup auto-check from spawning a real thread (we
    # don't want to hit api.github.com from tests).
    monkeypatch.setattr(
        "utils.update_checker.UpdateChecker.check_async",
        lambda self, *, manual: True,
    )

    from main import MultiToonTool

    window = MultiToonTool()
    assert hasattr(window, "update_banner")
    assert hasattr(window, "update_checker")
    assert hasattr(window, "update_runner")
    # Banner is hidden by default (no update yet)
    assert not window.update_banner.isVisible()
    window.close()
