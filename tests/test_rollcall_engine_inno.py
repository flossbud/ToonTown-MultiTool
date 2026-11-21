"""The real Roll Call engine over a fake PC.

Setup is played by the test: the engine starts a "process" through the fake
machine, the test appends the progress lines Setup would write (the format
proven against the real installer under Wine; see
utils/rollcall/protocol.py) and sets its exit code, and the engine's clock
is ticked by hand.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils.rollcall import engine_inno as E                          # noqa: E402
from utils.rollcall import protocol as P                             # noqa: E402
from utils.rollcall.engine import INDETERMINATE, Flavor, InstallOptions  # noqa: E402

FLAVOR = Flavor(app_name="ToonTown MultiTool", version="v0.8.0-alpha.2", build=412,
                app_id="{D3B6B7EE-20F5-4D45-AD15-F772F3B1DCAC}",
                config_dir_name="toontown_multitool", channel="stable",
                payload_bytes=221_000_000)


class FakeProc:
    def __init__(self, exe, args, cwd=""):
        self.exe = exe
        self.args = list(args)
        self.cwd = cwd
        self.code = None

    def poll(self):
        return self.code

    def arg(self, prefix):
        for a in self.args:
            if a.upper().startswith(prefix.upper()):
                return a[len(prefix):]
        return None

    def say(self, *lines):
        with open(self.arg("/RCPROGRESS="), "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\r\n")


class FakeMachine(E.Machine):
    def __init__(self, tmp_path, record=None, admin_dirs=()):
        self.tmp = tmp_path
        self.record = record
        self.admin_dirs = set(admin_dirs)
        self.started = []
        self.launched = []
        self.running = set()          # pids of the app
        self.alive = set()            # other pids
        self.windows = False
        self.quit_answers = False
        self.rm_closes = False
        self.removed = []
        self.files_left = 0
        self.settings = {}
        self.deleted_keys = []
        os.environ["TTMT_CONFIG_DIR"] = str(tmp_path / "config")

    def read_install(self, app_id, app_name):
        return self.record

    def read_settings(self, config_dir):
        return dict(self.settings)

    def user_programs_dir(self):
        return "C:\\Users\\P\\AppData\\Local\\Programs"

    def temp_dir(self):
        return str(self.tmp)

    def needs_admin(self, directory):
        return directory in self.admin_dirs

    def count_files(self, directory):
        return self.files_left

    def app_pids(self, exe_path):
        return sorted(self.running)

    def pid_alive(self, pid):
        return pid in self.alive or pid in self.running

    def has_visible_window(self, pids):
        return self.windows

    def ask_quit(self, server_name):
        if self.quit_answers:
            self.running.clear()
        return self.quit_answers

    def restart_manager_close(self, paths):
        if self.rm_closes:
            self.running.clear()
        return self.rm_closes

    def start(self, exe, args, cwd=""):
        proc = FakeProc(exe, args, cwd)
        self.started.append(proc)
        return proc

    def launch_app(self, exe, args=()):
        self.launched.append(exe)
        return True

    def shortcut_paths(self, app_name, all_users):
        return [f"desk\\{app_name}.lnk", f"group\\{app_name}.lnk", "group"]

    def remove_file(self, path):
        self.removed.append(path)

    def remove_dir_if_empty(self, path):
        self.removed.append(path)

    def delete_empty_app_key(self, app_name, all_users):
        self.deleted_keys.append((app_name, all_users))


RECORD = E.InstallRecord(version="v0.8.0-alpha.1", build=380,
                         directory="C:\\Users\\P\\AppData\\Local\\Programs\\ToonTown MultiTool",
                         all_users=False,
                         uninstaller="C:\\Users\\P\\AppData\\Local\\Programs\\ToonTown MultiTool\\unins000.exe",
                         selected_tasks=("checkupdates", "desktopicon"),
                         deselected_tasks=("keepalive", "launchapp"))


@pytest.fixture
def make(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(E, "STEP_DWELL_S", 0.0)
    built = []

    def factory(mode="install", record=None, **kwargs):
        machine = kwargs.pop("machine", None) or FakeMachine(tmp_path, record=record)
        engine = E.InnoEngine(machine=machine, mode=mode, flavor=FLAVOR,
                              setup_path="C:\\Temp\\Setup.exe",
                              log_path=str(tmp_path / "rollcall.log"), **kwargs)
        engine._timer.stop()
        events = []
        engine.step_progress.connect(lambda s, f: events.append(("step", s, f)))
        engine.finished.connect(lambda: events.append(("finished",)))
        engine.failed.connect(lambda failure: events.append(("failed", failure)))
        engine.cancelled.connect(lambda: events.append(("cancelled",)))
        engine.app_closed.connect(lambda ok: events.append(("app_closed", ok)))
        built.append(engine)
        return engine, machine, events

    yield factory
    os.environ.pop("TTMT_CONFIG_DIR", None)
    for engine in built:
        engine._timer.stop()


def tick(engine, qapp, n=1):
    for _ in range(n):
        engine._tick()
        qapp.processEvents()


def last(events, kind):
    found = [e for e in events if e[0] == kind]
    return found[-1] if found else None


def steps(events):
    return [(e[1], e[2]) for e in events if e[0] == "step"]


# ── Protocol ───────────────────────────────────────────────────────────────

def test_arguments_are_quoted_for_inno():
    assert P.quote_arg("/VERYSILENT") == "/VERYSILENT"
    assert P.quote_arg("/DIR=C:\\Program Files\\X") == '"/DIR=C:\\Program Files\\X"'
    # A backslash before the closing quote would escape it for the C runtime.
    assert P.quote_arg("/DIR=C:\\Program Files\\X\\") == '"/DIR=C:\\Program Files\\X"'
    assert P.quote_arg("") == '""'
    with pytest.raises(ValueError):
        P.quote_arg('/DIR=C:\\a"b')
    assert P.command_line("C:\\x y\\Setup.exe", ["/SILENT", "/TASKS=a,b"]) == \
        '"C:\\x y\\Setup.exe" /SILENT /TASKS=a,b'


def test_the_temp_copy_cleaner_retries_then_logs_what_became_of_the_folder():
    # This exact line ran under Wine's cmd (minus the cmd /c wrapper): it
    # removed a plain folder, kept trying while a file in it was held open
    # and removed it once the file was let go, and logged both outcomes.
    line = P.temp_copy_cleaner("C:\\T\\R\\copy-3\\", "C:\\T\\R\\rc.log")
    assert line == (
        'cmd.exe /d /c "ping -n 3 127.0.0.1 >nul & '
        '(for /l %i in (1,1,60) do @if exist "C:\\T\\R\\copy-3\\" '
        '(rmdir /s /q "C:\\T\\R\\copy-3" 2>nul & '
        'if exist "C:\\T\\R\\copy-3\\" ping -n 2 127.0.0.1 >nul)) & '
        '(if exist "C:\\T\\R\\copy-3\\" '
        '(echo [RollCall] temp copy still there after 60 tries>>"C:\\T\\R\\rc.log") '
        'else (echo [RollCall] temp copy removed>>"C:\\T\\R\\rc.log"))"')
    spaced = P.temp_copy_cleaner("C:\\Users\\A B (x)\\Temp\\ttmt-rollcall-uninstall-9",
                                 "C:\\Users\\A B (x)\\Temp\\rc.log")
    assert 'rmdir /s /q "C:\\Users\\A B (x)\\Temp\\ttmt-rollcall-uninstall-9"' in spaced
    assert f'{P.TEMP_COPY_REMOVED}>>"C:\\Users\\A B (x)\\Temp\\rc.log"' in spaced


def test_a_path_cmd_would_mangle_gets_no_cleaner_or_no_log_line():
    assert P.temp_copy_cleaner("C:\\T\\100%\\copy", "C:\\T\\rc.log") == ""
    assert P.temp_copy_cleaner("") == ""
    line = P.temp_copy_cleaner("C:\\T\\copy", "C:\\T\\%x%\\rc.log")
    assert line and "rmdir" in line and ">>" not in line


def test_the_line_reader_returns_only_complete_new_lines(tmp_path):
    path = tmp_path / "p.txt"
    reader = P.LineReader(str(path))
    assert reader.read() == []
    path.write_bytes(b"hello 1 v1 2 no\r\nstep 0\r\nprog")
    assert reader.read() == ["hello 1 v1 2 no", "step 0"]
    with open(path, "ab") as fh:
        fh.write(b"ress 120\r\n")
    assert reader.read() == ["progress 120"]


def test_run_state_reads_every_line_setup_writes():
    s = P.RunState()
    for line in ["hello 288 v9.9.9-test 999 yes", "step 0", "backup ok C:\\T\\app.previous-version",
                 "step 1", "progress 350", "paused", "resumed", "error test-failure",
                 "restored C:\\T\\app", "end"]:
        s.apply(line)
    assert s.hello and s.admin_mode and s.step == 1 and s.permille == 350
    assert s.backup == "ok" and s.backup_dir.endswith("previous-version")
    assert s.restored and s.ended and not s.paused and not s.installed
    assert s.has_error("test-failure") and not s.has_error("backup")


def test_the_quit_request_reaches_the_name_the_app_listens_on(tmp_path):
    from utils import instance_guard
    cfg = str(tmp_path)
    assert E.server_name(cfg, "player") == instance_guard.server_name(
        cfg, "player", platform="win32")


# ── Setup's log ────────────────────────────────────────────────────────────

INNO_LOG_ACCESS_DENIED = """\
2026-11-20 17:11:17.600   -- File entry --
2026-11-20 17:11:17.601   Dest filename: C:\\T\\app\\_internal\\Qt6Core.dll
2026-11-20 17:11:17.657   Defaulting to Abort for suppressed message box (Abort/Retry/Ignore):
                          C:\\T\\app\\_internal\\Qt6Core.dll

                          An error occurred while trying to create a file in the destination directory:
                          CreateFile failed; code 5.
                          Access is denied.
2026-11-20 17:11:17.657   User canceled the installation process.
2026-11-20 17:11:17.657   Rolling back changes.
2026-11-20 17:11:17.700   Exception message:
2026-11-20 17:11:17.700   Defaulting to OK for suppressed message box (OK):
                          Something unrelated.
"""

INNO_LOG_TEST_FAILURE = """\
2026-11-20 17:11:17.657   Defaulting to Abort for suppressed message box (Abort/Retry/Ignore):
                          Simulated failure (/RCTESTFAIL) for a test run.
2026-11-20 17:11:17.657   User canceled the installation process.
"""


def test_the_error_that_stopped_setup_is_read_from_its_log():
    assert E.read_setup_error(INNO_LOG_ACCESS_DENIED) == (5, "Access is denied")
    assert E.read_setup_error(INNO_LOG_TEST_FAILURE) == (
        0, "Simulated failure (/RCTESTFAIL) for a test run")
    assert E.read_setup_error("") == (0, "")


def test_failure_copy_follows_the_pattern():
    s = P.RunState()
    for line in ["hello 1 v 1 no", "step 0", "backup none", "step 1"]:
        s.apply(line)
    f = E.install_failure(1, s, 5, "Access is denied", upgrade=False, log_path="L",
                          short_name="MultiTool")
    assert f.headline == "Couldn\u2019t copy the files."
    assert f.body == ("Windows blocked writing to the install folder. "
                      "Anything already copied was removed.")
    assert f.detail == "Access is denied \u00b7 0x80070005"
    assert f.step == 1 and f.log_path == "L"


@pytest.mark.parametrize("lines, intact, tail", [
    (["step 0", "backup ok D.previous-version", "step 1", "restored D"], True,
     "Your previous version is back. Nothing was lost."),
    (["step 0", "backup ok D.previous-version", "step 1", "error restore D.previous-version"],
     False, "Run the installer again to repair MultiTool."),
    (["step 0", "error backup in-use D"], True, "Nothing was changed."),
    (["step 0", "backup ok D.previous-version", "step 1"], False,
     "Run the installer again to repair MultiTool."),   # Setup died mid-copy
])
def test_an_upgrade_failure_says_only_what_is_true(lines, intact, tail):
    s = P.RunState()
    for line in ["hello 1 v 1 no"] + lines:
        s.apply(line)
    f = E.install_failure(s.step, s, 0, "", upgrade=True, log_path="", short_name="MultiTool")
    assert f.previous_intact is intact
    assert f.body.endswith(tail)


# ── Install ────────────────────────────────────────────────────────────────

def test_a_fresh_install_runs_setup_silently_then_saves_the_choices(make, qapp):
    engine, machine, events = make()
    options = engine.default_options()
    assert options.directory == "C:\\Users\\P\\AppData\\Local\\Programs\\ToonTown MultiTool"
    assert options.desktop_shortcut and options.start_menu and options.check_updates
    assert not options.keep_alive
    engine.install(options)
    setup = machine.started[-1]
    assert setup.exe == "C:\\Temp\\Setup.exe"
    assert setup.args[:4] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER"]
    assert setup.arg("/DIR=") == options.directory
    assert setup.arg("/TASKS=") == "startmenuicon,desktopicon,checkupdates"
    assert setup.arg("/RCPROGRESS=") and setup.arg("/LOG=")
    assert steps(events)[0] == (0, INDETERMINATE)
    assert engine.can_cancel()

    setup.say("hello 9 v0.8.0-alpha.2 412 no", "step 0", "backup none", "step 1",
              "progress 500")
    tick(engine, qapp)
    assert steps(events)[-1] == (1, 0.5)
    assert engine.can_cancel()
    setup.say("step 2")
    tick(engine, qapp)
    assert steps(events)[-1] == (2, INDETERMINATE)
    assert not engine.can_cancel()
    setup.say("installed", "end")
    setup.code = 0
    tick(engine, qapp)
    config = machine.started[-1]
    assert config.exe.endswith("ToonTown MultiTool\\ToonTownMultiTool.exe")
    assert config.args == ["--apply-installer-config", "--check-updates=1", "--keep-alive=0"]
    assert steps(events)[-1] == (3, INDETERMINATE)
    config.code = 0
    tick(engine, qapp)
    assert last(events, "finished")


def test_a_folder_that_needs_administrator_rights_installs_for_all_users(make, qapp, tmp_path):
    machine = FakeMachine(tmp_path, admin_dirs={"C:\\Program Files\\ToonTown MultiTool"})
    engine, _, _ = make(machine=machine)
    engine.install(InstallOptions(directory="C:\\Program Files\\ToonTown MultiTool"))
    assert "/ALLUSERS" in machine.started[-1].args


def test_an_upgrade_keeps_the_existing_folder_mode_and_choices(make, qapp, tmp_path):
    import dataclasses
    record = dataclasses.replace(RECORD, all_users=True)
    engine, machine, events = make(record=record)
    options = engine.default_options()
    assert options.directory == record.directory
    assert options.desktop_shortcut
    assert options.start_menu        # older installs had no switch: the entry was always there
    engine.install(options)
    setup = machine.started[-1]
    assert "/ALLUSERS" in setup.args and setup.arg("/DIR=") == record.directory
    assert not engine.can_cancel()   # an upgrade cannot be stopped


def test_keep_alive_consent_already_given_is_never_written_again(make, qapp):
    engine, machine, events = make()
    machine.settings = {"keep_alive_enabled": True, "keep_alive_consent_acknowledged": True,
                        "check_for_updates_at_startup": False}
    options = engine.default_options()
    assert options.keep_alive and not options.check_updates
    engine.install(options)
    setup = machine.started[-1]
    setup.say("hello 1 v 1 no", "step 0", "step 1", "step 2", "installed")
    setup.code = 0
    tick(engine, qapp)
    assert machine.started[-1].args == ["--apply-installer-config", "--check-updates=0",
                                        "--keep-alive=0"]


def test_stopping_mid_copy_ends_cancelled(make, qapp):
    engine, machine, events = make()
    engine.install(engine.default_options())
    setup = machine.started[-1]
    setup.say("hello 1 v 1 no", "step 0", "backup none", "step 1", "progress 300")
    tick(engine, qapp)
    engine.set_paused(True)
    progress = setup.arg("/RCPROGRESS=")
    assert os.path.exists(progress + ".pause")
    engine.cancel()
    assert os.path.exists(progress + ".cancel") and not os.path.exists(progress + ".pause")
    assert not engine.can_cancel()
    setup.say("cancelled copying", "end")
    setup.code = 5
    tick(engine, qapp)
    assert last(events, "cancelled") and not last(events, "failed")
    assert not os.path.exists(progress)      # the run's own files are gone too


def test_a_declined_administrator_prompt_ends_cancelled(make, qapp):
    engine, machine, events = make()
    engine.install(engine.default_options())
    machine.started[-1].code = 2            # Inno: elevation declined, never said hello
    tick(engine, qapp)
    assert last(events, "cancelled")


def test_a_stop_that_arrives_after_setup_finished_removes_the_fresh_install(make, qapp):
    engine, machine, events = make()
    engine.install(engine.default_options())
    setup = machine.started[-1]
    setup.say("hello 1 v 1 no", "step 0", "step 1", "progress 990")
    tick(engine, qapp)
    engine.cancel()
    setup.say("step 2", "installed", "end")
    setup.code = 0
    machine.record = RECORD
    tick(engine, qapp)
    undo = machine.started[-1]
    assert undo.exe == RECORD.uninstaller and "/VERYSILENT" in undo.args
    undo.code = 0
    tick(engine, qapp)
    assert last(events, "cancelled")


def test_a_copy_failure_reports_the_cause_and_the_state(make, qapp):
    engine, machine, events = make()
    engine.install(engine.default_options())
    setup = machine.started[-1]
    setup.say("hello 1 v 1 no", "step 0", "backup none", "step 1", "progress 400", "end")
    with open(setup.arg("/LOG="), "w", encoding="utf-8") as fh:
        fh.write(INNO_LOG_ACCESS_DENIED)
    setup.code = 5
    tick(engine, qapp)
    failure = last(events, "failed")[1]
    assert failure.step == 1
    assert failure.headline == "Couldn\u2019t copy the files."
    assert "Anything already copied was removed." in failure.body
    assert failure.detail == "Access is denied \u00b7 0x80070005"
    assert failure.log_path == setup.arg("/LOG=")
    assert os.path.exists(failure.log_path)   # kept for Copy details


def test_try_again_after_a_failed_save_only_saves_again(make, qapp):
    engine, machine, events = make()
    options = engine.default_options()
    engine.install(options)
    setup = machine.started[-1]
    setup.say("hello 1 v 1 no", "step 0", "step 1", "step 2", "installed")
    setup.code = 0
    tick(engine, qapp)
    machine.started[-1].code = 1
    tick(engine, qapp)
    failure = last(events, "failed")[1]
    assert failure.step == 3 and failure.headline == "Couldn\u2019t save your choices."
    count = len(machine.started)
    engine.install(options)
    assert len(machine.started) == count + 1
    assert machine.started[-1].args[0] == "--apply-installer-config"
    machine.started[-1].code = 0
    tick(engine, qapp)
    assert last(events, "finished")


def test_try_again_after_a_copy_failure_keeps_earlier_steps_done(make, qapp):
    engine, machine, events = make()
    options = engine.default_options()
    engine.install(options)
    setup = machine.started[-1]
    setup.say("hello 1 v 1 no", "step 0", "step 1", "progress 200", "end")
    setup.code = 5
    tick(engine, qapp)
    assert last(events, "failed")[1].step == 1
    events.clear()
    engine.install(options)
    retry = machine.started[-1]
    assert retry.exe == "C:\\Temp\\Setup.exe"
    retry.say("hello 1 v 1 no", "step 0")
    tick(engine, qapp)
    assert all(step >= 1 for step, _ in steps(events))


# ── Closing the app ────────────────────────────────────────────────────────

def test_a_running_app_that_takes_the_quit_request_closes(make, qapp, tmp_path):
    engine, machine, events = make(record=RECORD)
    machine.running = {501}
    machine.quit_answers = True
    assert engine.app_running()
    engine.close_app()
    tick(engine, qapp, 3)
    assert last(events, "app_closed") == ("app_closed", True)


def test_an_older_app_is_closed_through_the_restart_manager(make, qapp):
    engine, machine, events = make(record=RECORD)
    machine.running = {501}
    machine.rm_closes = True
    engine.close_app()
    tick(engine, qapp, 3)
    import time
    for _ in range(50):
        tick(engine, qapp)
        if last(events, "app_closed"):
            break
        time.sleep(0.02)
    assert last(events, "app_closed") == ("app_closed", True)


# ── Update ─────────────────────────────────────────────────────────────────

def test_an_update_waits_for_the_app_installs_and_reopens(make, qapp, tmp_path):
    ready = tmp_path / "ready.txt"
    engine, machine, events = make(mode="update", record=RECORD, ready_file=str(ready),
                                   app_pid=4242, from_version="v0.8.0-alpha.1")
    machine.alive = {4242}
    assert engine.previous_version() == "v0.8.0-alpha.1"
    engine.update()
    assert P.read_ready(str(ready)) == P.READY_UP     # the app may quit now
    tick(engine, qapp)
    assert not machine.started                       # still waiting for it
    machine.alive.clear()
    tick(engine, qapp)
    setup = machine.started[-1]
    assert "/CURRENTUSER" in setup.args and setup.arg("/DIR=") == RECORD.directory
    assert not setup.arg("/TASKS=")                  # the existing choices stay
    setup.say("hello 1 v 1 no", "step 0", "backup ok X", "step 1", "progress 500")
    tick(engine, qapp, 2)
    assert any(s == 1 and 0.4 < f < 0.6 for s, f in steps(events))
    setup.say("step 2", "installed", "end")
    setup.code = 0
    tick(engine, qapp)
    assert machine.launched == [RECORD.directory + "\\ToonTownMultiTool.exe"]
    machine.running = {777}
    tick(engine, qapp)
    assert not last(events, "finished")              # running, window not up yet
    machine.windows = True
    tick(engine, qapp)
    assert last(events, "finished")


def test_a_failed_update_with_the_old_version_back_says_so(make, qapp, tmp_path):
    engine, machine, events = make(mode="update", record=RECORD,
                                   ready_file=str(tmp_path / "r.txt"), app_pid=1)
    engine.update()
    tick(engine, qapp)
    setup = machine.started[-1]
    setup.say("hello 1 v 1 no", "step 0", "backup ok X", "step 1", "error test-failure",
              "restored X", "end")
    setup.code = 5
    tick(engine, qapp)
    failure = last(events, "failed")[1]
    assert failure.previous_intact
    assert failure.headline == "The update didn\u2019t finish."
    assert failure.body == "Your previous version is back. Nothing was lost."


def test_a_failed_update_that_could_not_restore_asks_for_a_repair(make, qapp, tmp_path):
    engine, machine, events = make(mode="update", record=RECORD,
                                   ready_file=str(tmp_path / "r.txt"), app_pid=1)
    engine.update()
    tick(engine, qapp)
    setup = machine.started[-1]
    setup.say("hello 1 v 1 no", "step 0", "backup ok X", "step 1", "error restore X", "end")
    setup.code = 5
    tick(engine, qapp)
    failure = last(events, "failed")[1]
    assert not failure.previous_intact
    assert failure.body == "Run the installer again to repair MultiTool."


# ── Uninstall ──────────────────────────────────────────────────────────────

def test_an_uninstall_runs_the_uninstaller_then_sweeps_and_wipes(make, qapp, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.json").write_text("{}")
    engine, machine, events = make(mode="uninstall", record=RECORD,
                                   uninstaller=RECORD.uninstaller, app_dir=RECORD.directory)
    machine.files_left = 200
    engine.uninstall(True)
    tick(engine, qapp)
    proc = machine.started[-1]
    assert proc.exe == RECORD.uninstaller
    assert proc.args[:3] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    proc.say("hello 1 v 1 uninstall", "removing")
    machine.files_left = 50
    tick(engine, qapp)
    assert steps(events)[-1] == (1, 0.75)
    proc.say("removed", "end")
    proc.code = 0
    tick(engine, qapp, 4)
    assert last(events, "finished")
    assert "group" in machine.removed
    assert machine.deleted_keys == [("ToonTown MultiTool", False)]
    assert not config.exists()
    assert engine.config_dir_display() == str(config)    # TTMT_CONFIG_DIR is set here


def test_the_user_data_stays_unless_asked(make, qapp, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    engine, machine, events = make(mode="uninstall", record=RECORD, app_dir=RECORD.directory)
    engine.uninstall(False)
    tick(engine, qapp)
    machine.started[-1].code = 0
    tick(engine, qapp, 4)
    assert last(events, "finished") and config.exists()


def test_the_config_dir_is_shown_as_the_app_finds_it(make, monkeypatch):
    engine, _, _ = make()
    monkeypatch.delenv("TTMT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert engine.config_dir_display() == "%USERPROFILE%\\.config\\toontown_multitool"


# ── From Setup's command line ──────────────────────────────────────────────

def test_build_engine_reads_the_flags_setup_passes(qapp, tmp_path):
    # Exactly what installer.iss passed under Wine (tests/handoff run).
    argv = ["--setup", "Z:\\b\\Output\\setup-test.exe", "--log", str(tmp_path / "rc.log"),
            "--ready-file", str(tmp_path / "ready.txt"), "--app-name", "ToonTown MultiTool",
            "--app-version", "v9.9.9-test", "--build", "999",
            "--app-id", "{D3B6B7EE-20F5-4D45-AD15-F772F3B1DCAC}",
            "--config-dir-name", "toontown_multitool", "--channel", "stable",
            "--payload-bytes", "0", "--app-pid", "4242", "--from-version", "v0.1.0"]
    engine = E.build_engine("update", argv, machine=FakeMachine(tmp_path))
    flavor = engine.flavor()
    assert (flavor.app_name, flavor.version, flavor.build, flavor.channel) == (
        "ToonTown MultiTool", "v9.9.9-test", 999, "stable")
    assert flavor.app_id == "{D3B6B7EE-20F5-4D45-AD15-F772F3B1DCAC}"
    assert engine.previous_version() == "v0.1.0"
    assert "engine inno update" in (tmp_path / "rc.log").read_text()
    os.environ.pop("TTMT_CONFIG_DIR", None)


def test_the_install_window_marks_itself_up_once_the_loop_runs(qapp, tmp_path):
    ready = tmp_path / "ready.txt"
    engine = E.build_engine("install", ["--ready-file", str(ready)],
                            machine=FakeMachine(tmp_path))
    assert not ready.exists()
    qapp.processEvents()
    assert P.read_ready(str(ready)) == P.READY_UP
    engine._timer.stop()
    os.environ.pop("TTMT_CONFIG_DIR", None)


def test_the_ci_cancel_hook_stops_a_fresh_install_mid_copy(make, qapp):
    engine, machine, events = make(test_cancel_at=300)
    engine.install(engine.default_options())
    setup = machine.started[-1]
    setup.say("hello 1 v 1 no", "step 0", "step 1", "progress 100")
    tick(engine, qapp)
    assert not os.path.exists(setup.arg("/RCPROGRESS=") + ".cancel")
    setup.say("progress 320")
    tick(engine, qapp)
    assert os.path.exists(setup.arg("/RCPROGRESS=") + ".cancel")


def test_the_sweep_after_an_uninstall_uses_the_mode_read_before_it(make, qapp):
    import dataclasses
    record = dataclasses.replace(RECORD, all_users=True)
    engine, machine, events = make(mode="uninstall", record=record, app_dir=record.directory)
    seen = []
    machine.shortcut_paths = lambda name, all_users: seen.append(all_users) or []
    engine.uninstall(False)
    tick(engine, qapp)
    machine.record = None                  # the uninstaller removed it
    machine.started[-1].code = 0
    tick(engine, qapp, 4)
    assert last(events, "finished")
    assert seen == [True]
    assert machine.deleted_keys == [("ToonTown MultiTool", True)]


def test_the_uninstall_window_leaves_a_cleaner_for_its_temp_copy(make, qapp, tmp_path):
    from PySide6.QtCore import SIGNAL

    class Cleaning(FakeMachine):
        asked = None

        def delete_self_later(self, directory, log_path=""):
            self.asked = (directory, log_path)
            return "cleaner started (pid 7)"

    machine = Cleaning(tmp_path, record=RECORD)
    before = qapp.receivers(SIGNAL("aboutToQuit()"))
    engine, _, _ = make(mode="uninstall", record=RECORD, machine=machine,
                        uninstaller=RECORD.uninstaller, app_dir=RECORD.directory,
                        self_dir="C:\\T\\ttmt-rollcall-uninstall-7")
    assert qapp.receivers(SIGNAL("aboutToQuit()")) == before + 1
    engine._delete_temp_copy()             # what aboutToQuit runs
    assert machine.asked == ("C:\\T\\ttmt-rollcall-uninstall-7", str(tmp_path / "rollcall.log"))
    assert "temp copy: cleaner started (pid 7)" in (tmp_path / "rollcall.log").read_text()
