import pytest
from PySide6.QtWidgets import QApplication

from utils.widgets.update_dialog import UpdateDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _info(tag="v2.4.0-a", body="Build: 470\nFix something\nAdd CC token rotation"):
    return {
        "tag_name": tag,
        "body": body,
        "html_url": f"https://github.com/x/{tag}",
        "build_number": 470,
    }


def test_dialog_shows_release_notes_without_build_line(qapp):
    d = UpdateDialog(_info(), local_version_string="2.3.0-a (build 458, 97279d7)")
    body_text = d._body.toPlainText() if hasattr(d._body, "toPlainText") else ""
    assert "Build: 470" not in body_text
    assert "Fix something" in body_text


def test_dialog_emits_update_signal(qapp):
    d = UpdateDialog(_info(), local_version_string="2.3.0-a (build 458, 97279d7)")
    fired = []
    d.update_now.connect(lambda: fired.append(True))
    d._update_btn.click()
    assert fired == [True]


def test_dialog_emits_skip_signal(qapp):
    d = UpdateDialog(_info(), local_version_string="2.3.0-a (build 458, 97279d7)")
    fired = []
    d.skip_version.connect(lambda: fired.append(True))
    d._skip_btn.click()
    assert fired == [True]


def test_dialog_emits_later_signal(qapp):
    d = UpdateDialog(_info(), local_version_string="2.3.0-a (build 458, 97279d7)")
    fired = []
    d.remind_later.connect(lambda: fired.append(True))
    d._later_btn.click()
    assert fired == [True]


def test_dialog_view_notes_opens_url(qapp, monkeypatch):
    d = UpdateDialog(_info(), local_version_string="2.3.0-a (build 458, 97279d7)")
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    d._view_notes_btn.click()
    assert opened == ["https://github.com/x/v2.4.0-a"]
