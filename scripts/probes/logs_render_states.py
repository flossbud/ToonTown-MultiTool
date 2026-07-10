#!/usr/bin/env python
"""Render the four bundle screenshot states of LogsCard to PNGs for
side-by-side visual review against
Redesign/design_handoff_logs_redesign/screenshots/. Not a pixel diff
(browser vs Qt font rasterization differs); a human judges parity.
Safe: touches no config, no network — pure widget rendering."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from datetime import datetime, timedelta

from PySide6.QtWidgets import QApplication

SEEDS = [  # the bundle's seed traffic, verbatim tags/voice
    ("MultiTool v0.7.0-alpha.4 (build 1898, 52ef8b0) starting", None),
    ("Platform: Linux (Flatpak) · Qt 6.7.2 · Python 3.12.4", None),
    ("[Credentials] KWallet unavailable - falling back to SecretService", None),
    ("[Credentials] Keyring backend detected: SecretService (GNOME Keyring)", None),
    ("[Credentials] Credential storage available - 6 saved accounts", None),
    ("[Service] Input service started (backend: Xlib)", None),
    ("[Service] ChatFSM ACTIVE - forwarding: Focused Toon Only", None),
    ("[Hotkey] Registered 4 global chords", None),
    ("[TTR API] Login attempt 1 failed: timeout - retrying", None),
    ("[TTR API] Login queue: position 3 of 41", None),
    ("[TTR API] Login OK - cookie issued", None),
    ("[Launch] Patch manifest checked - 1 file updated (phase_14.mf)", None),
    ("[Launch] TTREngine started (pid 48210)", "ok"),
    ("[CCLauncher] resolve_proton: Proton 9.0-4 (Steam library) - cached", None),
    ("Window manager: 2 TTR windows found", None),
    ('[Input] Keyset "WASD" bound → Duddles (TTR)', None),
    ('[Input] Keyset "Arrows" bound → Mr. Fumbles (TTR)', None),
    ("[Profile] Portraits refreshed for 2 toons", None),
    ("[KeepAlive] Armed · action: Jump · interval: 30 sec", None),
]


def build(out_dir):
    from utils.widgets.logs_console.logs_card import LogsCard
    from utils.widgets.logs_console.records import make_line

    app = QApplication.instance() or QApplication([])
    card = LogsCard()
    card.resize(900, 640)   # window-900 parity: visible card 868, content 836 (bundle geometry)
    t0 = datetime(2026, 7, 9, 17, 57, 0)
    for i, (msg, level) in enumerate(SEEDS):
        card.model.append(make_line(msg, level=level,
                                    now=t0 + timedelta(seconds=6 * i)))
    card.show()
    app.processEvents()
    app.processEvents()

    def snap(name):
        from PySide6.QtCore import QEvent
        # No running event loop here: reap deleteLater'd chip generations or
        # stale widgets paint under the current ones.
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        card.grab().save(os.path.join(out_dir, name))
        print(os.path.join(out_dir, name))

    snap("01-default-following.png")

    chip = next(c for c in card.chips() if c.text() == "[KeepAlive]")
    chip.setChecked(True)
    snap("02-tag-filter-keepalive.png")
    chip.setChecked(False)

    card.search.setText("login")
    snap("03-search-filter.png")
    card.search.setText("")

    # Pause via the public API rather than scrolling to the top: with only
    # ~19 seed lines the pane's content doesn't yet overflow its viewport
    # (scrollbar max == 0), so a manual setValue(0) is a silent no-op and
    # follow-mode never turns off. set_following(False) is the exact call
    # the pause button makes and reliably reaches the paused state
    # regardless of viewport fill.
    card.pane.set_following(False)
    app.processEvents()
    for j in range(4):
        card.model.append(make_line("[KeepAlive] Jump sent → 2 idle toons",
                                    now=t0 + timedelta(minutes=3, seconds=j)))
    app.processEvents()
    snap("04-paused-scrollback.png")

    card.pane.set_following(True)
    app.processEvents()
    card.apply_theme(False)
    snap("05-light-theme.png")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/logs-render"
    os.makedirs(out, exist_ok=True)
    build(out)
