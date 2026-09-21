"""Widget-owned animations must die with their widget, on the GUI thread.

Live SIGSEGV (core dump: QUnifiedTimer::updateAnimationTimers ->
QAnimationDriver::advanceAnimation, no Python frame on the main thread).
PulsingDot's QVariantAnimation had no QObject parent, so its C++ object
belonged to the Python wrapper. CardShelf.set_entries tears every card down
with setParent(None) + deleteLater(); the card wrapper sits in a reference
cycle, so the card -> dot -> animation wrapper chain is only released by
Python's cyclic GC, which runs on whichever thread trips the allocation
threshold. When that is a worker thread, ~QAbstractAnimation looks up the
(thread-local) animation timer, finds none, and leaves a dangling pointer
in the GUI thread's list; the next driver tick dereferences freed memory.

With the animation parented to the widget, Qt destroys it inside the
widget's own destructor on the GUI thread, where it deregisters before its
memory is freed, and the Python wrapper can never delete it.

A segfault kills the interpreter, so each case runs in a subprocess and the
test asserts on the exit code (-11 is SIGSEGV). The worker-thread gc is the
load-bearing ingredient: the same sequence with gc.collect() on the main
thread survives even on the unparented code, because Qt then deregisters
correctly. Do not "simplify" it away.

Modes (which ones die on the unparented code, verified by mutation):
  detach  -- setParent(None) + deleteLater(), the CardShelf path. A hide
             event reaches the children, so PulsingDot's hide gate stops the
             pulse before the deferred delete runs. Survives even unparented;
             it checks the gate, not the parenting.
  delete  -- deleteLater() only: no hide event, still running at destructor
             time. PulsingDot dies unparented (SIGSEGV); this is the proof.
             Switch / IOSSegmentedControl survive even unparented because Qt
             stops a QPropertyAnimation synchronously when its target (the
             same widget) dies -- kept as a teardown smoke check only.
  release -- ownership check with a synthetic trigger: the widget stays
             alive and animating, only the animation's Python wrapper is
             dropped, on a worker thread. Python-owned: the C++ animation is
             deleted off-thread while registered -> SIGSEGV for all three
             widgets. Widget-owned: the wrapper is just a handle and nothing
             is deleted.
"""
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = r'''
import gc, sys, threading
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QWidget

WIDGET, MODE = sys.argv[1], sys.argv[2]

app = QApplication(sys.argv[:1])
app.setQuitOnLastWindowClosed(False)

strip = QWidget()        # stays alive, like CardShelf._strip
card = QWidget(strip)    # what set_entries tears down

if WIDGET == "PulsingDot":
    from utils.shared_widgets import PulsingDot
    w = PulsingDot(6, card)
    w.set_color("#56c856", pulse=True)
elif WIDGET == "Switch":
    import utils.motion as motion
    motion.is_reduced = lambda: False
    from utils.shared_widgets import Switch
    w = Switch(False, card)
    w._anim.setDuration(5000)   # hold the 160 ms hazard window open across the teardown
    w.setChecked(True)
elif WIDGET == "IOSSegmentedControl":
    from utils.shared_widgets import IOSSegmentedControl
    w = IOSSegmentedControl(["a", "b"], card)
    # Nothing in production starts this animation; start it the way Qt
    # would so the ownership hazard is identical.
    w._anim.setDuration(5000)
    w._anim.setStartValue(0.0)
    w._anim.setEndValue(50.0)
    w._anim.start()
else:
    raise SystemExit("unknown widget " + WIDGET)

strip.show()
for _ in range(20):
    app.processEvents()      # animation registered with the unified timer and ticking
assert w._anim.state() == QAbstractAnimation.State.Running, w._anim.state()
print("owner:", type(w._anim.parent()).__name__, file=sys.stderr)

w._cycle = w     # the real RosterCard wrapper sits in a cycle: only the cyclic GC frees it
live = {"card": card, "w": w}
del w, card
gc.disable()     # keep the GUI thread from collecting it first


def on_worker(fn):
    t = threading.Thread(target=fn, name="worker")
    t.start()
    t.join()


def teardown():
    # Everything below runs inside one slot, with no driver tick in between:
    # the widget is torn down and deleted on the GUI thread, then the cyclic
    # GC runs on a worker thread -- as in the app whenever a worker trips
    # it. Back-to-back on purpose so a tick cannot intervene.
    card = live.pop("card")
    if MODE == "detach":
        card.setParent(None)
    card.deleteLater()
    del card
    live.clear()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    on_worker(gc.collect)
    print("worker gc done", file=sys.stderr)


def release():
    # Widget alive and animating; only the animation's wrapper goes, on a
    # worker thread. With Python ownership that is a C++ delete off-thread.
    holder = [live["w"].__dict__.pop("_anim")]
    def drop():
        del holder[:]
    on_worker(drop)
    print("worker release done", file=sys.stderr)


QTimer.singleShot(200, release if MODE == "release" else teardown)
QTimer.singleShot(1200, app.quit)   # several driver ticks after the free
app.exec()
print("survived", file=sys.stderr)
sys.exit(0)
'''

CASES = [
    ("PulsingDot", "detach"),
    ("PulsingDot", "delete"),
    ("PulsingDot", "release"),
    ("Switch", "delete"),
    ("Switch", "release"),
    ("IOSSegmentedControl", "delete"),
    ("IOSSegmentedControl", "release"),
]


@pytest.mark.parametrize("widget,mode", CASES, ids=[f"{w}-{m}" for w, m in CASES])
def test_animation_owned_by_widget_survives_teardown(widget, mode):
    env = dict(
        os.environ,
        QT_QPA_PLATFORM="offscreen",
        TTMT_NO_VENV_REEXEC="1",
        PYTHONPATH=REPO_ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""),
    )
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT, widget, mode],
        cwd=REPO_ROOT, env=env, timeout=60,
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"{widget}/{mode}: subprocess exited {proc.returncode} "
        f"(-11 is SIGSEGV)\n--- stderr ---\n{proc.stderr}"
    )
    assert "survived" in proc.stderr, proc.stderr
