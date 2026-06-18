import importlib
import pytest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def test_tab_switch_records_substep_spans(app, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_PERF_TRACE", "1")
    import utils.perf_trace as pt
    importlib.reload(pt)
    import utils.motion as motion
    importlib.reload(motion)
    # Force animated (non-reduced) mode with a near-instant duration.
    monkeypatch.setattr(motion, "is_reduced", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)

    stack = QStackedWidget()
    for _ in range(2):
        w = QWidget()
        stack.addWidget(w)
    stack.resize(200, 150)
    stack.setCurrentIndex(0)
    stack.show()

    group = motion.push_slide_pages(stack, 0, 1, axis="h")
    assert group is not None
    # Drive the (zero-duration) animation + the deferred start timer to finish.
    for _ in range(20):
        app.processEvents()
    pt.flush()  # ensure any buffered-but-unflushed spans are written

    text = open(pt.log_path()).read()
    assert "tab_switch#1" in text
    assert "incoming.grab" in text
    assert "outgoing.grab" in text
