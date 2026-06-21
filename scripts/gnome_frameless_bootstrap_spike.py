"""THROWAWAY spike: prove frame-then-strip on the REAL main window on GNOME.
Isolated from real config (tmp HOME + TTMT_CONFIG_DIR; null keyring) per
project IRON LAWs so it can never touch real settings/portraits."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="ttmt_spike_")
os.environ["HOME"] = _tmp
os.environ["TTMT_CONFIG_DIR"] = _tmp
os.environ["XDG_CONFIG_HOME"] = _tmp
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from Xlib import display as _xd, Xatom

_D = _xd.Display()
_MWH = _D.intern_atom("_MOTIF_WM_HINTS")
_OPACITY = _D.intern_atom("_NET_WM_WINDOW_OPACITY")
_FE = _D.intern_atom("_NET_FRAME_EXTENTS")


def set_motif(xid, decorations):  # decorations: 1=all,0=none,2=border
    w = _D.create_resource_object("window", xid)
    w.change_property(_MWH, _MWH, 32, [2, 0, decorations, 0, 0]); _D.sync()


def set_opacity(xid, val):
    w = _D.create_resource_object("window", xid)
    w.change_property(_OPACITY, Xatom.CARDINAL, 32, [val]); _D.sync()


def del_opacity(xid):
    w = _D.create_resource_object("window", xid)
    w.delete_property(_OPACITY); _D.sync()


def frame_extents(xid):
    w = _D.create_resource_object("window", xid)
    p = w.get_full_property(_FE, 0)
    return list(p.value) if p else None


app = QApplication(sys.argv)
from main import MultiToonTool
win = MultiToonTool()  # builds with custom frameless chrome (use_system_title_bar defaults False)
xid = int(win.winId())
geom = (100, 100, 880, 862)
set_opacity(xid, 1)          # near-invisible stage
set_motif(xid, 1)            # force decorated
win.show()

state = {"t": 0}
def poll():
    state["t"] += 10
    fe = frame_extents(xid)
    if fe and any(fe):
        print(f"[spike] frame extents {fe} at ~{state['t']}ms -> stripping", flush=True)
        set_motif(xid, 0)                       # strip frame
        win.setGeometry(*geom)                  # reassert geometry
        del_opacity(xid)                        # reveal
        print("[spike] revealed borderless; LOOK NOW", flush=True)
        return
    if state["t"] >= 500:
        print("[spike] TIMEOUT waiting for frame extents", flush=True)
        return
    QTimer.singleShot(10, poll)
QTimer.singleShot(10, poll)

def _cleanup():
    tab = getattr(win, "multitoon_tab", None)
    svc = getattr(tab, "input_service", None)
    if svc is not None:
        try: svc.shutdown()
        except Exception: pass
app.aboutToQuit.connect(_cleanup)
sys.exit(app.exec())
