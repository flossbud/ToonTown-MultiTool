"""The in-app update flow: chip, sheet views, actions, "Next launch",
What's new, and the structured release notes behind them."""
import json
import os

import pytest
from PySide6.QtCore import QObject, Signal

from utils import release_highlights, update_download, update_flow
from utils.install_method import InstallMethod
from utils.settings_keys import (
    UPDATE_OFFER_SHOWN_VERSION, UPDATE_PENDING_INSTALL, UPDATE_SKIPPED_VERSION,
    WHATS_NEW_SEEN_VERSION,
)

SIZE = 88_300_000
NOTES = {
    "highlights": [{"title": "Light theme", "text": "Follows your system."},
                   {"title": "Logs console", "text": "One live console."},
                   {"title": "Feature discovery", "text": "Hints point things out."}],
    "fixes": 3,
}
BLOCK = "<!-- ttmt:highlights\n" + json.dumps(NOTES) + "\n-->"


def _info(tag="v0.8.0-alpha.2", body="Notes.\n\n" + BLOCK):
    return {
        "tag_name": tag, "body": body, "html_url": "https://example.invalid/r",
        "assets": [{"name": f"ToonTownMultiTool-Setup-{tag}.exe", "size": SIZE,
                    "browser_download_url": "https://example.invalid/s.exe"},
                   {"name": "ToonTownMultiTool.AppImage", "size": 1}],
    }


class Settings:
    def __init__(self, loaded=("theme",)):
        self.settings = {}
        self.loaded_keys = frozenset(loaded)

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value


class Downloader(QObject):
    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.started = []

    def start(self, asset):
        self.started.append(asset)
        return True

    def shutdown(self):
        pass


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(update_download, "download_dir", lambda: str(tmp_path))
    return tmp_path


def _flow(qapp, downloads, method=InstallMethod.WINDOWS_INSTALLER, toons=None, **kwargs):
    toons = toons if toons is not None else {"up": False}
    settings = kwargs.pop("settings", None) or Settings()
    downloader = Downloader()
    native = []
    windows = []

    def start_window(path, *, app_pid, from_version):
        windows.append((path, app_pid, from_version))
        return kwargs.get("window_starts", True)

    flow = update_flow.UpdateFlow(
        settings, install_method=method, local_tag="v0.8.0-alpha.1",
        downloader=downloader, run_native_update=native.append,
        start_update_window=start_window, toons_running=lambda: toons["up"])
    flow.sheet = []
    flow.sheet_requested.connect(flow.sheet.append)
    flow.quits = []
    flow.quit_requested.connect(lambda: flow.quits.append(1))
    flow.settings, flow.downloader, flow.native, flow.windows = settings, downloader, native, windows
    return flow


# ── Release notes ──────────────────────────────────────────────────────────


def test_highlights_are_read_from_the_release_body():
    notes = release_highlights.from_release_body("Text\n" + BLOCK, "v1.0.0")
    assert [h.title for h in notes.highlights] == [
        "Light theme", "Logs console", "Feature discovery"]
    assert notes.fix_count == 3 and notes.more_text() == "+ 3 bug fixes"
    assert notes.version == "v1.0.0"


@pytest.mark.parametrize("body", ["", "No block here.", "<!-- ttmt:highlights {not json} -->",
                                  '<!-- ttmt:highlights {"highlights": []} -->'])
def test_a_body_without_a_usable_block_has_no_notes(body):
    assert release_highlights.from_release_body(body) is None


def test_at_most_three_highlights_and_a_singular_fix():
    data = {"highlights": [{"title": str(i)} for i in range(5)], "fixes": ["one"]}
    notes = release_highlights._parse(data)
    assert len(notes.highlights) == 3 and notes.more_text() == "+ 1 bug fix"


def test_the_shipped_file_round_trips_through_the_body_block():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "whats_new.json")
    shipped = release_highlights.from_file(path)
    assert shipped and len(shipped.highlights) == 3 and shipped.version.startswith("v")
    again = release_highlights.from_release_body(release_highlights.body_block(path))
    assert again.highlights == shipped.highlights and again.fix_count == shipped.fix_count


# ── The chip ───────────────────────────────────────────────────────────────


def test_nothing_to_say_means_no_chip(qapp, downloads):
    assert _flow(qapp, downloads).chip() is None


def test_a_manual_check_answers_in_the_chip(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_check_started(True)
    assert flow.chip().kind == update_flow.CHIP_CHECKING and not flow.chip().clickable
    flow.on_no_update()
    assert flow.chip().kind == update_flow.CHIP_UP_TO_DATE
    flow._transient_timer.timeout.emit()           # about 2.5 s later
    assert flow.chip() is None
    assert flow.sheet == []                        # nothing opens


def test_a_failed_manual_check_can_be_retried_from_the_chip(qapp, downloads):
    flow = _flow(qapp, downloads)
    again = []
    flow.recheck_requested.connect(lambda: again.append(1))
    flow.on_check_started(True)
    flow.on_check_failed("offline")
    assert flow.chip().label == "Couldn\u2019t check \u00b7 Retry"
    flow.chip_clicked()
    assert again == [1]


def test_automatic_checks_are_silent_unless_they_find_something(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_check_started(False)
    assert flow.chip() is None
    flow.on_no_update()
    assert flow.chip() is None
    flow.on_check_started(False)
    flow.on_check_failed("offline")
    assert flow.chip() is None


# ── Offer ──────────────────────────────────────────────────────────────────


def test_an_update_shows_the_chip_and_opens_the_offer_once_per_version(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_check_started(False)
    flow.on_update_available(_info())
    assert flow.chip() == update_flow.Chip(update_flow.CHIP_UPDATE, "Update ready")
    assert flow.sheet == [True]
    assert flow.settings.get(UPDATE_OFFER_SHOWN_VERSION) == "v0.8.0-alpha.2"
    view = flow.view()
    assert view.key == "offer"
    assert view.micro == "Update \u00b7 v0.8.0-alpha.1 \u2192 v0.8.0-alpha.2"
    assert view.highlights == ("Light theme", "Logs console", "Feature discovery")
    assert view.primary == ("Update now", "update_now")
    assert view.secondary == ("Later", "later") and view.link == ("Skip this version", "skip")
    assert view.floor_label == "84.2 MB \u00b7 installs after a restart"

    second = _flow(qapp, downloads, settings=flow.settings)
    second.on_check_started(False)
    second.on_update_available(_info())
    assert second.sheet == [] and second.chip().kind == update_flow.CHIP_UPDATE


def test_the_offer_never_opens_by_itself_over_running_toons(qapp, downloads):
    flow = _flow(qapp, downloads, toons={"up": True})
    flow.on_check_started(False)
    flow.on_update_available(_info())
    assert flow.sheet == [] and flow.chip().kind == update_flow.CHIP_UPDATE
    assert flow.settings.get(UPDATE_OFFER_SHOWN_VERSION) is None


def test_a_manual_check_that_finds_an_update_opens_the_offer(qapp, downloads):
    flow = _flow(qapp, downloads, toons={"up": True})
    flow.on_check_started(True)
    flow.on_update_available(_info())
    assert flow.sheet == [True]


def test_a_release_without_highlights_still_offers(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_update_available(_info(body="Plain notes."))
    view = flow.view()
    assert view.highlights == () and view.body


def test_later_hides_and_keeps_the_chip(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_update_available(_info())
    flow.later()
    assert flow.sheet[-1] is False and flow.chip().kind == update_flow.CHIP_UPDATE


def test_skip_stores_the_tag_and_removes_the_chip(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_update_available(_info())
    flow.skip()
    assert flow.settings.get(UPDATE_SKIPPED_VERSION) == "v0.8.0-alpha.2"
    assert flow.chip() is None and flow.view() is None and flow.sheet[-1] is False


# ── Download ───────────────────────────────────────────────────────────────


def test_update_now_downloads_in_the_background(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_update_available(_info())
    flow.update_now()
    assert flow.state == update_flow.DOWNLOADING
    assert flow.downloader.started[0]["name"].endswith(".exe")
    flow.downloader.progress.emit(int(SIZE * 0.42), SIZE)
    chip = flow.chip()
    assert chip.kind == update_flow.CHIP_DOWNLOADING and chip.percent == 42
    view = flow.view()
    assert view.key == "dl" and view.primary is None and view.secondary == ("Hide", "later")
    assert view.floor_label == "Downloading \u00b7 35.4 of 84.2 MB" and view.floor_tail == "42%"
    assert view.fraction == pytest.approx(0.42)


def test_a_dropped_connection_pauses_and_try_again_resumes(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_update_available(_info())
    flow.update_now()
    flow.downloader.progress.emit(int(SIZE * 0.37), SIZE)
    flow.downloader.failed.emit(update_download.REASON_NETWORK)
    assert flow.chip() == update_flow.Chip(update_flow.CHIP_PAUSED, "Update paused")
    view = flow.view()
    assert view.key == "fail" and view.micro_bad and view.headline == "Lost the connection."
    assert view.crew_present == 1 and view.crew_bad == 1 and view.floor_bad
    assert view.primary == ("Try again", "try_again")
    flow.try_again()
    assert flow.state == update_flow.DOWNLOADING and len(flow.downloader.started) == 2


def test_a_damaged_download_says_it_starts_over(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_update_available(_info())
    flow.update_now()
    flow.downloader.failed.emit(update_download.REASON_VERIFY)
    assert flow.view().headline == "The download was damaged."


def test_ready_reopens_the_sheet_when_nobody_is_playing(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_update_available(_info())
    flow.later()
    flow.update_now()
    flow.downloader.finished.emit("C:\\Temp\\setup.exe")
    assert flow.sheet[-1] is True
    assert flow.chip() == update_flow.Chip(update_flow.CHIP_RESTART, "Restart to update")
    view = flow.view()
    assert view.key == "ready" and view.hop
    assert view.primary == ("Restart & update", "restart_now")
    assert view.secondary == ("Next launch", "next_launch")


def test_ready_with_toons_in_game_only_turns_the_chip_green(qapp, downloads):
    toons = {"up": False}
    flow = _flow(qapp, downloads, toons=toons)
    flow.on_update_available(_info())
    flow.update_now()
    flow.later()
    toons["up"] = True
    before = list(flow.sheet)
    flow.downloader.finished.emit("C:\\Temp\\setup.exe")
    assert flow.sheet == before                        # nothing opened
    assert flow.chip().kind == update_flow.CHIP_RESTART
    view = flow.view()
    assert view.key == "ingame" and view.headline == "Your toons are still in game."
    assert view.primary == ("Next launch", "next_launch")      # the safe action is gold
    assert view.secondary == ("Restart anyway", "restart_now")


def test_restart_hands_over_to_the_update_window_and_quits(qapp, downloads):
    flow = _flow(qapp, downloads)
    flow.on_update_available(_info())
    flow.update_now()
    flow.downloader.finished.emit("C:\\Temp\\setup.exe")
    flow.restart_now()
    assert flow.windows == [("C:\\Temp\\setup.exe", os.getpid(), "v0.8.0-alpha.1")]
    assert flow.quits == [1]


def test_an_update_window_that_never_comes_up_keeps_the_app_running(qapp, downloads):
    flow = _flow(qapp, downloads, window_starts=False)
    flow.on_update_available(_info())
    flow.update_now()
    flow.downloader.finished.emit("C:\\Temp\\setup.exe")
    flow.restart_now()
    assert flow.quits == []
    view = flow.view()
    assert view.key == "fail" and view.headline == "The installer didn\u2019t start."
    assert view.primary == ("Try again", "restart_now")


def test_a_build_downloaded_on_an_earlier_run_is_ready_at_once(qapp, downloads):
    info = _info()
    asset = info["assets"][0]
    asset["size"] = 10
    (downloads / asset["name"]).write_bytes(b"0123456789")
    flow = _flow(qapp, downloads)
    flow.on_update_available(info)
    assert flow.state == update_flow.READY
    assert flow.installer_path == str(downloads / asset["name"])


# ── Other install methods ──────────────────────────────────────────────────


@pytest.mark.parametrize("method", [InstallMethod.APPIMAGE, InstallMethod.FLATPAK,
                                    InstallMethod.AUR, InstallMethod.DEB, InstallMethod.SOURCE])
def test_other_install_methods_keep_their_own_update_action(qapp, downloads, method):
    flow = _flow(qapp, downloads, method=method)
    flow.on_update_available(_info())
    assert flow.chip().kind == update_flow.CHIP_UPDATE
    view = flow.view()
    assert view.key == "offer" and "MB" not in view.floor_label and view.floor_label
    flow.update_now()
    assert flow.native == [flow.info] and flow.downloader.started == []
    assert flow.state == update_flow.OFFER and flow.sheet[-1] is False


# ── Next launch ────────────────────────────────────────────────────────────


def _ready(qapp, downloads, path):
    flow = _flow(qapp, downloads)
    flow.on_update_available(_info())
    flow.update_now()
    flow.downloader.finished.emit(path)
    return flow


def test_next_launch_remembers_the_downloaded_build(qapp, downloads):
    flow = _ready(qapp, downloads, "C:\\Temp\\setup.exe")
    flow.next_launch()
    pending = json.loads(flow.settings.get(UPDATE_PENDING_INSTALL))
    assert pending == {"tag": "v0.8.0-alpha.2", "path": "C:\\Temp\\setup.exe", "size": SIZE}
    assert flow.sheet[-1] is False and flow.chip().kind == update_flow.CHIP_RESTART


def _pending(settings, tmp_path, tag="v0.8.0-alpha.2", data=b"installer"):
    path = tmp_path / "setup.exe"
    path.write_bytes(data)
    settings.set(UPDATE_PENDING_INSTALL, json.dumps(
        {"tag": tag, "path": str(path), "size": len(data)}))
    return path


def test_a_waiting_build_installs_before_the_window_opens(tmp_path):
    settings = Settings()
    path = _pending(settings, tmp_path)
    calls = []

    def start(p, *, app_pid, from_version):
        calls.append((p, app_pid, from_version))
        return True

    assert update_flow.install_pending_at_startup(
        settings, local_tag="v0.8.0-alpha.1", start_update_window=start, app_pid=77) is True
    assert calls == [(str(path), 77, "v0.8.0-alpha.1")]
    assert not settings.get(UPDATE_PENDING_INSTALL)       # one attempt per build


def test_an_already_installed_waiting_build_is_cleaned_up(tmp_path):
    settings = Settings()
    path = _pending(settings, tmp_path, tag="v0.8.0-alpha.1")
    assert update_flow.install_pending_at_startup(
        settings, local_tag="v0.8.0-alpha.1",
        start_update_window=lambda *a, **k: pytest.fail("must not start")) is False
    assert not settings.get(UPDATE_PENDING_INSTALL) and not path.exists()


def test_a_missing_or_truncated_waiting_build_is_forgotten(tmp_path):
    settings = Settings()
    path = _pending(settings, tmp_path)
    path.write_bytes(b"cut")
    assert update_flow.install_pending_at_startup(
        settings, local_tag="v0.8.0-alpha.1",
        start_update_window=lambda *a, **k: pytest.fail("must not start")) is False
    assert not settings.get(UPDATE_PENDING_INSTALL)


def test_an_update_window_that_fails_to_start_does_not_block_startup(tmp_path):
    settings = Settings()
    _pending(settings, tmp_path)
    assert update_flow.install_pending_at_startup(
        settings, local_tag="v0.8.0-alpha.1",
        start_update_window=lambda *a, **k: False) is False
    assert not settings.get(UPDATE_PENDING_INSTALL)


# ── What's new ─────────────────────────────────────────────────────────────


def _notes(version="v0.8.0-alpha.2"):
    return release_highlights._parse(NOTES, version)


def test_whats_new_shows_once_after_an_update():
    settings = Settings(loaded=("theme", "accounts"))
    notes = _notes()
    assert update_flow.whats_new_to_show(settings, notes, "v0.8.0-alpha.2", False) is notes
    settings.set(WHATS_NEW_SEEN_VERSION, "v0.8.0-alpha.2")
    assert update_flow.whats_new_to_show(settings, notes, "v0.8.0-alpha.2", False) is None


def test_a_first_run_marks_it_seen_without_showing():
    settings = Settings(loaded=("check_for_updates_at_startup",))
    assert update_flow.is_first_run(settings)
    assert update_flow.whats_new_to_show(settings, _notes(), "v0.8.0-alpha.2", True) is None
    assert settings.get(WHATS_NEW_SEEN_VERSION) == "v0.8.0-alpha.2"


def test_an_existing_settings_file_is_not_a_first_run():
    assert not update_flow.is_first_run(Settings(loaded=("theme", "hints_enabled")))
    assert update_flow.is_first_run(Settings(loaded=()))


def test_notes_for_another_version_are_not_shown():
    settings = Settings()
    assert update_flow.whats_new_to_show(settings, _notes("v0.7.0"), "v0.8.0-alpha.2", False) is None
    assert update_flow.whats_new_to_show(settings, None, "v0.8.0-alpha.2", False) is None


def test_closing_whats_new_leaves_a_chip_for_the_session(qapp, downloads):
    flow = _flow(qapp, downloads)
    asked = []
    flow.whats_new_requested.connect(lambda: asked.append(1))
    flow.mark_whats_new_seen(_notes())
    assert flow.settings.get(WHATS_NEW_SEEN_VERSION) == "v0.8.0-alpha.1"
    assert flow.chip() == update_flow.Chip(update_flow.CHIP_WHATS_NEW, "What\u2019s new")
    flow.chip_clicked()
    assert asked == [1]
    flow.on_update_available(_info())                 # an update outranks it
    assert flow.chip().kind == update_flow.CHIP_UPDATE
