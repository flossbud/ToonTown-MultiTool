"""Offscreen render probe for the feature-discovery states. Writes PNGs of
(1) the pinwheel with both flags off (pill 'Enable features'), (2) one flag
on ('More features'), (3) both on (pill gone), and (4) the popover with the
ToS confirm expanded. For visual review against the bundle screenshots.

Run (on the box):
  TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
      python scripts/probes/feature_discovery_states.py /tmp/fd_probe
"""
import os
import sys
import tempfile

# Runnable from anywhere: put the repo root on sys.path (this file lives at
# scripts/probes/<name>.py).
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
# Probe isolation law: point config at tmp BEFORE any app import.
_tmp = tempfile.mkdtemp(prefix="ttmt-fd-probe-")
os.environ["HOME"] = _tmp
os.environ["TTMT_CONFIG_DIR"] = _tmp

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


class _FakeSettings:
    def __init__(self, initial=None):
        self._data = dict(initial or {})
        self._callbacks = []

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        for cb in self._callbacks:
            cb(key, value)

    def on_change(self, callback):
        self._callbacks.append(callback)


class _FakeWM(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return []

    def clear_window_ids(self):
        pass

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass


def main(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    from tabs.multitoon_tab import MultitoonTab

    sm = _FakeSettings()
    tab = MultitoonTab(settings_manager=sm, window_manager=_FakeWM())
    tab.resize(844, 668)
    tab.show()
    app.processEvents()
    tab.grab().save(os.path.join(out_dir, "01-both-off.png"))

    sm.set("click_sync_enabled", True)
    app.processEvents()
    tab.grab().save(os.path.join(out_dir, "02-one-on.png"))

    sm.set("keep_alive_enabled", True)
    app.processEvents()
    tab.grab().save(os.path.join(out_dir, "03-both-on-pill-gone.png"))

    sm.set("click_sync_enabled", False)
    sm.set("keep_alive_enabled", False)
    sm._data.pop("keep_alive_consent_acknowledged", None)
    tab._open_feature_popover(0)
    pop = tab._feature_popover
    pop._on_switch_clicked("ka")   # opens the ToS confirm
    app.processEvents()
    pop.grab().save(os.path.join(out_dir, "04-popover-tos.png"))

    svc = getattr(tab, "input_service", None)
    if svc is not None:
        svc.shutdown()
    print(f"wrote 4 PNGs to {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fd_probe")
