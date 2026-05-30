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
    # show_for_release internally calls self.show(); no extra call needed.
    b.show_for_release({"tag_name": "v2.4.0-a", "html_url": "https://x"})
    assert b.isVisible()


def test_banner_text_has_no_emdash(qapp):
    from utils.widgets.update_banner import BANNER_TEXT
    assert "—" not in BANNER_TEXT  # em-dash forbidden in user-facing text


def test_banner_canonical_copy(qapp):
    from utils.widgets.update_banner import BANNER_TEXT
    assert "A new update is available - click to update" in BANNER_TEXT


def test_close_button_is_icon_not_text(qapp):
    b = UpdateBanner()
    assert b._close_btn.text() == ""
    assert not b._close_btn.icon().isNull()


def test_banner_text_unelided_when_wide(qapp):
    from utils.widgets.update_banner import BANNER_TEXT
    b = UpdateBanner()
    b.show_for_release({"tag_name": "v2.4.0-a", "html_url": "https://x"})
    b.resize(1024, 28)          # plenty of room, no elision
    b._label.resize(960, 28)    # pin label width so QFontMetrics has space
    b._refresh_label()
    assert b._label.text() == BANNER_TEXT


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
