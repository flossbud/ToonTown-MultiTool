"""Pin: header carries a 'header_session_status' QLabel that reports
service idle vs running and the enabled-toon count. The chip-rail audit
flagged the right side of the header as dead space."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_header_has_session_status_label(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from main import MultiToonTool
    window = MultiToonTool()
    label = window.header.findChild(QLabel, "header_session_status")
    assert label is not None, "Expected QLabel#header_session_status in header"
    txt = label.text()
    # Idle and 0/4 are the defaults at startup with no game detected.
    assert "Idle" in txt
    assert "0/4" in txt
    window.close()


def test_header_session_status_updates_on_service_start(qapp, tmp_path, monkeypatch):
    """When the multitoon service flips to running, the status label must
    update its prefix from Idle to Running. Drives the wire-up between
    multitoon state and the header label."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from main import MultiToonTool
    window = MultiToonTool()
    label = window.header.findChild(QLabel, "header_session_status")
    # Simulate service running
    window.multitoon_tab.service_running = True
    window._refresh_header_session_status()
    assert "Running" in label.text(), (
        f"Expected 'Running' after service_running=True; got {label.text()!r}"
    )
    window.close()
