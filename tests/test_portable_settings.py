import os
import pytest
pytestmark = pytest.mark.skipif(os.environ.get("QT_QPA_PLATFORM") != "offscreen",
                                reason="offscreen only")

def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def test_container_hosts_and_releases_content_and_emits_closed():
    _app()
    from PySide6.QtWidgets import QLabel
    from utils.overlay.portable_settings import PortableSettingsContainer
    content = QLabel("settings here")
    c = PortableSettingsContainer(content)
    assert content.parent() is not None                  # reparented into the panel
    fired = []
    c.closed.connect(lambda: fired.append(1))
    c.close_via_test = None
    # Esc emits closed
    from PySide6.QtCore import Qt, QEvent
    from PySide6.QtGui import QKeyEvent
    c.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert fired == [1]
    released = c.release_content()
    assert released is content
    assert content.parent() is None                      # detached, survives container destruction

def test_container_paint_does_not_crash():
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPixmap, QPainter
    from PySide6.QtWidgets import QLabel
    from utils.overlay.portable_settings import PortableSettingsContainer
    c = PortableSettingsContainer(QLabel("x")); c.resize(400, 400)
    pm = QPixmap(400, 400); p = QPainter(pm); c.render(p, QPoint(0, 0)); p.end()
