"""Themed picker dialog for choosing among multiple Corporate Clash installs."""

from __future__ import annotations

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from services.wine_runtimes import WineInstall, install_signature
from utils.widgets.picker_card import PickerCard


_CONFIRM_KEEP = "Keep this install"
_CONFIRM_USE = "Use this install"


def _short_path(p: str) -> str:
    home = os.path.expanduser("~")
    if p == home:
        return "~"
    if p.startswith(home + os.sep):
        return "~" + p[len(home):]
    return p


class CCInstallPickerDialog(QDialog):
    """Modal dialog listing detected Corporate Clash installs.

    When ``active_signature`` is provided and matches one of the (non-stale)
    installs, that row is rendered with active=True and pre-selected; the
    confirm button reads "Keep this install" while the active row stays
    selected, "Use this install" otherwise.

    Stale handling: installs whose exe_path no longer exists on disk are
    filtered out unless their signature matches ``active_signature``, in
    which case they render with stale=True and are un-pickable so the
    user can see why their last pick is no longer launchable.
    """

    def __init__(
        self,
        installs: list[WineInstall],
        parent: QWidget | None = None,
        active_signature: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("picker_dialog")
        self.setWindowTitle("Choose Corporate Clash install")
        self.setModal(True)
        self._active_signature = active_signature or None
        self._cards: list[PickerCard] = []
        self._card_installs: list[WineInstall] = []
        self._card_is_stale: list[bool] = []
        self._selected: WineInstall | None = None
        self._selected_index: int = -1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)

        intro = QLabel(
            "Multiple Corporate Clash installs were detected. "
            "Choose which one to use."
        )
        intro.setObjectName("picker_intro")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        # Card column inside a scroll area for overflow.
        self._scroll = QScrollArea()
        self._scroll.setObjectName("picker_card_list")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        try:
            from utils.widgets.auto_hide_scrollbar import install_modern_scrollbar
            from utils.theme_manager import is_dark_palette
            install_modern_scrollbar(self._scroll, is_dark=is_dark_palette())
        except Exception:
            # Auto-hide scrollbar is a polish nicety; fall back to Qt default.
            pass

        card_holder = QWidget()
        self._card_layout = QVBoxLayout(card_holder)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(8)

        for inst in installs:
            exists = os.path.exists(inst.exe_path)
            is_active = bool(
                self._active_signature
                and install_signature(inst) == self._active_signature
            )
            if not exists and not is_active:
                # Truly orphaned: drop entirely.
                continue
            i = len(self._cards)
            card = PickerCard(
                chip_slug=inst.launcher,
                name=inst.display_name,
                path=_short_path(inst.exe_path),
                active=is_active,
                stale=(not exists),
            )
            card.clicked.connect(lambda i=i: self._on_card_clicked(i))
            card.doubleClicked.connect(lambda i=i: self._on_card_double_clicked(i))
            self._card_layout.addWidget(card)
            self._cards.append(card)
            self._card_installs.append(inst)
            self._card_is_stale.append(not exists)

        self._card_layout.addStretch(1)
        self._scroll.setWidget(card_holder)
        outer.addWidget(self._scroll, 1)

        # Buttons.
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.confirm_btn = QPushButton(_CONFIRM_USE)
        self.confirm_btn.setObjectName("picker_primary_btn")
        self.confirm_btn.setDefault(True)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._confirm)
        btn_row.addWidget(self.confirm_btn)
        outer.addLayout(btn_row)

        self.resize(640, 480)
        self.setMinimumSize(560, 360)
        self.setMaximumWidth(820)

        # Pre-select the active row if it's a non-stale card.
        for i, inst in enumerate(self._card_installs):
            if (
                self._active_signature
                and install_signature(inst) == self._active_signature
                and not self._card_is_stale[i]
            ):
                self.select_index(i)
                break

    # ── Public API (preserved) ──────────────────────────────────────────
    def cards(self) -> list[PickerCard]:
        return list(self._cards)

    def select_index(self, idx: int) -> None:
        """Programmatically pick a row (used in tests and the boot prompt)."""
        if not (0 <= idx < len(self._cards)):
            return
        if self._card_is_stale[idx]:
            return  # Stale rows are un-pickable.
        if self._selected_index >= 0:
            self._cards[self._selected_index].set_selected(False)
        self._selected_index = idx
        self._cards[idx].set_selected(True)
        self._selected = self._card_installs[idx]
        self._update_confirm_button()

    def selected_install(self) -> WineInstall | None:
        return self._selected

    # ── Internal ────────────────────────────────────────────────────────
    def _on_card_clicked(self, idx: int) -> None:
        self.select_index(idx)

    def _on_card_double_clicked(self, idx: int) -> None:
        self.select_index(idx)
        self._confirm()

    def _update_confirm_button(self) -> None:
        idx = self._selected_index
        self.confirm_btn.setEnabled(idx >= 0)
        if (
            self._active_signature
            and 0 <= idx < len(self._card_installs)
            and install_signature(self._card_installs[idx]) == self._active_signature
        ):
            self.confirm_btn.setText(_CONFIRM_KEEP)
        else:
            self.confirm_btn.setText(_CONFIRM_USE)

    def _confirm(self) -> None:
        idx = self._selected_index
        if 0 <= idx < len(self._card_installs) and not self._card_is_stale[idx]:
            self._selected = self._card_installs[idx]
            self.accept()
