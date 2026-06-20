# scripts/peek_dim_spike.py
"""Throwaway spike: validate dim-body-75% + controls-100% + fade on a live card.

Run on a real X11 session (NOT offscreen):
  TTMT_NO_VENV_REEXEC=1 ./venv/bin/python scripts/peek_dim_spike.py
Toggle peek with the SPACE key; watch the colorful background show through the
card body while the controls stay crisp. Esc quits.
"""
import os, sys
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtCore import Qt, QVariantAnimation, QRect
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


def main():
    app = QApplication(sys.argv)

    # A bright background window standing in for the game behind the card.
    bg = QWidget(); bg.setWindowTitle("BACKGROUND (game stand-in)")
    bg.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                     "stop:0 #2e8b57, stop:1 #ffd36e);")
    bg.setGeometry(300, 300, 700, 500); bg.show()

    # Build a real card via the tab, host it in a CardSurface over the bg.
    import tabs.launch_tab
    tabs.launch_tab.discover_cc_installs = lambda *a, **k: []
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    from PySide6.QtCore import QObject, Signal

    class WM(QObject):
        window_ids_updated = Signal(list); cell_assignment_changed = Signal(list)
        window_geometry_updated = Signal(); active_window_changed = Signal(str)
        def __init__(self): super().__init__(); self.ttr_window_ids=[]; self.slot_cells=[0,1,2,3]
        def get_window_ids(self): return []
        def get_active_window(self): return None
        def clear_window_ids(self): pass
        def assign_windows(self): pass
        def enable_detection(self): pass
        def disable_detection(self): pass
        def count_for_game(self, g): return 0
        def get_window_geometry(self, wid): return None

    tab = MultitoonTab(settings_manager=SettingsManager(), window_manager=WM())
    compact = tab._compact
    tab._stack.setCurrentWidget(compact); tab.show()
    for _ in range(8): app.processEvents()

    from utils.overlay.surface import CardSurface
    card = compact._cells[0]["cell"]
    base = (card.sizeHint().width(), card.sizeHint().height())
    rects = compact.control_rects(0)

    surface = CardSurface(surface_id=0)
    surface.host(card, base_size=base)
    surface.setGeometry(400, 380, base[0], base[1])
    surface.prepare_initial_state(); surface.show()

    view = surface._scaled_view  # ScaledCardView

    # ---- CANDIDATE MECHANISM A (recommended): proxy opacity + control overlay ----
    overlay_item = {"item": None}

    def apply(body_opacity):
        view._proxy.setOpacity(body_opacity)
        if body_opacity >= 0.999:
            if overlay_item["item"] is not None:
                view._scene.removeItem(overlay_item["item"]); overlay_item["item"] = None
            return
        full = card.grab()
        dpr = int(full.devicePixelRatio()) or 1
        ov = QPixmap(full.size()); ov.setDevicePixelRatio(full.devicePixelRatio())
        ov.fill(Qt.transparent)
        p = QPainter(ov)
        for r in rects:
            p.drawPixmap(r, full, QRect(r.x()*dpr, r.y()*dpr, r.width()*dpr, r.height()*dpr))
        p.end()
        if overlay_item["item"] is None:
            overlay_item["item"] = view._scene.addPixmap(ov)
            overlay_item["item"].setZValue(100)
        else:
            overlay_item["item"].setPixmap(ov)
        overlay_item["item"].setPos(0, 0)

    state = {"peek": False, "anim": None}

    def toggle():
        target = 0.75 if not state["peek"] else 1.0
        state["peek"] = not state["peek"]
        anim = QVariantAnimation(); anim.setStartValue(view._proxy.opacity())
        anim.setEndValue(target); anim.setDuration(120)
        anim.valueChanged.connect(lambda v: apply(float(v)))
        anim.start(); state["anim"] = anim

    class Keys(QWidget):
        def keyPressEvent(self, e):
            if e.key() == Qt.Key_Space: toggle()
            elif e.key() == Qt.Key_Escape: app.quit()
    keys = Keys(); keys.setGeometry(300, 250, 200, 40); keys.show(); keys.setFocus()
    print("SPACE = toggle peek, ESC = quit. Watch the card body vs the controls.")
    app.exec()
    # Cleanup: never leak the InputService non-daemon thread.
    svc = getattr(tab, "input_service", None)
    if svc is not None:
        try: svc.shutdown()
        except Exception: pass


if __name__ == "__main__":
    main()
