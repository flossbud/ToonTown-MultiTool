"""A/B flag for the perf pass: when TTMT_NO_EFFECTS=1, a NAMED set of visual
effects (pinwheel card colorize dim + tab-transition opacity fade) is skipped,
to isolate Cocoa offscreen-render cost. Deliberately narrow - do not extend to
popovers/scrollbars/dialogs without re-scoping the experiment."""
from __future__ import annotations

import os


def effects_disabled() -> bool:
    return os.environ.get("TTMT_NO_EFFECTS") == "1"
