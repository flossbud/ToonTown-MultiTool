"""Windows-only elevated relaunch helper. A higher-integrity game blocks our
synthetic input (UIPI); relaunching elevated raises our integrity to match.
os.execv / ShellExecute without the 'runas' verb keep the current integrity, so
elevation specifically requires ShellExecuteEx with verb='runas'."""
from __future__ import annotations

import os
import sys

ELEVATION_RESTART_FLAG = "--elevation-restart=uipi"

# One-shot/internal modes that must NOT be forwarded into the relaunched GUI.
_ONE_SHOT_FLAGS = {"--self-check", "--self-check-keyring", "--apply-installer-config"}
# Flags that consume a following value (so we drop the value too).
_ONE_SHOT_WITH_VALUE = {"--apply-installer-config"}


def build_relaunch_params(argv) -> list:
    """Filter one-shot modes out of argv (argv = sys.argv[1:]) and append the
    elevation-restart flag exactly once. Handles both space-separated
    (`--apply-installer-config PATH`) and equals (`--flag=value`) forms. A
    space-separated value is dropped ONLY when the following token looks like a
    value (not another `-` flag), so an immediately-following unrelated flag is
    never swallowed."""
    out = []
    i, n = 0, len(argv)
    while i < n:
        tok = argv[i]
        base = tok.split("=", 1)[0]
        if base in _ONE_SHOT_FLAGS:
            if (base in _ONE_SHOT_WITH_VALUE and "=" not in tok
                    and i + 1 < n and not argv[i + 1].startswith("-")):
                i += 1          # also drop the space-separated value token
            i += 1
            continue
        out.append(tok)
        i += 1
    if ELEVATION_RESTART_FLAG not in out:
        out.append(ELEVATION_RESTART_FLAG)
    return out
