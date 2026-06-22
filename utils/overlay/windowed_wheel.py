"""In-window host for the radial wheel in WINDOWED mode.

Today the wheel is hosted only by an X11 override-redirect OverlaySurface that
exists while transparent mode is active. In windowed mode there is no such
surface, so we host the same RadialMenuWidget as a transparent, click-catching
CHILD of the main window's content widget - no new top-level window, which
sidesteps the known GNOME/Mutter invisible-frameless bug.

The host spans the parent's content area; the menu is an emblem_dia*4 child
centered ON the emblem (exactly like the transparent surface), so the widget's
own soft vignette stays a local halo. The menu consumes its own presses (see
RadialMenuWidget.mousePressEvent), so any press that reaches the host is
necessarily outside the wheel -> dismiss.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget

from utils.overlay.radial_menu import RadialMenuWidget


class WindowedWheelHost(QWidget):
    """Transparent child overlay that hosts a windowed-variant RadialMenuWidget
    centered on the emblem and dismisses on click-away / the wheel's own close
    (Back spoke / Esc / 15s idle / all-accounts-launched)."""

    closed = Signal()

    def __init__(self, parent, emblem, emblem_diameter, customizations=None):
        super().__init__(parent)
        # Transparent to the tab behind it, but still catches mouse (do NOT set
        # WA_TransparentForMouseEvents): no background fill -> the tab shows
        # through everywhere the menu child does not paint.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self._emblem = emblem
        self._alive = True
        self.menu = RadialMenuWidget(
            emblem_diameter, customizations=customizations, variant="windowed",
            parent=self)
        side = int(emblem_diameter * 4)
        self.menu.resize(side, side)
        # The wheel's own close paths (Back spoke, Esc, idle, all-launched)
        # dismiss the whole host:
        self.menu.close_requested.connect(self.dismiss)

    def show_centered(self):
        """Fill the parent, center the menu on the emblem, reveal, focus."""
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self._center_menu_on_emblem()        # after show: the mapping is valid
        self.menu.show()
        self.menu.raise_()
        self.menu.setFocus()                 # Esc handled by the menu
        self.menu.start_reveal()

    def _center_menu_on_emblem(self):
        ec = self._emblem.mapToGlobal(self._emblem.rect().center())
        local = self.mapFromGlobal(ec)
        sz = self.menu.size()
        self.menu.move(local.x() - sz.width() // 2,
                       local.y() - sz.height() // 2)

    def mousePressEvent(self, e):
        # The menu consumes its own presses, so a press here is outside the wheel.
        self.dismiss()

    def dismiss(self):
        if not self._alive:                  # idempotent across every path
            return
        self._alive = False
        self.hide()
        self.closed.emit()
        self.deleteLater()
