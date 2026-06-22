"""The AppImage AppRun MUST force xcb, never wayland.

This app is X11-only (overlay = X11 override-redirect + Xlib SHAPE; input =
xdotool/pynput), so running under native Wayland silently breaks transparent
mode and input. A 2026-04-24 revision forced wayland in AppRun to dodge a
SIGSEGV/keyring issue that has since been fixed; this guards against that
regression returning."""
import os


def _apprun_exec_lines() -> list:
    """Executable (non-comment, non-blank) shell lines, so explanatory comments
    that mention 'wayland'/'xcb' can't produce false matches."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "AppDir", "AppRun")
    with open(p) as f:
        lines = []
        for raw in f:
            s = raw.strip()
            if s and not s.startswith("#"):
                lines.append(s)
    return lines


def test_apprun_forces_xcb():
    assert any("QT_QPA_PLATFORM=xcb" in line for line in _apprun_exec_lines())


def test_apprun_does_not_force_wayland():
    # Forcing wayland here puts the X11-only app on the wrong platform.
    assert not any("QT_QPA_PLATFORM=wayland" in line for line in _apprun_exec_lines())


def test_apprun_keeps_user_override_hatch():
    # The force must be conditional so a user can still set QT_QPA_PLATFORM.
    assert any('if [ -z "$QT_QPA_PLATFORM" ]' in line for line in _apprun_exec_lines())
