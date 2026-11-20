"""The Roll Call installer, update window and uninstaller as state machines
over the engine contract. The timer engine is driven by hand: its clock is
stopped and the tests emit the engine's signals themselves."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils.rollcall import motion                                    # noqa: E402
from utils.rollcall.engine import (                                  # noqa: E402
    INDETERMINATE, INSTALL_STEPS, Failure, FakeEngine, Flavor, Installed, InstallOptions,
)

FLAVOR = Flavor(version="v0.8.0-alpha.2", build=412, payload_bytes=221_000_000)
DIRECTORY = "C:\\Users\\P\\AppData\\Local\\Programs\\ToonTown MultiTool"
FAILURE = Failure(step=1, headline="Couldn\u2019t copy the files.",
                  body="Windows blocked writing to the install folder.",
                  detail="Access is denied \u00b7 0x80070005", log_path="C:\\log.txt")


@pytest.fixture(autouse=True)
def frozen_clock():
    motion.set_now(0)
    motion.set_reduced(False)
    yield
    motion.set_now(None)


def _engine(**kwargs):
    engine = FakeEngine(flavor=FLAVOR, **kwargs)
    engine._timer.setInterval(10_000_000)        # the tests are the clock
    return engine


def _button(window, text):
    for control in window.stage.copy.controls():
        if control.text() == text:
            return control
    raise AssertionError(f"no control {text!r} in {window.stage.copy.texts()}")


def _has(window, text):
    return any(c.text() == text for c in window.stage.copy.controls())


def _settle(window):
    for _ in range(40):
        motion.advance(100)
        window.stage._on_tick()


# ── Motion ─────────────────────────────────────────────────────────────────


def test_a_tween_reads_the_stage_clock():
    tween = motion.Tween(0.0)
    tween.to(10.0, 100)
    assert tween.value() == 0.0 and tween.active()
    motion.advance(100)
    assert tween.value() == 10.0 and not tween.active()


def test_the_follower_completes_earlier_steps_and_never_goes_back():
    follower = motion.RunFollower(4)
    follower.report(2, 0.5)
    follower.report(1, 0.9)                    # late, out of order: ignored
    for _ in range(40):
        motion.advance(100)
        follower.frame()
    assert follower.shown[:2] == [1.0, 1.0]
    assert follower.shown[2] == pytest.approx(0.5, abs=0.01)
    assert follower.step == 2


def test_an_unmeasured_step_creeps_but_never_finishes_by_itself():
    follower = motion.RunFollower(3)
    follower.report(0, INDETERMINATE)
    for _ in range(600):
        motion.advance(100)
        follower.frame()
    assert 0.5 < follower.shown[0] <= follower.CREEP_LIMIT + 0.001


def test_a_held_follower_stays_where_it_is():
    follower = motion.RunFollower(2)
    follower.report(0, 0.8)
    follower.held = True
    motion.advance(5000)
    follower.frame()
    assert follower.shown[0] == 0.0


def test_a_retry_keeps_the_steps_before_the_failed_one():
    follower = motion.RunFollower(4)
    follower.reset(keep_before=2)
    assert follower.shown == [1.0, 1.0, 0.0, 0.0] and follower.step == 2


# ── Installer ──────────────────────────────────────────────────────────────


def _installer(qapp, **kwargs):
    from utils.rollcall.installer import InstallerWindow
    engine = _engine(**kwargs)
    window = InstallerWindow(engine)
    window.show()
    return window, engine


def test_relation_prefers_build_numbers_and_falls_back_to_tags():
    from utils.rollcall.installer import FRESH, NEWER, SAME, UPGRADE, relation
    assert relation(None, "v1.0.0", 5) == FRESH
    assert relation(Installed("v1.0.0", 5, "d", False), "v1.0.0", 5) == SAME
    assert relation(Installed("v1.0.0", 4, "d", False), "v1.0.0", 5) == UPGRADE
    assert relation(Installed("v1.0.0", 9, "d", False), "v1.0.0", 5) == NEWER
    assert relation(Installed("v0.8.0-alpha.1", 0, "d", False), "v0.8.0-alpha.2", 5) == UPGRADE
    assert relation(Installed("v0.8.1", 0, "d", False), "v0.8.0-alpha.2", 0) == NEWER
    assert relation(Installed("v0.8.0-alpha.2", 0, "d", False), "v0.8.0-alpha.2", 0) == SAME


def test_fresh_install_opens_on_the_welcome_with_one_gold_button(qapp):
    window, _engine_ = _installer(qapp)
    assert window.state == "idle"
    texts = window.stage.copy.texts()
    assert texts[0] == "Windows \u00b7 v0.8.0-alpha.2"
    assert "Control four toons at once." in texts
    golds = [c for c in window.stage.copy.controls() if getattr(c, "kind", "") == "gold"]
    assert [g.text() for g in golds] == ["Install"]
    assert _has(window, "Customize")
    assert window.stage.crew_present() == 0
    assert window.stage.floor_labels() == list(INSTALL_STEPS)
    assert any("210.8 MB" in t and "ToonTown MultiTool" in t for t in texts)


def test_install_runs_a_toon_per_step_and_ends_with_everyone(qapp):
    window, engine = _installer(qapp)
    _button(window, "Install").click()
    assert window.state == "run"
    assert engine.last_options == engine.default_options()
    engine.step_progress.emit(0, 0.5)
    assert window.stage.crew_present() == 1
    engine.step_progress.emit(2, 0.1)
    assert window.stage.crew_present() == 3
    assert window.stage.copy.headline_text() == "Creating shortcuts"
    assert "Installing \u00b7 step 3 of 4" in window.stage.copy.texts()
    engine.finished.emit()
    assert window.state == "done"
    assert window.stage.crew_present() == 4
    assert "Everyone\u2019s here." in window.stage.copy.texts()
    assert window.stage.floor_fractions() == [1.0] * 4
    _button(window, "Open MultiTool").click()
    assert engine.opened == 1 and not window.isVisible()


def test_cancel_pauses_asks_and_keep_going_resumes(qapp):
    window, engine = _installer(qapp)
    _button(window, "Install").click()
    engine.step_progress.emit(1, 0.3)
    _button(window, "Cancel").click()
    assert window.state == "ask" and engine._paused
    assert "Stop installing?" in window.stage.copy.texts()
    assert "Paused \u00b7 step 2 of 4" in window.stage.copy.texts()
    _button(window, "Keep going").click()
    assert window.state == "run" and not engine._paused


def test_stop_undoes_and_start_over_returns_to_the_welcome(qapp):
    window, engine = _installer(qapp)
    _button(window, "Install").click()
    engine.step_progress.emit(1, 0.3)
    _button(window, "Cancel").click()
    _button(window, "Stop").click()
    assert window.state == "stopping"
    qapp.processEvents()                       # the engine reports the undo
    assert window.state == "undone"
    assert "Nothing was installed." in window.stage.copy.texts()
    assert window.stage.crew_present() == 0
    _button(window, "Start over").click()
    assert window.state == "idle"


def test_the_close_button_mid_install_behaves_like_cancel(qapp):
    window, engine = _installer(qapp)
    _button(window, "Install").click()
    engine.step_progress.emit(1, 0.3)
    assert window.request_close() is False
    assert window.state == "ask"
    assert window.request_close() is False     # still deciding: stays open


def test_cancel_is_hidden_once_the_engine_cannot_undo(qapp):
    window, engine = _installer(qapp)
    _button(window, "Install").click()
    engine.can_cancel = lambda: False
    engine.step_progress.emit(2, 0.1)
    assert not _button(window, "Cancel").isVisible()
    assert window.request_close() is False and window.state == "run"


def test_a_declined_elevation_prompt_lands_on_undone(qapp):
    window, engine = _installer(qapp)
    _button(window, "Install").click()
    engine.cancelled.emit()
    assert window.state == "undone"


def test_a_failed_step_keeps_its_slot_empty_and_retries_that_step(qapp):
    window, engine = _installer(qapp)
    _button(window, "Install").click()
    engine.step_progress.emit(1, 0.6)
    engine.failed.emit(FAILURE)
    assert window.state == "fail"
    texts = window.stage.copy.texts()
    assert texts[0] == "Stopped at step 2 of 4"
    assert "Couldn\u2019t copy the files." in texts
    assert "Access is denied \u00b7 0x80070005" in texts
    assert window.stage.crew_present() == 1 and window.stage.crew_bad() == 1
    assert window.stage.floor_failed() == 1
    assert _has(window, "Change location")
    _button(window, "Copy details").click()
    clip = qapp.clipboard().text()
    assert "Copying files" in clip and "0x80070005" in clip and "C:\\log.txt" in clip
    _button(window, "Try again").click()
    assert window.state == "run"
    # The retry restarts at the failed step: step 1 stays done, and the
    # missing toon comes back as its step starts again.
    assert window.stage.floor_fractions()[0] == 1.0
    assert window.stage.crew_present() == 2


def test_change_location_opens_the_customize_panel(qapp):
    window, engine = _installer(qapp)
    _button(window, "Install").click()
    engine.failed.emit(FAILURE)
    _button(window, "Change location").click()
    assert window.panel.is_open()


def test_same_version_offers_open_repair_and_uninstall(qapp):
    window, engine = _installer(qapp, installed=Installed("v0.8.0-alpha.2", 412, DIRECTORY, False))
    assert window.state == "maint"
    assert "Everyone\u2019s already here." in window.stage.copy.texts()
    assert window.stage.crew_present() == 4
    assert _has(window, "Open") and _has(window, "Uninstall instead")
    _button(window, "Repair").click()
    assert window.state == "run"


def test_over_an_older_version_it_is_an_update_without_customize(qapp):
    window, engine = _installer(qapp, installed=Installed("v0.8.0-alpha.1", 380, DIRECTORY, False))
    assert window.state == "idle"
    assert window.stage.copy.texts()[0] == "Update \u00b7 v0.8.0-alpha.1 \u2192 v0.8.0-alpha.2"
    assert _has(window, "Update") and not _has(window, "Customize")
    _button(window, "Update").click()
    assert "Updating \u00b7 step 1 of 4" in window.stage.copy.texts()
    assert engine.last_options.directory == DIRECTORY


def test_over_a_newer_version_open_is_the_safe_action(qapp):
    window, engine = _installer(qapp, installed=Installed("v0.8.1", 460, DIRECTORY, False))
    assert window.state == "newer"
    golds = [c.text() for c in window.stage.copy.controls() if getattr(c, "kind", "") == "gold"]
    assert golds == ["Open"]
    _button(window, "Install anyway").click()
    assert window.state == "run"


def test_a_running_app_is_closed_before_installing(qapp):
    window, engine = _installer(qapp, running=True)
    _button(window, "Install").click()
    assert window.state == "busy"
    assert "MultiTool is still running." in window.stage.copy.texts()
    _button(window, "Close & install").click()
    qapp.processEvents()
    assert window.state == "run" and not engine.app_running()


def test_an_app_that_will_not_close_keeps_the_question_up(qapp):
    window, engine = _installer(qapp, running=True)
    _button(window, "Install").click()
    engine.app_closed.emit(False)
    assert window.state == "busy"
    assert window.stage.copy.texts()[0] == "Couldn\u2019t close it"
    _button(window, "Cancel").click()
    assert window.state == "idle"


# ── Customize panel ────────────────────────────────────────────────────────


def test_customize_choices_reach_the_engine(qapp):
    window, engine = _installer(qapp)
    _button(window, "Customize").click()
    assert window.panel.is_open()
    window.panel._desktop.click()
    window.panel._updates.click()
    window.panel.set_directory("D:\\Games\\ToonTown MultiTool")
    _button(window, "Install").click()
    assert not window.panel.is_open()
    assert engine.last_options == InstallOptions(
        directory="D:\\Games\\ToonTown MultiTool", desktop_shortcut=False,
        start_menu=True, check_updates=False, keep_alive=False)


def test_keep_alive_needs_the_consent_block(qapp):
    from utils.rollcall.panel import KEEP_ALIVE_CONSENT
    window, _engine_ = _installer(qapp)
    panel = window.panel
    panel._keep_alive.click()
    assert panel.consent_showing() and not panel.options().keep_alive
    assert not panel._keep_alive.is_on()        # the switch has not flipped
    panel._decline.click()
    assert not panel.consent_showing() and not panel.options().keep_alive
    panel._keep_alive.click()
    panel._accept.click()
    assert panel.options().keep_alive and panel._keep_alive.is_on()
    panel._keep_alive.click()                   # off asks nothing
    assert not panel.options().keep_alive and not panel.consent_showing()
    assert KEEP_ALIVE_CONSENT == (
        "The use of Keep-Alive and other automation tools is against TTR and CC ToS, "
        "and thus is disabled by default. Enable at your own risk.")


# ── Update window ──────────────────────────────────────────────────────────


def _updater(qapp, **kwargs):
    from utils.rollcall.updater import UpdateWindow
    engine = _engine(previous_version="v0.8.0-alpha.1", **kwargs)
    window = UpdateWindow(engine)
    window.show()
    window.start()
    return window, engine


def test_the_update_window_follows_the_steps_and_cannot_be_closed(qapp):
    window, engine = _updater(qapp)
    assert window.state == "run"
    assert window.stage.copy.texts() == [
        "v0.8.0-alpha.1 \u2192 v0.8.0-alpha.2", "Closing up.", "MultiTool reopens on its own."]
    assert window.stage.copy.controls() == []
    assert window.request_close() is False
    engine.step_progress.emit(1, 0.2)
    _settle(window)
    window._refresh()
    assert window.stage.copy.headline_text() == "Installing."
    engine.step_progress.emit(2, 0.9)
    _settle(window)
    window._refresh()
    assert window.stage.copy.headline_text() == "Reopening."
    assert window.stage.crew_present() == 4      # the fourth arrives in the last quarter
    engine.finished.emit()
    assert window.state == "done"
    assert window.stage.copy.headline_text() == "Back in a second."


def test_the_toon_count_follows_overall_progress(qapp):
    window, engine = _updater(qapp)
    engine.step_progress.emit(0, 0.3)
    _settle(window)
    window._refresh()
    assert window.stage.crew_present() == 1
    engine.step_progress.emit(1, 0.0)
    _settle(window)
    window._refresh()
    assert window.stage.crew_present() == 2


def test_a_failed_update_keeps_everyone_on_stage_and_offers_retry(qapp):
    window, engine = _updater(qapp)
    engine.step_progress.emit(1, 0.5)
    engine.failed.emit(Failure(step=1, headline="The update didn\u2019t finish.",
                               body="Your previous version is back. Nothing was lost."))
    assert window.state == "fail"
    texts = window.stage.copy.texts()
    assert texts[0] == "Still on v0.8.0-alpha.1"
    assert "Your previous version is back. Nothing was lost." in texts
    assert window.stage.crew_present() == 4 and window.stage.floor_failed() == 1
    assert window.request_close() is True
    _button(window, "Retry").click()
    assert window.state == "run" and window.stage.copy.headline_text() == "Closing up."


def test_a_failed_update_that_could_not_restore_says_so(qapp):
    window, engine = _updater(qapp)
    engine.step_progress.emit(1, 0.5)
    engine.failed.emit(Failure(step=1, headline="The update didn\u2019t finish.",
                               body="Run the installer again to repair MultiTool.",
                               previous_intact=False))
    assert window.stage.copy.texts()[0] == "Update stopped"
    assert _has(window, "Try again") and _has(window, "Close")
    assert window.stage.crew_bad() == 1


# ── Uninstaller ────────────────────────────────────────────────────────────


def _uninstaller(qapp, **kwargs):
    from utils.rollcall.uninstaller import UninstallerWindow
    kwargs.setdefault("installed", Installed("v0.8.0-alpha.2", 412, DIRECTORY, False))
    engine = _engine(**kwargs)
    window = UninstallerWindow(engine)
    window.show()
    return window, engine


def test_uninstall_asks_first_with_no_gold_button(qapp):
    window, engine = _uninstaller(qapp)
    assert window.state == "idle"
    assert "Remove ToonTown MultiTool?" in window.stage.copy.texts()
    kinds = [getattr(c, "kind", "") for c in window.stage.copy.controls()]
    assert "gold" not in kinds and "red" in kinds
    assert window.stage.crew_present() == 4
    _button(window, "Keep it").click()
    assert not window.isVisible() and engine.removed_user_data is None


def test_uninstall_runs_the_stage_backwards_and_drains_the_colour(qapp):
    window, engine = _uninstaller(qapp)
    _button(window, "Uninstall").click()
    assert window.state == "run" and engine.removed_user_data is False
    assert window.stage.crew_present() == 3      # toon 4 leaves as step 1 starts
    assert window.request_close() is False
    engine.step_progress.emit(2, 0.5)
    _settle(window)
    window._refresh()
    assert window.stage.crew_present() == 1
    assert "Removing \u00b7 step 3 of 4" in window.stage.copy.texts()
    assert window.saturation() < 0.7
    engine.finished.emit()
    assert window.state == "done"
    texts = window.stage.copy.texts()
    assert "The stage is clear." in texts
    assert any("still in %USERPROFILE%\\.config\\toontown_multitool." in t for t in texts)
    assert window.stage.crew_present() == 0
    assert window.saturation() == pytest.approx(0.2)


def test_the_tick_box_removes_user_data_and_says_so(qapp):
    window, engine = _uninstaller(qapp)
    window.set_wipe(True)
    _button(window, "Uninstall").click()
    assert engine.removed_user_data is True
    engine.finished.emit()
    assert "Accounts, keysets and settings were removed too." in window.stage.copy.texts()


def test_uninstall_with_the_app_running_closes_it_first(qapp):
    window, engine = _uninstaller(qapp, running=True)
    assert window.state == "busy"
    assert "MultiTool is still running." in window.stage.copy.texts()
    _button(window, "Close & uninstall").click()
    qapp.processEvents()
    assert window.state == "run"


# ── The program ────────────────────────────────────────────────────────────


def test_self_check_passes_with_the_shipped_art_and_type(qapp, tmp_path):
    from utils.rollcall import app as rollcall_app
    shots = tmp_path / "shots"
    assert rollcall_app.self_check(str(shots)) == rollcall_app.EXIT_OK
    assert sorted(os.listdir(shots)) == [
        "self-check-install.png", "self-check-uninstall.png", "self-check-update.png"]


def test_unknown_flags_are_left_for_the_engine():
    from utils.rollcall import app as rollcall_app
    args, extra = rollcall_app._parse(
        ["--mode", "update", "--auto", "--setup", "C:\\s.exe", "--app-pid=41"])
    assert args.mode == "update" and args.auto and args.demo is None
    assert extra == ["--setup", "C:\\s.exe", "--app-pid=41"]


@pytest.mark.parametrize("scenario,expected", [("fresh", 0), ("fail", 1)])
def test_auto_drives_the_installer_to_an_exit_code(qapp, scenario, expected):
    from utils.rollcall import app as rollcall_app

    class App:
        code = None

        def exit(self, code):
            App.code = code

    engine = rollcall_app._demo_engine("install", scenario)
    engine._timer.setInterval(10_000_000)
    window = rollcall_app.build_window("install", engine)
    driver = rollcall_app.AutoDriver(App(), window, "install", wipe=False)
    _button(window, "Install").click()           # what the driver's timer would do
    if scenario == "fail":
        engine.failed.emit(FAILURE)
    else:
        engine.finished.emit()
    assert driver.exit_code == expected
