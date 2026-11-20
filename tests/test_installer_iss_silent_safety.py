"""Static invariants that keep packaging/windows/installer.iss silent-safe.

The in-app updater runs the installer with /SILENT. A custom interactive
consent page that hides the wizard's Next button strands Inno's silent page
driver ("Failed to proceed to next wizard page; aborting"), so a silent update
exits 1 and the version never changes. These assertions guard the fix without
needing ISCC (which only runs on Windows): they pin the silent-mode behavior of
the consent page and the silent relaunch wiring as plain text invariants.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ISS_PATH = os.path.join(HERE, "..", "packaging", "windows", "installer.iss")


def _read_iss() -> str:
    with open(ISS_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def _block(text: str, header_regex: str) -> str:
    """Return the body of the [Code] routine whose header matches header_regex,
    up to the next top-level `function`/`procedure` declaration."""
    m = re.search(header_regex, text)
    assert m, f"routine not found: {header_regex}"
    start = m.start()
    nxt = re.search(r"\n(?:function|procedure)\s", text[m.end():])
    end = m.end() + nxt.start() if nxt else len(text)
    return text[start:end]


def test_should_skip_page_skips_consent_when_silent():
    # A silent install cannot collect interactive consent, so the consent page
    # must be skipped under WizardSilent regardless of the keepalive task state
    # (UsePreviousTasks can restore keepalive as selected on a silent upgrade).
    body = _block(_read_iss(), r"function ShouldSkipPage\(")
    assert "WizardSilent" in body, "ShouldSkipPage must skip the consent page in silent mode"


def test_cur_page_changed_does_not_hide_next_when_silent():
    # Defense in depth: even if the consent page were ever reached silently,
    # hiding Next would deadlock the silent driver. The hide branch must be
    # guarded by WizardSilent.
    body = _block(_read_iss(), r"procedure CurPageChanged\(")
    assert "WizardSilent" in body, "CurPageChanged must not hide Next in silent mode"


def test_silent_relaunch_run_entry_present():
    text = _read_iss()
    assert "Check: WantSilentRelaunch" in text, "missing silent-relaunch [Run] entry"
    body = _block(text, r"function WantSilentRelaunch\(")
    assert "WizardSilent" in body
    assert "RELAUNCH" in body, "relaunch must be gated on the updater's /RELAUNCH param"


def test_restart_applications_disabled():
    # Relaunch is owned explicitly by the /RELAUNCH [Run] entry. Inno's Restart
    # Manager must not also relaunch the app it closed, or the two race and can
    # double-launch.
    text = _read_iss()
    assert re.search(r"^\s*RestartApplications\s*=\s*no\s*$", text, re.MULTILINE), \
        "RestartApplications must be no to avoid double-launch with /RELAUNCH"


# ── Roll Call (the install / update / uninstall windows) ──────────────────

def _section(text: str, name: str) -> str:
    m = re.search(r"^\[" + re.escape(name) + r"\]\s*$(.*?)(?=^\[\w+\]\s*$)", text,
                  re.MULTILINE | re.DOTALL)
    assert m, f"[{name}] section not found"
    return m.group(1)


def test_no_install_mode_dialog_on_a_double_click():
    text = _read_iss()
    assert re.search(r"^\s*PrivilegesRequiredOverridesAllowed\s*=\s*commandline\s*$", text,
                     re.MULTILINE), "the window decides the mode; the dialog must be gone"
    # Without the dialog Inno ignores UsePreviousPrivileges: Setup re-runs a
    # run that chose no mode with /ALLUSERS over an all-users install.
    body = _block(text, r"function RcNeedsAllUsersRespawn\b")
    assert "HKLM" in body and "ALLUSERS" in body and "CURRENTUSER" in body
    init = _block(text, r"function InitializeSetup\(")
    assert init.count("RcNeedsAllUsersRespawn") == 2, "silent runs and the wizard both re-run"


def test_the_windows_are_unpacked_first_and_also_installed_for_the_uninstaller():
    files = _section(_read_iss(), "Files")
    entries = [line for line in files.splitlines() if line.startswith("Source:")]
    assert "dontcopy" in entries[0] and "{tmp}\\rollcall" in entries[0]
    assert "{code:RcFileDestDir}\\rollcall" in entries[1]


def test_every_installed_file_goes_through_the_stop_hook():
    # A Check cannot stop an install (Inno skips the file and carries on); an
    # exception while expanding DestDir aborts it and rolls it back.
    files = _section(_read_iss(), "Files")
    for line in files.splitlines():
        if line.startswith("Source:") and "dontcopy" not in line:
            assert "DestDir: \"{code:RcFileDestDir}" in line, line
            assert "Check:" not in line, line


def test_only_the_dest_dir_hook_raises():
    text = _read_iss()
    for routine in ("function RcBeforeFiles", "function RcShortcutsCheckpoint",
                    "procedure RcFileStarting", "procedure CurInstallProgressChanged"):
        assert "RaiseException" not in _block(text, re.escape(routine) + r"\b"), routine
    assert "RcCheckpoint(" in _block(text, r"function RcFileDestDir\(")


def test_the_window_run_skips_the_wizards_config_step():
    run = _section(_read_iss(), "Run")
    apply_entry = run.split("Filename:")[1]
    assert "--apply-installer-config" in apply_entry and "Check: RcNotWindowRun" in apply_entry


def test_a_failed_window_run_puts_the_previous_version_back():
    text = _read_iss()
    assert "RcRestoreBackup" in _block(text, r"procedure DeinitializeSetup\(")
    assert "RcDropBackup" in _block(text, r"procedure CurStepChanged\(")
