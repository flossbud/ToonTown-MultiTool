import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from utils.widgets.admin_notice_banner import AdminNoticeBanner, BANNER_TEXT


def _app():
    return QApplication.instance() or QApplication([])


def test_restart_button_emits():
    _app()
    b = AdminNoticeBanner()
    fired = []
    b.restart_as_admin.connect(lambda: fired.append(True))
    b._restart_btn.click()
    assert fired == [True]


def test_close_emits_dismissed_and_hides():
    _app()
    b = AdminNoticeBanner()
    b.show()
    fired = []
    b.dismissed.connect(lambda: fired.append(True))
    b._close_btn.click()
    assert fired == [True]
    assert not b.isVisible()


def test_set_restart_enabled_disables_button():
    _app()
    b = AdminNoticeBanner()
    b.set_restart_enabled(False)
    assert not b._restart_btn.isEnabled()
    b.set_restart_enabled(True)
    assert b._restart_btn.isEnabled()


def test_banner_text_has_no_em_dash():
    assert "—" not in BANNER_TEXT


def test_hidden_by_default():
    _app()
    b = AdminNoticeBanner()
    assert not b.isVisible()


def test_label_elides_at_narrow_width_and_tooltip_is_full():
    _app()
    b = AdminNoticeBanner()
    b._label.setFixedWidth(180)
    b._refresh_label()
    assert len(b._label.text()) <= len(BANNER_TEXT)   # elided or fits, never longer
    assert b._label.toolTip() == BANNER_TEXT
