"""Build and dispose launchpad windows offscreen, and report what outlives them.

A construction check for object lifetime: every LaunchpadWindow should be
gone after shutdown + close + deleteLater, with nothing it built left
behind. Prints, per window: process memory, how many window wrappers are
still alive, and how many widgets / top-level widgets Qt still has. At the
end, the leftover top-levels by class and object name.

    python scripts/launchpad_lifetime_probe.py [N]        (default 4)

Exit code 0 when no window wrapper survives and the widget count does not
grow; 1 otherwise.
"""
from __future__ import annotations

import gc
import os
import sys
import tempfile
import weakref

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(QT_QPA_PLATFORM="offscreen", TTMT_NO_VENV_REEXEC="1",
                  TTMT_SELF_CHECK="1", TTMT_GRANDSTAND="1",
                  PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring")
os.environ["TTMT_CONFIG_DIR"] = tempfile.mkdtemp(prefix="ttmt-probe-cfg-")
os.environ["HOME"] = tempfile.mkdtemp(prefix="ttmt-probe-home-")

from PySide6.QtCore import QEventLoop, QTimer           # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402


def _rss_mb() -> int:
    try:
        with open("/proc/self/status") as f:
            return int(f.read().split("VmRSS:")[1].split()[0]) // 1024
    except Exception:
        return -1


def _spin(app, ms: int = 50) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run(n: int) -> int:
    app = QApplication.instance() or QApplication([])
    import utils.launchpad_window as lw
    import utils.update_checker as uc
    lw._quit_app = lambda: None
    uc.UpdateChecker.check_async = lambda self, *, manual: True

    refs, widgets = [], []
    for i in range(n):
        w = lw.LaunchpadWindow()
        w.resize(880, 860)
        w.show()
        app.processEvents()
        w.shutdown()
        w.close()
        w.deleteLater()
        _spin(app)
        refs.append(weakref.ref(w))
        del w
        gc.collect()
        _spin(app)
        alive = sum(1 for r in refs if r() is not None)
        widgets.append(len(app.allWidgets()))
        print(f"window {i + 1}: rss {_rss_mb()} MB, window wrappers alive {alive}, "
              f"widgets {widgets[-1]}, top-levels {len(app.topLevelWidgets())}",
              flush=True)

    leftovers: dict[str, int] = {}
    for t in app.topLevelWidgets():
        try:
            key = f"{type(t).__name__}({t.objectName() or '-'})"
        except RuntimeError:
            key = "deleted"
        leftovers[key] = leftovers.get(key, 0) + 1
    print("leftover top-levels:", leftovers or "none")

    alive = sum(1 for r in refs if r() is not None)
    grows = len(widgets) > 1 and widgets[-1] > widgets[0]
    ok = alive == 0 and not grows
    print("OK" if ok else f"LEAK: {alive} window wrapper(s) alive, widgets "
          f"{widgets[0]} -> {widgets[-1]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(int(sys.argv[1]) if len(sys.argv) > 1 else 4))
