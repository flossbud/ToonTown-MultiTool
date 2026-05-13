"""Tests for CreditsTab content and structure."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from utils.settings_manager import SettingsManager


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def settings_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return SettingsManager()


def _all_label_texts(widget):
    """Recursively collect text from every QLabel under widget."""
    out = []
    for label in widget.findChildren(QLabel):
        out.append(label.text())
    return out


def test_credits_tab_constructs_without_error(qapp, settings_manager):
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    assert tab is not None


def test_title_is_app_name_without_version(qapp, settings_manager):
    """Title is just 'ToonTown MultiTool' — no version suffix. Version
    text lives in the header bar, so showing it again on the Credits page
    is redundant."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    texts = _all_label_texts(tab)
    assert "ToonTown MultiTool" in texts, (
        f"Expected exact title 'ToonTown MultiTool', got labels: {texts!r}"
    )
    for t in texts:
        # No 'v2', 'v3', etc. version-tag prefix anywhere in the credits.
        assert " v" not in t and not t.startswith("v"), (
            f"Found a version-tag substring in credits label: {t!r}"
        )


def test_hook_line_present(qapp, settings_manager):
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    texts = _all_label_texts(tab)
    assert any(
        "For when one toon isn't enough." in t for t in texts
    ), f"Hook line not found in labels: {texts!r}"


def test_tagline_mentions_both_games_and_both_platforms(qapp, settings_manager):
    """The tagline must convey full scope: TTR + CC, Linux + Windows."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    joined = "\n".join(_all_label_texts(tab))
    assert "Toontown Rewritten" in joined
    assert "Corporate Clash" in joined
    assert "Linux" in joined
    assert "Windows" in joined


def test_byline_dropped_created_prefix(qapp, settings_manager):
    """Byline reads 'by flossbud 🐾', not 'Created by flossbud 🐾'."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    texts = _all_label_texts(tab)
    assert any(t == "by flossbud 🐾" for t in texts), (
        f"Expected exact byline 'by flossbud 🐾', got labels: {texts!r}"
    )
    for t in texts:
        assert not t.startswith("Created by"), (
            f"Found stale 'Created by' prefix: {t!r}"
        )


def test_byline_font_includes_noto_emoji_fallback(qapp, settings_manager):
    """Byline font's family list must include Noto Color Emoji as a
    fallback so the paw glyph renders on Fedora (default install lacks
    a color emoji font)."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    texts = _all_label_texts(tab)
    byline_labels = [
        lbl for lbl in tab.findChildren(QLabel)
        if lbl.text() == "by flossbud 🐾"
    ]
    assert byline_labels, f"Byline label not found among: {texts!r}"
    families = byline_labels[0].font().families()
    assert "Noto Color Emoji" in families, (
        f"Expected 'Noto Color Emoji' in byline font families, got {families!r}"
    )


def test_no_capability_bullets(qapp, settings_manager):
    """The earlier design had four capability bullets. Visual review
    removed them in favor of a larger centerpiece image; this is a
    regression guard so they don't accidentally come back."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    joined = "\n".join(_all_label_texts(tab))
    for phrase in (
        "per-slot custom keymaps",
        "OS-keyring",
        "invasion tracker",
    ):
        assert phrase not in joined, (
            f"Capability bullet phrase {phrase!r} found in labels; bullets "
            f"should not be in the Credits tab"
        )


def test_no_em_dashes_in_user_facing_text(qapp, settings_manager):
    """The codebase scrubbed em-dashes from user-facing strings (commit
    633dfe1). The Credits tab must follow that posture."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    for t in _all_label_texts(tab):
        assert "—" not in t, f"Em-dash found in label: {t!r}"
        assert "–" not in t, f"En-dash found in label: {t!r}"


def test_centerpiece_image_loads(qapp, settings_manager):
    """An image label exists with the flossbud asset's pixmap loaded."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    image_labels = [
        lbl for lbl in tab.findChildren(QLabel)
        if lbl.pixmap() is not None and not lbl.pixmap().isNull()
    ]
    assert image_labels, "Expected at least one QLabel with a loaded pixmap"


def test_credits_footer_links_present(qapp, settings_manager):
    """Footer row exposes GitHub, Report a bug, and Privacy Policy links with correct URLs."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    joined = "\n".join(_all_label_texts(tab))
    assert "https://github.com/flossbud/ToonTown-MultiTool" in joined
    assert "https://github.com/flossbud/ToonTown-MultiTool/issues/new" in joined
    assert "https://github.com/flossbud/ToonTown-MultiTool/blob/main/PRIVACY.md" in joined
    assert "GitHub" in joined
    assert "Report a bug" in joined
    assert "Privacy Policy" in joined


def test_credits_footer_label_routes_links_through_open_url(qapp, settings_manager, monkeypatch):
    """Footer must NOT use Qt's openExternalLinks (broken in AppImage due to
    PyInstaller's LD_LIBRARY_PATH leak into xdg-open). Instead, clicking a
    link emits linkActivated, which is wired to utils.open_url.open_url."""
    from PySide6.QtCore import Qt
    from tabs.credits_tab import CreditsTab

    captured: list[str] = []

    def fake_open_url(url):
        captured.append(url)
        return True

    monkeypatch.setattr("tabs.credits_tab.open_url", fake_open_url)

    tab = CreditsTab(settings_manager=settings_manager)
    footer = tab.footer_links
    assert footer.openExternalLinks() is False, (
        "openExternalLinks must be False; Qt's xdg-open call leaks "
        "LD_LIBRARY_PATH from PyInstaller and breaks links in the AppImage."
    )
    assert footer.textFormat() == Qt.RichText

    footer.linkActivated.emit("https://example.com/test")
    assert captured == ["https://example.com/test"], (
        f"Expected linkActivated to route through open_url, got {captured!r}"
    )


def test_credits_footer_uses_pipe_separators(qapp, settings_manager):
    """Footer row uses pipe separators (not middots) between the three links."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    text = tab.footer_links.text()
    assert text.count("|") >= 2, f"Expected at least two pipe separators, got: {text!r}"
    assert "·" not in text, f"Middot found in footer text; spec says use pipe: {text!r}"


def test_credits_tab_repaints_on_system_theme_change_when_pref_is_system(
    qapp, settings_manager, monkeypatch
):
    """When TTMT theme = 'system', an OS light/dark toggle must trigger
    refresh_theme on the credits tab. Issue 2 from v2.1.3 beta report."""
    from tabs.credits_tab import CreditsTab

    settings_manager.set("theme", "system")
    tab = CreditsTab(settings_manager=settings_manager)

    refresh_calls = []
    original_refresh = tab.refresh_theme

    def counting_refresh():
        refresh_calls.append(True)
        original_refresh()

    monkeypatch.setattr(tab, "refresh_theme", counting_refresh)
    tab._on_system_theme_changed("dark")
    assert refresh_calls, "refresh_theme was not called on system_theme_changed"


def test_credits_tab_skips_refresh_when_explicit_pref_set(
    qapp, settings_manager, monkeypatch
):
    """When TTMT theme is an explicit 'light' or 'dark', an OS toggle must
    NOT overwrite the user's choice."""
    from tabs.credits_tab import CreditsTab

    settings_manager.set("theme", "dark")
    tab = CreditsTab(settings_manager=settings_manager)

    refresh_calls = []
    monkeypatch.setattr(tab, "refresh_theme", lambda: refresh_calls.append(True))
    tab._on_system_theme_changed("light")
    assert not refresh_calls, (
        "refresh_theme should not run on system change when user pref is explicit "
        "(got {} calls)".format(len(refresh_calls))
    )


def test_credits_footer_link_color_matches_theme_muted(qapp, settings_manager):
    """Footer link color is sourced from get_theme_colors()['text_muted']."""
    from PySide6.QtGui import QPalette
    from tabs.credits_tab import CreditsTab
    from utils.theme_manager import resolve_theme, get_theme_colors

    tab = CreditsTab(settings_manager=settings_manager)
    is_dark = resolve_theme(settings_manager) == "dark"
    expected = get_theme_colors(is_dark)["text_muted"].lower()
    actual = tab.footer_links.palette().color(QPalette.Link).name().lower()
    assert actual == expected, (
        f"Expected footer link color {expected!r} (theme text_muted), "
        f"got {actual!r}. refresh_theme() must set QPalette.Link on footer_links."
    )
