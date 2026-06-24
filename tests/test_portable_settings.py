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

def test_explicitly_hidden_content_is_shown_when_container_is_shown():
    """Regression: the real SettingsTab is a non-current QStackedWidget page, so
    Qt has it EXPLICITLY hidden (hide() sets WA_WState_ExplicitShowHide).
    Reparenting it via setParent() keeps it hidden, and addWidget() will not
    re-show an explicitly-hidden widget. Without an explicit show() the floating
    panel rendered only its chrome (dark box + "Settings" header) over an
    invisible body. The container must re-show the content it hosts."""
    _app()
    from PySide6.QtWidgets import QLabel, QApplication
    from utils.overlay.portable_settings import PortableSettingsContainer
    content = QLabel("settings body")
    content.hide()                       # explicit-hidden, like a non-current stack page
    assert content.isHidden()
    c = PortableSettingsContainer(content)
    c.resize(400, 400)
    c.show()
    QApplication.processEvents()
    try:
        assert content.isVisible(), "reparented, explicitly-hidden content stayed hidden"
    finally:
        c.hide()

def test_close_button_emits_closed():
    """The traffic-light close dot (reused from the windowed chrome) dismisses
    the panel and carries the windowed close colors/glyph."""
    _app()
    from PySide6.QtWidgets import QLabel
    from utils.overlay.portable_settings import PortableSettingsContainer, _CloseDot
    from utils.widgets.window_chrome_style import TRAFFIC
    fired = []
    c = PortableSettingsContainer(QLabel("body"))
    c.closed.connect(lambda: fired.append(1))
    btn = c.findChild(_CloseDot)
    assert btn is not None, "panel has no close dot"
    assert btn._dot_color.name() == TRAFFIC["close"][0]   # same red as the window close
    assert btn._glyph == "×"
    btn.click()
    assert fired == [1]

def test_no_dim_scrim_outside_panel():
    """The panel must NOT paint a dim scrim. The margin around the inner panel
    stays fully transparent so the cards/games behind show through (the old
    paintEvent filled the whole surface with a semi-opaque dark rectangle)."""
    _app()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtWidgets import QLabel
    from utils.overlay.portable_settings import PortableSettingsContainer
    c = PortableSettingsContainer(QLabel("body"))
    c.resize(400, 400)
    img = QImage(400, 400, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))                 # transparent canvas
    p = QPainter(img); c.render(p, QPoint(0, 0)); p.end()
    # A corner pixel, well inside the 40px margin, must remain fully transparent.
    assert img.pixelColor(5, 5).alpha() == 0, "panel painted a scrim in its margin"

def test_titlebar_drag_moves_the_window():
    """Dragging the title bar moves the panel's top-level window so the user can
    slide it aside from the emblem underneath."""
    _app()
    from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QLabel, QApplication
    from utils.overlay.portable_settings import PortableSettingsContainer, _TitleBar
    c = PortableSettingsContainer(QLabel("body"))
    c.resize(400, 400)
    c.move(100, 100)
    c.show()
    QApplication.processEvents()
    bar = c.findChild(_TitleBar)
    assert bar is not None
    start = c.frameGeometry().topLeft()
    local = QPointF(10.0, 10.0)
    press_g = QPointF(200.0, 120.0)
    move_g = QPointF(260.0, 160.0)               # +60, +40
    bar.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, local, press_g,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    bar.mouseMoveEvent(QMouseEvent(
        QEvent.MouseMove, local, move_g,
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.processEvents()
    end = c.frameGeometry().topLeft()
    assert end - start == QPoint(60, 40), (start, end)
