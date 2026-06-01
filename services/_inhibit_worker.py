"""Run SleepInhibitor.acquire() off the GUI thread.

acquire() shells out to systemd-inhibit and polls `systemd-inhibit --list`;
under Flatpak that crosses flatpak-spawn, which can be slow. Doing it on the
GUI thread would freeze Keep-Alive activation, so it runs in a QThread and
emits the resulting InhibitStatus back to the GUI thread.
"""
from PySide6.QtCore import QThread, Signal

from services.sleep_inhibitor import InhibitStatus


class InhibitAcquireWorker(QThread):
    # NOTE: deliberately NOT named `finished` -- that would shadow QThread's
    # built-in finished() completion signal (which fires when run() returns).
    status_ready = Signal(object)  # emits InhibitStatus

    def __init__(self, inhibitor, parent=None):
        super().__init__(parent)
        self._inhibitor = inhibitor

    def run(self):
        try:
            self._inhibitor.acquire()
            status = self._inhibitor.status
        except Exception:
            status = InhibitStatus()
        self.status_ready.emit(status)
