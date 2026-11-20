"""The header chip, the update sheet and What's new, in a stand-in window and
in the real launchpad window."""
import json
import os
import time

import pytest
from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils import release_highlights, update_flow                    # noqa: E402
from utils.install_method import InstallMethod                       # noqa: E402
from utils.rollcall import motion                                    # noqa: E402
from utils.settings_keys import WHATS_NEW_SEEN_VERSION               # noqa: E402

SIZE = 88_300_000
NOTES = {"version": "v0.8.0-alpha.2",
         "highlights": [{"title": "Light theme", "text": "Follows your system."},
                        {"title": "Logs console", "text": "One live console."},
                        {"title": "Feature discovery", "text": "Hints point things out."}],
         "fixes": ["a", "b", "c"]}


def _info():
    block = "<!-- ttmt:highlights\n" + json.dumps(NOTES) + "\n-->"
    return {"tag_name": "v0.8.0-alpha.2", "body": block, "html_url": "https://example.invalid/r",
            "assets": [{"name": "Setup.exe", "size": SIZE,
                        "browser_download_url": "https://example.invalid/s.exe"}]}


class Settings:
    def __init__(self):
        self.settings = {}
        self.loaded_keys = frozenset({"theme"})

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value


class Downloader(QObject):
    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)

    def start(self, _asset):
        return True

    def shutdown(self):
        pass


@pytest.fixture(autouse=True)
def frozen_clock(tmp_path, monkeypatch):
    from utils import update_download
    monkeypatch.setattr(update_download, "download_dir", lambda: str(tmp_path / "dl"))
    os.makedirs(tmp_path / "dl", exist_ok=True)
    motion.set_now(0)
    motion.set_reduced(False)
    yield
    motion.set_now(None)


def _settle(host):
    for _ in range(30):
        motion.advance(100)
        host._on_tick()
        host.stage._on_tick()


@pytest.fixture
def standin(qapp):
    from utils.widgets.launchpad.header import HEADER_H, LaunchpadHeader
    from utils.widgets.launchpad.update_sheet import UpdateSheetHost
    window = QWidget()
    window.resize(880, 860)
    window.header = LaunchpadHeader(window)
    window.header.setGeometry(0, 0, 880, HEADER_H)
    window.sheet = UpdateSheetHost(window, top=HEADER_H)
    toons = {"up": False}
    downloader = Downloader()
    flow = update_flow.UpdateFlow(
        Settings(), install_method=InstallMethod.WINDOWS_INSTALLER,
        local_tag="v0.8.0-alpha.1", downloader=downloader,
        start_update_window=lambda *a, **k: True, toons_running=lambda: toons["up"])
    flow.changed.connect(lambda: window.header.set_update_chip(flow.chip()))
    flow.sheet_requested.connect(
        lambda show: window.sheet.show_update() if show else window.sheet.hide_sheet())
    window.sheet.set_flow(flow)
    window.flow, window.downloader, window.toons = flow, downloader, toons
    window.show()
    yield window
    for ticker in (window.sheet._ticker, window.sheet.stage._ticker,
                   window.sheet.stage.copy._ticker, window.header.update_chip._ticker):
        ticker.stop()
    window.close()
    window.deleteLater()


# ── The chip ───────────────────────────────────────────────────────────────


def test_the_chip_takes_the_session_statuss_place_and_gives_it_back(standin):
    header = standin.header
    header.set_toon_count(2)
    assert header.status.isVisible() and not header.update_chip.isVisible()
    standin.flow.on_update_available(_info())
    assert header.update_chip.isVisible() and not header.status.isVisible()
    assert header.update_chip.chip().label == "Update ready"
    standin.flow.skip()
    assert not header.update_chip.isVisible() and header.status.isVisible()


def test_the_chip_sits_right_14_and_never_reaches_the_wordmark(standin):
    from utils.widgets.launchpad.update_chip import FOCUS_PAD
    header = standin.header
    standin.flow.on_check_started(True)
    standin.flow.on_check_failed("offline")           # the longest label
    chip = header.update_chip
    right = chip.x() + chip.width() - FOCUS_PAD
    assert right == header.width() - 14
    assert chip.y() + FOCUS_PAD == 58 and chip.height() - 2 * FOCUS_PAD == 28
    logo_right = header.logo.x() + header.logo.width()
    assert chip.x() + FOCUS_PAD > logo_right


def test_a_quiet_chip_is_not_clickable(standin, qapp):
    clicks = []
    standin.header.update_chip_clicked.connect(lambda: clicks.append(1))
    standin.flow.on_check_started(True)
    chip = standin.header.update_chip
    QTest.mouseClick(chip, Qt.LeftButton, pos=QPoint(chip.width() // 2, chip.height() // 2))
    assert clicks == []
    standin.flow.on_update_available(_info())
    QTest.mouseClick(chip, Qt.LeftButton, pos=QPoint(chip.width() // 2, chip.height() // 2))
    assert clicks == [1]


def test_the_downloading_chip_carries_the_percentage(standin):
    standin.flow.on_update_available(_info())
    standin.flow.update_now()
    standin.downloader.progress.emit(int(SIZE * 0.42), SIZE)
    chip = standin.header.update_chip
    assert chip.chip().percent == 42 and chip.accessibleName() == "Downloading 42%"
    width = chip.width()
    standin.downloader.progress.emit(SIZE, SIZE)
    assert chip.width() == width                      # counting does not resize it


# ── The update sheet ───────────────────────────────────────────────────────


def test_the_sheet_is_inset_14_below_the_header_and_310_high(standin):
    from utils.widgets.launchpad.header import HEADER_H
    standin.flow.on_update_available(_info())
    sheet = standin.sheet
    _settle(sheet)
    assert sheet.is_open() and sheet.geometry().top() == HEADER_H
    stage = sheet.stage.geometry()
    assert (stage.x(), stage.y(), stage.width(), stage.height()) == (14, 14, 880 - 28, 310)
    # Copy pinned left, crew pinned right with the last toon flush.
    assert sheet.stage.slot_rect(1).right() == pytest.approx(stage.width())
    assert sheet.stage.slot_rect(1).x() - sheet.stage.slot_rect(0).x() == 62


def test_the_offer_shows_three_highlights_and_one_gold_button(standin):
    standin.flow.on_update_available(_info())
    texts = standin.sheet.texts()
    assert texts[:2] == ["Update \u00b7 v0.8.0-alpha.1 \u2192 v0.8.0-alpha.2",
                         "A new build is ready."]
    for title in ("Light theme", "Logs console", "Feature discovery"):
        assert title in texts
    kinds = [getattr(c, "kind", "") for c in standin.sheet.stage.copy.controls()]
    assert kinds.count("gold") == 1
    assert standin.sheet.stage.floor_labels() == ["84.2 MB \u00b7 installs after a restart"]
    assert standin.sheet.stage.crew_present() == 2


def test_the_sheet_follows_the_download_without_replaying_the_copy(standin):
    standin.flow.on_update_available(_info())
    for control in standin.sheet.stage.copy.controls():
        if control.text() == "Update now":
            control.click()
    assert "Getting it ready." in standin.sheet.texts()
    hide = standin.sheet.stage.copy.controls()[0]
    standin.downloader.progress.emit(int(SIZE * 0.5), SIZE)
    assert standin.sheet.stage.copy.controls()[0] is hide     # same copy, new numbers
    assert standin.sheet.stage.floor_tail() == "50%"
    assert standin.sheet.stage.floor_fractions() == [pytest.approx(0.5)]
    standin.downloader.failed.emit("network")
    assert "Lost the connection." in standin.sheet.texts()
    assert standin.sheet.stage.crew_bad() == 1 and standin.sheet.stage.floor_failed() == 0


def test_the_scrim_hides_the_sheet_and_cancels_nothing(standin):
    standin.flow.on_update_available(_info())
    standin.flow.update_now()
    sheet = standin.sheet
    _settle(sheet)
    QTest.mouseClick(sheet, Qt.LeftButton, pos=QPoint(400, 500))     # below the sheet
    _settle(sheet)
    assert not sheet.is_open() and not sheet.isVisible()
    assert standin.flow.state == update_flow.DOWNLOADING
    assert standin.header.update_chip.chip().kind == update_flow.CHIP_DOWNLOADING


def test_a_click_on_the_sheet_itself_does_not_hide_it(standin):
    standin.flow.on_update_available(_info())
    sheet = standin.sheet
    _settle(sheet)
    QTest.mouseClick(sheet.stage, Qt.LeftButton, pos=QPoint(500, 100))
    assert sheet.is_open()


def test_ready_shows_in_game_copy_while_toons_are_up(standin):
    standin.flow.on_update_available(_info())
    standin.flow.update_now()
    standin.sheet.hide_sheet()
    standin.toons["up"] = True
    standin.downloader.finished.emit("C:\\Temp\\setup.exe")
    assert not standin.sheet.is_open()
    standin.sheet.show_update()
    assert "Your toons are still in game." in standin.sheet.texts()
    golds = [c.text() for c in standin.sheet.stage.copy.controls()
             if getattr(c, "kind", "") == "gold"]
    assert golds == ["Next launch"]


# ── What's new ─────────────────────────────────────────────────────────────


def test_whats_new_pages_through_the_highlights(standin):
    notes = release_highlights._parse(NOTES)
    urls, closed = [], []
    standin.sheet.open_url.connect(urls.append)
    standin.sheet.closed.connect(closed.append)
    standin.sheet.show_whats_new(notes, "https://example.invalid/tag")
    sheet = standin.sheet
    assert sheet.texts()[:3] == ["New in v0.8.0-alpha.2 \u00b7 1 of 3", "Light theme",
                                 "Follows your system."]
    assert sheet.stage.solo() == 2                    # toons 2, 3, 4 present 1, 2, 3
    controls = {c.text(): c for c in sheet.stage.copy.controls()}
    controls["Release notes"].click()
    assert urls == ["https://example.invalid/tag"]
    controls["Next"].click()
    assert sheet.page() == 1 and sheet.stage.solo() == 3 and sheet.stage.page() == 1
    sheet.stage.page_clicked.emit(2)
    assert "Feature discovery" in sheet.texts() and sheet.stage.solo() == 4
    {c.text(): c for c in sheet.stage.copy.controls()}["Got it"].click()
    _settle(sheet)
    assert not sheet.is_open() and closed == ["whats_new"]


# ── In the real window ─────────────────────────────────────────────────────


def _dispose(window, qapp):
    window._quitting = True
    window.close()
    qapp.processEvents()


@pytest.fixture
def launchpad(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TTMT_SELF_CHECK", "1")
    monkeypatch.setenv("TTMT_GRANDSTAND", "1")
    checks = []
    monkeypatch.setattr("utils.update_checker.UpdateChecker.check_async",
                        lambda self, *, manual: checks.append(manual) or True)
    quits = []
    monkeypatch.setattr("utils.launchpad_window._quit_app", lambda: quits.append(1))
    from utils.launchpad_window import LaunchpadWindow
    window = LaunchpadWindow()
    window.resize(880, 860)
    window.show()
    qapp.processEvents()
    window.checks, window.quits = checks, quits
    yield window
    _dispose(window, qapp)


def test_the_launchpad_wires_the_checker_to_the_chip_and_the_sheet(launchpad, capsys):
    window = launchpad
    assert window.update_flow.local_tag.startswith("v")
    window.update_checker.check_started.emit(True)
    assert window.header.update_chip.chip().kind == update_flow.CHIP_CHECKING
    window.update_checker.update_available.emit(_info_newer(window))
    assert window.header.update_chip.chip().kind == update_flow.CHIP_UPDATE
    assert window.update_sheet.is_open()
    assert "A new build is ready." in window.update_sheet.texts()


def _info_newer(window):
    info = _info()
    info["tag_name"] = "v99.0.0"
    return info


def test_the_chip_toggles_the_sheet(launchpad, qapp):
    window = launchpad
    window.update_checker.update_available.emit(_info_newer(window))
    window.header.update_chip_clicked.emit()
    assert not window.update_sheet.is_open()
    window.header.update_chip_clicked.emit()
    assert window.update_sheet.is_open()


def test_retry_from_the_chip_checks_again(launchpad):
    window = launchpad
    window.update_checker.check_started.emit(True)
    window.update_checker.check_failed.emit("offline")
    window.header.update_chip_clicked.emit()
    assert window.checks == [True]


def test_a_handed_over_update_quits_the_app(launchpad):
    window = launchpad
    window.update_flow.quit_requested.emit()
    assert window._quitting is True


def test_whats_new_shows_once_for_an_updated_install(launchpad, monkeypatch):
    window = launchpad
    tag = window.update_flow.local_tag
    notes = release_highlights._parse(dict(NOTES, version=tag))
    monkeypatch.setattr(release_highlights, "shipped", lambda: notes)
    monkeypatch.setattr("utils.update_flow.is_first_run", lambda _sm: False)
    window._maybe_show_whats_new()
    assert window.update_sheet.mode() == "whats_new"
    assert f"New in {tag} \u00b7 1 of 3" in window.update_sheet.texts()
    window.update_sheet.hide_sheet()
    deadline = time.monotonic() + 3
    while window.update_sheet.isVisible() and time.monotonic() < deadline:
        motion.advance(200)
        window.update_sheet._on_tick()
    assert window.settings_manager.get(WHATS_NEW_SEEN_VERSION) == tag
    assert window.header.update_chip.chip().kind == update_flow.CHIP_WHATS_NEW
    window.header.update_chip_clicked.emit()             # the chip reopens it at page 1
    assert window.update_sheet.mode() == "whats_new" and window.update_sheet.page() == 0


def test_a_first_run_is_not_shown_whats_new(launchpad, monkeypatch):
    window = launchpad
    tag = window.update_flow.local_tag
    monkeypatch.setattr(release_highlights, "shipped",
                        lambda: release_highlights._parse(dict(NOTES, version=tag)))
    monkeypatch.setattr("utils.update_flow.is_first_run", lambda _sm: True)
    window._maybe_show_whats_new()
    assert not window.update_sheet.is_open()
    assert window.settings_manager.get(WHATS_NEW_SEEN_VERSION) == tag
