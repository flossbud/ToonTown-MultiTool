"""Settings sheet: the shared Settings rows regrouped, the Float strips rows,
Logs and About; mounted in the sheet host under the real stylesheet."""
import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QWidget

from utils import settings_keys as sk
from utils import theme_manager
from utils.widgets.launchpad import material as m
from utils.widgets.launchpad import settings_sheet as ss
from utils.widgets.launchpad.settings_sheet import SettingsSheet
from utils.widgets.launchpad.slide_sheet import SlideSheetHost


class _Settings:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.order = []
        self._cbs = []

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.order.append((key, value))
        for cb in list(self._cbs):
            cb(key, value)

    def on_change(self, cb):
        self._cbs.append(cb)


@pytest.fixture
def quiet(monkeypatch):
    import utils.widgets.settings_rows as sr
    monkeypatch.setattr(sr, "find_engine_path", lambda: None)
    monkeypatch.setattr(sr, "find_cc_engine_path", lambda: None)
    monkeypatch.setattr(sr, "discover_cc_installs", lambda: [])
    monkeypatch.setattr("services.cc_login_service.discover_cc_installs", lambda: [])
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)


@contextmanager
def _theme(qapp, theme):
    before_sheet = qapp.styleSheet()
    before_palette = QPalette(qapp.palette())
    before_marker = theme_manager._APPLIED_THEME
    try:
        theme_manager.apply_theme(qapp, theme)
        yield
    finally:
        qapp.setStyleSheet(before_sheet)
        qapp.setPalette(before_palette)
        theme_manager._APPLIED_THEME = before_marker


def _titles(card):
    return [r.label_widget.text() for r in card.rows() if hasattr(r, "label_widget")]


def _sheet(sm=None, **kw):
    return SettingsSheet(sm or _Settings(), is_dark=True, **kw)


# ── grouping ────────────────────────────────────────────────────────────────

def test_groups_hold_the_shipped_rows(qapp, quiet):
    s = _sheet()
    feats = _titles(s._cards["features"])
    for t in ("Enable Keep-Alive", "Action", "Interval", "Enable Click Sync",
              "Show ghost cursors", "Ghost cursors can use card controls"):
        assert t in feats, t
    assert any(isinstance(r, QLabel) and r.text() == "HOTKEYS"
               for r in s._cards["features"].rows())
    assert any(isinstance(r, QLabel) and r.text() == "CHAT HANDLING"
               for r in s._cards["features"].rows())
    app = _titles(s._cards["app"])
    for t in ("Theme", "Reduce motion", "Use system title bar",
              "Check for updates on startup", "Check for updates now",
              "Verbose logging", "Input Backend", "Clear Stored Credentials"):
        assert t in app, t
    assert "Enable Logging" not in app
    assert _titles(s._cards["strips"]) == [
        "Strip style", "Strip size", "Hide this window once toons are up",
        "Tray icon"]
    assert "TTR Companion App" in _titles(s._cards["ttr"])
    assert "Hide CC launch console" in _titles(s._cards["cc"])


def test_start_in_float_ui_is_dropped(qapp, quiet):
    s = _sheet()
    all_titles = [t for c in s._cards.values() for t in _titles(c)]
    assert "Start in Float UI mode" not in all_titles
    dropped = s._dropped.findChildren(QWidget, "start_in_float_ui_switch")
    assert dropped and not dropped[0].isVisibleTo(s)


def test_rows_use_sheet_material(qapp, quiet):
    s = _sheet()
    ka = s.keep_alive_row()
    assert isinstance(ka, m.SheetRow)
    assert isinstance(ka.control_widget, m.SheetToggle)
    assert ka.control_widget._track_on == "#ff9500"          # Keep-Alive keeps orange
    theme_row = [r for r in s._cards["app"].rows()
                 if getattr(r, "label_widget", None) and r.label_widget.text() == "Theme"][0]
    assert isinstance(theme_row.control_widget, m.SheetSegmented)
    assert theme_row.control_widget._fill == ss.APP[0]       # App rows take App gold


def test_accents_survive_a_theme_change(qapp, quiet):
    s = _sheet()
    s.apply_theme(False)
    s.apply_theme(True)
    assert s.keep_alive_row().control_widget._track_on == "#ff9500"
    theme_row = [r for r in s._cards["app"].rows()
                 if getattr(r, "label_widget", None) and r.label_widget.text() == "Theme"][0]
    assert theme_row.control_widget._fill == ss.APP[0]


# ── behaviour through the shared handlers ───────────────────────────────────

def test_keep_alive_records_consent_before_the_flag(qapp, quiet, monkeypatch):
    sm = _Settings()
    s = _sheet(sm)
    monkeypatch.setattr(s.rows, "_show_keep_alive_warning_dialog", lambda: True)
    sw = s.keep_alive_row().control_widget
    QTest.mouseClick(sw, Qt.LeftButton)
    keys = [k for k, _ in sm.order]
    assert keys.index(sk.KEEP_ALIVE_CONSENT_ACKNOWLEDGED) < keys.index(sk.KEEP_ALIVE_ENABLED)
    assert sm.data[sk.KEEP_ALIVE_ENABLED] is True


def test_theme_segment_emits_on_settings_rows(qapp, quiet):
    s = _sheet()
    fired = []
    s.rows.theme_changed.connect(lambda: fired.append(1))
    s.rows._on_theme_changed(2)
    assert fired == [1]


def test_float_strip_rows_write_their_keys(qapp, quiet):
    sm = _Settings()
    s = _sheet(sm)
    assert s._strip_style.currentIndex() == 0                 # neon by default
    assert s._hide_toggle.isChecked() and s._tray_toggle.isChecked()
    rects = s._strip_style._seg_rects()
    s._strip_style.resize(s._strip_style.sizeHint())
    QTest.mouseClick(s._strip_style, Qt.LeftButton, pos=rects[1].center().toPoint())
    assert sm.data[sk.FLOAT_STRIP_STYLE] == "flat"
    s._hide_toggle.setChecked(False)
    s._tray_toggle.setChecked(False)
    assert sm.data[sk.HIDE_WINDOW_WHEN_TOONS_UP] is False
    assert sm.data[sk.TRAY_ICON] is False


def test_strip_size_row_reads_and_writes_its_key(qapp, quiet):
    sm = _Settings()
    s = _sheet(sm)
    assert s._strip_size.currentIndex() == 1                  # medium by default
    s._strip_size.resize(s._strip_size.sizeHint())
    rects = s._strip_size._seg_rects()
    assert len(rects) == 3
    QTest.mouseClick(s._strip_size, Qt.LeftButton, pos=rects[2].center().toPoint())
    assert sm.data[sk.FLOAT_STRIP_SIZE] == "large"
    QTest.mouseClick(s._strip_size, Qt.LeftButton, pos=rects[0].center().toPoint())
    assert sm.data[sk.FLOAT_STRIP_SIZE] == "small"
    assert _sheet(_Settings({sk.FLOAT_STRIP_SIZE: "large"}))._strip_size.currentIndex() == 2
    assert _sheet(_Settings({sk.FLOAT_STRIP_SIZE: "huge"}))._strip_size.currentIndex() == 1


def test_float_strip_rows_read_stored_values(qapp, quiet):
    s = _sheet(_Settings({sk.FLOAT_STRIP_STYLE: "flat", sk.TRAY_ICON: False,
                          sk.HIDE_WINDOW_WHEN_TOONS_UP: False}))
    assert s._strip_style.currentIndex() == 1
    assert not s._tray_toggle.isChecked() and not s._hide_toggle.isChecked()


def test_game_path_line_follows_the_shared_handler(qapp, quiet):
    s = _sheet()
    s.rows._refresh_game_path_display("ttr", "")
    note = s._path_notes["ttr"]
    assert note.text() == "Not found. Click Browse or Auto-detect."
    assert note.isVisibleTo(s)
    assert "#E05252" in note.styleSheet()
    buttons = [w.text() for w in s._header_buttons["ttr"]]
    assert buttons == ["Browse", "Auto-detect"]


def test_dialogs_parent_to_the_sheet(qapp, quiet):
    s = _sheet()
    assert s.rows._dialog_parent() is s


# ── chips, Logs, About ──────────────────────────────────────────────────────

def test_chips_switch_pages_and_header(qapp, quiet):
    s = _sheet()
    heads = []
    s.header_changed.connect(lambda t, sub: heads.append((t, sub)))
    s.chips["logs"].click()
    assert s.tab() == "logs" and heads[-1] == ("Settings", "What the app has been doing")
    assert s.logs_page.isVisibleTo(s) and not s.settings_page.isVisibleTo(s)
    s.chips["about"].click()
    assert heads[-1] == ("Settings", "ToonTown MultiTool")
    assert s.chips["about"].isChecked() and not s.chips["logs"].isChecked()
    s.set_tab("settings")
    assert s.sub() == "App-wide preferences"


def test_logs_mounts_the_given_widget(qapp, quiet):
    logs = QLabel("console")
    s = _sheet(logs_widget=logs)
    assert logs.parent() is s.logs_page
    assert _sheet()._logs_note is not None


def test_about_shows_version_and_repository(qapp, quiet):
    from utils import build_info
    s = _sheet()
    assert s._version.text() == build_info.version_string()
    assert ss.REPO_URL in s._repo.text()
    assert s._wordmark.pixmap() is not None and not s._wordmark.pixmap().isNull()


# ── mounted, both themes ────────────────────────────────────────────────────

@pytest.mark.parametrize("theme", ["dark", "light"])
def test_mounted_render(qapp, quiet, theme):
    with _theme(qapp, theme):
        is_dark = theme == "dark"
        win = QWidget()
        win.resize(880, 860)
        host = SlideSheetHost(win, is_dark=is_dark)
        s = SettingsSheet(_Settings(), is_dark=is_dark)
        s.header_changed.connect(host.set_header)
        host.open(s, s.IDENTITY, s.TITLE, s.sub())
        win.show()
        qapp.processEvents()
        img = win.grab().toImage()
        # Identity line is Settings green.
        assert img.pixelColor(880 - 300, 112).name() == "#3da343"
        # The Features card's disc is painted in its colour.
        card = s._cards["features"]
        disc = card.disc.mapTo(win, card.disc.rect().center())
        col = img.pixelColor(disc.x() - 9, disc.y())
        assert abs(col.blue() - 0xff) < 30 and col.red() < 40
        # Labels sized by the sheet's own stylesheet, not the app's 12pt.
        assert s.keep_alive_row().label_widget.fontInfo().pixelSize() in (12, 13)
        assert host.panel.header.sub_label.fullText() == "App-wide preferences"
        win.close()


def test_about_keeps_what_the_credits_page_had(qapp, quiet, monkeypatch):
    s = _sheet()
    assert s._hook.text() == "For when one toon isn't enough."
    assert s._byline.text() in ("by flossbud", "by flossbud \U0001F43E")
    text = s._repo.text()
    for url in (ss.REPO_URL, ss.BUG_URL, ss.PRIVACY_URL):
        assert f'href="{url}"' in text
    assert "Report a bug" in text and "Privacy Policy" in text
    # The Credits page's URLs, not new ones.
    import inspect
    import tabs.credits_tab as credits
    src = inspect.getsource(credits)
    for url in (ss.REPO_URL, ss.BUG_URL, ss.PRIVACY_URL):
        assert url in src
    opened = []
    monkeypatch.setattr("utils.open_url.open_url", lambda url: opened.append(url) or True)
    for url in (ss.REPO_URL, ss.BUG_URL, ss.PRIVACY_URL):
        s._repo.linkActivated.emit(url)
    assert opened == [ss.REPO_URL, ss.BUG_URL, ss.PRIVACY_URL]


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_about_labels_are_styled_in_both_themes(qapp, quiet, theme):
    s = SettingsSheet(_Settings(), is_dark=theme == "dark")
    s.set_tab("about")
    for lbl in (s._hook, s._byline, s._about_line, s._version):
        assert "background: transparent" in lbl.styleSheet()
    assert s._hook.fontInfo().pixelSize() == 14
    assert "Noto Color Emoji" in s._byline.styleSheet()


@pytest.mark.parametrize("families,paw", [
    (["DejaVu Sans"], False),
    (["DejaVu Sans", "Noto Color Emoji"], True),
    (["Segoe UI", "Segoe UI Emoji"], True),
])
def test_byline_paw_only_with_an_emoji_font(monkeypatch, families, paw):
    from PySide6.QtGui import QFontDatabase
    monkeypatch.setattr(QFontDatabase, "families", staticmethod(lambda *a: families))
    text = ss._byline_text()
    assert text.startswith("by flossbud")
    assert ("\U0001F43E" in text) is paw
