"""SettingsRows built the way SettingsTab builds its pages, for the tests of
the shared Settings rows: they test SettingsRows directly, so they survive
the deletion of SettingsTab at cut-over.

RowsUnderTest is a SettingsRows (so monkeypatching a handler on it reaches
the code under test) whose general, games, features and advanced pages are
built into page widgets laid out exactly as SettingsTab lays them out
(margins 24 12 24 28, spacing 4, top-aligned, 768 px wide at most). The few
QWidget calls the tests make on the old tab (findChildren, resize,
deleteLater, showEvent) go to the host widget holding the pages."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from utils.theme_manager import resolve_theme
from utils.widgets.settings_rows import SettingsRows

PAGES = ("general", "games", "features", "advanced")
CONTENT_MAX_W = 768        # tabs/settings_tab.py SETTINGS_CONTENT_MAX_W


class RowsUnderTest(SettingsRows):
    def __init__(self, settings_manager, keymap_manager=None, credentials_manager=None):
        super().__init__(settings_manager, keymap_manager, credentials_manager)
        self.host = QWidget()
        self.set_dialog_parent(self.host)
        host_lay = QVBoxLayout(self.host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        self.pages: dict[str, QWidget] = {}
        for key in PAGES:
            page = QWidget(self.host)
            lay = QVBoxLayout(page)
            lay.setContentsMargins(24, 12, 24, 28)
            lay.setSpacing(4)
            lay.setAlignment(Qt.AlignTop)
            lay.addStretch(1)
            page._panel_layout = lay
            page.setMaximumWidth(CONTENT_MAX_W)
            host_lay.addWidget(page)
            self.pages[key] = page
        self._build_general_page(self.pages["general"])
        self._build_games_page(self.pages["games"])
        self._build_features_page(self.pages["features"])
        self._build_advanced_page(self.pages["advanced"])
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self._apply_rows_theme(resolve_theme(self.settings_manager) == "dark")

    # QWidget calls the old tests made on SettingsTab.
    def findChildren(self, *args, **kwargs):  # noqa: N802 (Qt name)
        return self.host.findChildren(*args, **kwargs)

    def resize(self, *args) -> None:
        self.host.resize(*args)

    def deleteLater(self) -> None:  # noqa: N802 (Qt name)
        self.host.deleteLater()
        super().deleteLater()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt name)
        # What SettingsTab.showEvent does for the rows.
        if getattr(self, "_hotkey_accounts_provider", None) is not None:
            self._rebuild_hotkey_slot_rows()
