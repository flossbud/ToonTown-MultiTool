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
