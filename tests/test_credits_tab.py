"""Tests for CreditsTab content and structure."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from utils.settings_manager import SettingsManager
from utils.version import APP_VERSION


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


def test_title_uses_dynamic_app_version(qapp, settings_manager):
    """Title must read the current APP_VERSION, not a hardcoded string."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    texts = _all_label_texts(tab)
    matching = [t for t in texts if "ToonTown MultiTool" in t and APP_VERSION in t]
    assert matching, (
        f"Expected a label containing both 'ToonTown MultiTool' and "
        f"version {APP_VERSION!r}, got labels: {texts!r}"
    )


def test_no_stale_v2_0_string_anywhere(qapp, settings_manager):
    """Regression guard: the literal 'v2.0' string must not appear."""
    from tabs.credits_tab import CreditsTab
    tab = CreditsTab(settings_manager=settings_manager)
    texts = _all_label_texts(tab)
    for t in texts:
        assert "v2.0" not in t, f"Found stale 'v2.0' in label: {t!r}"


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
            f"Capability bullet phrase {phrase!r} found in labels — bullets "
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
