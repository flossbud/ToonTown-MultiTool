"""Tests for the icon-resolution helpers in main.py.

The helpers are split between a pure path-picker (`_resolve_icon_path`) and
the QIcon constructor (`_resolve_app_icon`). The path-picker is the one with
branching logic per channel; we test that directly.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_resolve_icon_path_stable_channel(qapp, monkeypatch):
    """Stable build resolves to the .ico fallback."""
    import main
    monkeypatch.setattr(main, "is_beta", lambda: False)
    path = main._resolve_icon_path()
    assert path.endswith(os.path.join("assets", "ToonTownMultiTool.ico")), path


def test_resolve_icon_path_beta_channel(qapp, monkeypatch):
    """Beta build resolves to the badged PNG."""
    import main
    monkeypatch.setattr(main, "is_beta", lambda: True)
    path = main._resolve_icon_path()
    assert path.endswith(os.path.join("assets", "ToonTownMultiTool-beta.png")), path


def test_resolve_app_icon_stable_returns_non_null(qapp, monkeypatch):
    """End-to-end: stable channel yields a usable QIcon."""
    import main
    from PySide6.QtGui import QIcon
    monkeypatch.setattr(main, "is_beta", lambda: False)
    monkeypatch.setattr(QIcon, "fromTheme", lambda _name: QIcon())  # force null
    icon = main._resolve_app_icon()
    assert not icon.isNull()
    assert not icon.pixmap(40, 40).isNull()


def test_resolve_app_icon_beta_returns_non_null(qapp, monkeypatch):
    """End-to-end: beta channel yields a usable QIcon (requires the beta PNG to exist)."""
    import main
    from PySide6.QtGui import QIcon
    monkeypatch.setattr(main, "is_beta", lambda: True)
    monkeypatch.setattr(QIcon, "fromTheme", lambda _name: QIcon())  # force null
    icon = main._resolve_app_icon()
    assert not icon.isNull()
    assert not icon.pixmap(40, 40).isNull()


def test_resolve_app_icon_skips_theme_when_not_packaged(qapp, monkeypatch):
    """Dev runs (not packaged) must not consult QIcon.fromTheme. A previously
    installed packaged version of ourselves (e.g. coexisting Flatpak) registers
    its icon under our canonical app id in the XDG theme; trusting that lookup
    in dev would surface the stale icon instead of the bundled one."""
    import main
    from PySide6.QtGui import QIcon
    monkeypatch.setattr(main, "is_beta", lambda: False)
    monkeypatch.setattr(main, "_is_packaged_install", lambda: False, raising=False)
    calls = []
    monkeypatch.setattr(QIcon, "fromTheme", lambda name: calls.append(name) or QIcon())
    main._resolve_app_icon()
    assert calls == [], f"theme lookups should be skipped in dev runs, but got: {calls}"


def test_resolve_app_icon_consults_theme_when_packaged(qapp, monkeypatch):
    """Packaged installs (AppImage/Flatpak/PyInstaller/AUR) keep the existing
    behaviour: prefer the system XDG theme, since it carries the multi-size
    icon set the WM expects."""
    import main
    from PySide6.QtGui import QIcon
    monkeypatch.setattr(main, "is_beta", lambda: False)
    monkeypatch.setattr(main, "_is_packaged_install", lambda: True, raising=False)
    calls = []
    monkeypatch.setattr(QIcon, "fromTheme", lambda name: calls.append(name) or QIcon())
    main._resolve_app_icon()
    assert calls == [main.APP_DESKTOP_ID]
