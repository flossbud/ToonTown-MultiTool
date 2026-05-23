"""LaunchTab: restore collapsed state from settings at init, persist on toggle."""
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSettings:
    """In-memory stand-in for SettingsManager — same .get/.set surface."""
    def __init__(self, initial: dict | None = None):
        self._d = dict(initial or {})
        self._cb = []

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value
        for cb in self._cb:
            cb(key, value)

    def on_change(self, cb):
        self._cb.append(cb)


class _FakeCredManager:
    """Minimal CredentialsManager stand-in: returns no accounts."""
    keyring_probe_pending = False
    keyring_available = True

    def get_accounts_metadata(self):
        return []

    def run_probe(self, timeout=45.0):
        return True


def _make_tab(qapp, settings):
    """Build a LaunchTab with fake settings + cred manager."""
    from tabs.launch_tab import LaunchTab
    return LaunchTab(
        settings_manager=settings,
        cred_manager=_FakeCredManager(),
    )


def test_init_reads_ttr_setting_and_applies_collapsed_state(qapp):
    settings = _FakeSettings({"launch_section_ttr_collapsed": True})
    tab = _make_tab(qapp, settings)
    assert tab.ttr_section.is_collapsed is True
    assert tab.cc_section.is_collapsed is False


def test_init_reads_cc_setting_independently(qapp):
    settings = _FakeSettings({"launch_section_cc_collapsed": True})
    tab = _make_tab(qapp, settings)
    assert tab.cc_section.is_collapsed is True
    assert tab.ttr_section.is_collapsed is False


def test_init_with_no_settings_renders_both_expanded(qapp):
    settings = _FakeSettings()
    tab = _make_tab(qapp, settings)
    assert tab.ttr_section.is_collapsed is False
    assert tab.cc_section.is_collapsed is False


def test_user_toggle_writes_ttr_setting(qapp):
    settings = _FakeSettings()
    tab = _make_tab(qapp, settings)
    # Simulate a user header click by emitting collapsed_changed directly.
    # (Section-level click tests already verify the click -> emit path.)
    tab.ttr_section.set_collapsed(True, animate=False)
    tab.ttr_section.collapsed_changed.emit(True)
    assert settings.get("launch_section_ttr_collapsed") is True
    assert settings.get("launch_section_cc_collapsed") is None  # untouched


def test_user_toggle_writes_cc_setting_independently(qapp):
    settings = _FakeSettings()
    tab = _make_tab(qapp, settings)
    tab.cc_section.set_collapsed(True, animate=False)
    tab.cc_section.collapsed_changed.emit(True)
    assert settings.get("launch_section_cc_collapsed") is True
    assert settings.get("launch_section_ttr_collapsed") is None


def test_compact_height_sync_excludes_collapsed_sections(qapp):
    """When one section is collapsed in compact mode, the other should
    be allowed to take its natural sizeHint and the collapsed section's
    min-height must be 0 (so it can shrink to the header bar)."""
    settings = _FakeSettings()
    tab = _make_tab(qapp, settings)
    tab.set_layout_mode("compact")
    tab.ttr_section.set_collapsed(True, animate=False)
    tab._sync_compact_section_heights()
    assert tab.ttr_section.minimumHeight() == 0
    # cc_section's minimumHeight should be max(its sizeHint, 380),
    # not max(ttr's, cc's, 380).
    cc_hint = tab.cc_section.sizeHint().height()
    assert tab.cc_section.minimumHeight() == max(cc_hint, 380)


def test_compact_height_sync_both_collapsed(qapp):
    settings = _FakeSettings()
    tab = _make_tab(qapp, settings)
    tab.set_layout_mode("compact")
    tab.ttr_section.set_collapsed(True, animate=False)
    tab.cc_section.set_collapsed(True, animate=False)
    tab._sync_compact_section_heights()
    assert tab.ttr_section.minimumHeight() == 0
    assert tab.cc_section.minimumHeight() == 0
