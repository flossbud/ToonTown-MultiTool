"""Clipboard helpers that survive Flatpak display-boundary quirks."""

from __future__ import annotations

import logging
import subprocess

from PySide6.QtWidgets import QApplication

from utils.host_spawn import host_run, in_flatpak

logger = logging.getLogger(__name__)


_HOST_CLIPBOARD_SCRIPT = """
if command -v wl-copy >/dev/null 2>&1; then
    exec wl-copy --type 'text/plain;charset=utf-8'
fi
if command -v xclip >/dev/null 2>&1; then
    exec xclip -selection clipboard -in
fi
if command -v xsel >/dev/null 2>&1; then
    exec xsel --clipboard --input
fi
exit 127
""".strip()


def copy_text(text: str) -> bool:
    """Copy text through Qt and, in Flatpak, through a host clipboard helper.

    Qt's in-process clipboard cache can report success even when a sandboxed
    XWayland selection does not become available to host Wayland apps. The
    host fallback publishes the same text outside the sandbox and passes the
    payload on stdin so sensitive error details do not appear in argv.

    Returns True only when the copy is believed to be pasteable by other
    apps. Outside Flatpak that is the Qt clipboard result. Inside Flatpak the
    Qt clipboard is known-unreliable (the bug this guards against), so the
    host helper is the source of truth: a missing helper or nonzero exit
    means we cannot promise a pasteable result, even though Qt reported
    success. Both owners carry identical text, so last-writer-wins is safe.
    """
    qt_copied = False
    app = QApplication.instance()
    if app is not None:
        QApplication.clipboard().setText(text)
        qt_copied = True

    if not in_flatpak():
        return qt_copied

    try:
        result = host_run(
            ["sh", "-c", _HOST_CLIPBOARD_SCRIPT],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except Exception:
        logger.warning("host clipboard helper failed to run", exc_info=True)
        return False

    if result.returncode != 0:
        logger.warning(
            "host clipboard helper exited %s (no wl-copy/xclip/xsel?); "
            "copy may not be pasteable", result.returncode,
        )
        return False
    return True
