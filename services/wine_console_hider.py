"""Hides the Wine console window that Corporate Clash's TTCCLauncher spawns
via AllocConsole(). The console shows CC's stdout (font loads, downloader
status, ConfigVariable changes) and is useful for debugging but visual
noise in the common-case successful launch.

After CCLauncher emits `game_launched`, this module polls top-level X11
windows every WATCH_INTERVAL_MS for up to WATCH_DURATION_MS, unmapping any
window whose title (case- and slash-normalized) ends with the CC exe
basename. The console process remains alive (CC's stdout keeps flowing);
only its X11 surface vanishes.

Single-shot per launch. Gated by the CC_HIDE_LAUNCH_CONSOLE setting
(default True). See docs/superpowers/specs/2026-05-21-hide-cc-launch-
console-design.md for the full design rationale.
"""

from __future__ import annotations

# Suffix the title must end with (after lowercasing and replacing forward
# slashes with backslashes). The leading backslash anchors against the
# Windows path separator so a token like "foo-corporateclash.exe.txt"
# never matches.
_CONSOLE_TITLE_SUFFIX = r"\corporateclash.exe"

# Polling cadence in milliseconds. 200ms is short enough that the user
# rarely perceives the console flash; long enough that 75 ticks over
# WATCH_DURATION_MS is trivial CPU.
WATCH_INTERVAL_MS = 200

# Total time to keep polling per launch. 15s covers CC's cold-start
# (network-bound) without leaving the timer running indefinitely.
WATCH_DURATION_MS = 15_000


def _title_matches(title: str) -> bool:
    """True if a window title looks like the Wine console for CC's exe.

    Normalization: lowercase, then replace forward slashes with backslashes
    so `C:/users/.../CorporateClash.exe` is treated the same as
    `C:\\users\\...\\CorporateClash.exe`. Match anchored on the leading
    backslash to prevent false positives on `*corporateclash.exe.txt` or
    `foo-corporateclash.exe` substrings.
    """
    if not title:
        return False
    normalized = title.lower().replace("/", "\\")
    return normalized.endswith(_CONSOLE_TITLE_SUFFIX)
