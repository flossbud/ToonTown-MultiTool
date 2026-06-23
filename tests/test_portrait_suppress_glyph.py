import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_suppress_flag_hides_fallback_glyph(qapp):
    from tabs.multitoon._tab import ToonPortraitWidget
    w = ToonPortraitWidget(slot=0)
    w.resize(64, 64)
    w.set_colors("#ff0000", "#ffffff")   # no pixmap, not loading -> draws "0"
    before = w.grab().toImage()
    w.set_suppress_fallback_glyph(True)
    after = w.grab().toImage()
    # The "0" was painted in `before`; suppressed in `after`.
    assert before != after
    w.deleteLater()
