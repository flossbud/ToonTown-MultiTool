import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from utils.widgets.update_banner import UpdateBanner


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_banner_hidden_by_default(qapp):
    b = UpdateBanner()
    assert not b.isVisible()


def test_banner_shows_when_release_set(qapp):
    b = UpdateBanner()
    b.show_for_release({"tag_name": "v2.4.0-a", "html_url": "https://x"})
    b.show()
    assert b.isVisible()


def test_banner_text_short_under_800px(qapp):
    b = UpdateBanner()
    b.show_for_release({"tag_name": "v2.4.0-a", "html_url": "https://x"})
    b.resize(600, 28)
    assert "Update available" in b._label.text()
    assert "v2.4.0-a" not in b._label.text()


def test_banner_text_long_at_or_above_800px(qapp):
    b = UpdateBanner()
    b.show_for_release({"tag_name": "v2.4.0-a", "html_url": "https://x"})
    b.resize(1024, 28)
    assert "v2.4.0-a" in b._label.text()


def test_banner_click_emits_clicked_signal(qapp):
    b = UpdateBanner()
    b.show_for_release({"tag_name": "v2.4.0-a", "html_url": "https://x"})
    fired = []
    b.clicked.connect(lambda: fired.append(True))
    ev = QMouseEvent(QMouseEvent.MouseButtonRelease, QPointF(10, 14), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    b.mouseReleaseEvent(ev)
    assert fired == [True]


def test_banner_close_button_emits_dismissed(qapp):
    b = UpdateBanner()
    b.show_for_release({"tag_name": "v2.4.0-a", "html_url": "https://x"})
    fired = []
    b.dismissed.connect(lambda: fired.append(True))
    b._close_btn.click()
    assert fired == [True]
