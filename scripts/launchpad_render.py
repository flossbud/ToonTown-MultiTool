"""Render the launchpad sheet parts offscreen and save PNGs.

A construction check: the real SlideSheetHost mounted in an 880 x 860
stand-in window (a 112 px header and a patterned content area, so the scrim's
blur and dim show), under the app's real stylesheet, in each theme.

    python scripts/launchpad_render.py OUTDIR [--theme dark|light|both]
                                              [--sheets material,keysets]

Writes <sheet>-<theme>.png per sheet, to set beside
docs/design/next-ui/window-renders/.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt                                # noqa: E402
from PySide6.QtGui import QColor, QPainter                          # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget    # noqa: E402

WINDOW_W, WINDOW_H = 880, 860


class StandInWindow(QWidget):
    """Header band + a striped content area standing in for the launcher."""

    def __init__(self, is_dark: bool):
        super().__init__()
        self.is_dark = is_dark
        self.resize(WINDOW_W, WINDOW_H)

    def paintEvent(self, _e):
        p = QPainter(self)
        bg = QColor("#1a1a1a" if self.is_dark else "#f8fafc")
        p.fillRect(self.rect(), bg)
        p.fillRect(QRect(0, 0, self.width(), 112),
                   QColor("#111111" if self.is_dark else "#e8ecf1"))
        stripe = [QColor("#2a4f8a"), QColor("#c0803a")] if self.is_dark else \
            [QColor("#9cc0f0"), QColor("#f2c38c")]
        for i, x in enumerate(range(0, self.width(), 60)):
            p.fillRect(QRect(x, 140, 40, 300), stripe[i % 2])
        p.end()


def material_demo(is_dark: bool) -> QWidget:
    from utils.icon_factory import (
        make_dpad_icon, make_edit_icon, make_eye_icon, make_trash_icon,
    )
    from utils.widgets.launchpad import material as m
    white = QColor("#ffffff")
    page = QWidget()
    lay = m.sheet_stack(page)
    card = m.GroupCard("#1fb8a6", "Float strips", make_dpad_icon(15, white),
                       is_dark=is_dark)
    card.add_meta_widget(m.SheetSegmented(["TTR", "CC"], "#1fb8a6", is_dark=is_dark))
    r1 = m.SheetRow("Strip style", "Neon glows; Flat is quieter.", is_dark=is_dark)
    r1.set_control(m.SheetSegmented(["Neon", "Flat"], "#1fb8a6", is_dark=is_dark))
    card.add_row(r1)
    r2 = m.SheetRow("Hide this window once toons are up",
                    "Bring it back from the home block or the tray icon.",
                    is_dark=is_dark)
    r2.set_control(m.SheetToggle(True, "#1fb8a6", is_dark=is_dark))
    card.add_row(r2)
    r3 = m.SheetRow("Tray icon", "Keeps MultiTool reachable when every strip is covered.",
                    is_dark=is_dark)
    r3.set_control(m.SheetToggle(False, "#1fb8a6", is_dark=is_dark))
    card.add_row(r3)
    r4 = m.SheetRow("Icon buttons", "Edit, hide, delete (disabled)", is_dark=is_dark)
    grey = QColor("#bbbbbb" if is_dark else "#334155")
    r4.add_control(m.IconButton(make_edit_icon(14, grey), "Edit", is_dark=is_dark))
    r4.add_control(m.IconButton(make_eye_icon(14, grey), "Hide", is_dark=is_dark))
    dis = m.IconButton(make_trash_icon(14, grey), "Delete", danger=True, is_dark=is_dark)
    dis.setEnabled(False)
    r4.add_control(dis)
    card.add_row(r4)
    card.add_row(m.AddRow("+ New keyset", is_dark=is_dark))
    lay.addWidget(card)
    plain = m.PlainCard(is_dark=is_dark)
    plain.add_row(m.SheetRow("Plain card row", "Neutral actions live here.",
                             is_dark=is_dark))
    lay.addWidget(plain)
    lay.addWidget(m.footer_label("Footer hint, centred, text-disabled.", is_dark))
    return page


def demo_keymap_manager():
    """A KeymapManager on a throwaway config dir: four TTR sets like the
    prototype (one hidden, one with a cross-set clash), two CC sets."""
    import tempfile
    from utils.keymap_manager import KeymapManager
    cfg = tempfile.mkdtemp(prefix="launchpad-render-")
    old = os.environ.get("TTMT_CONFIG_DIR")
    os.environ["TTMT_CONFIG_DIR"] = cfg
    try:
        km = KeymapManager()
    finally:
        if old is None:
            os.environ.pop("TTMT_CONFIG_DIR", None)
        else:
            os.environ["TTMT_CONFIG_DIR"] = old
    km.add_set("ttr", keys={"forward": "w", "left": "a", "reverse": "s",
                            "right": "d", "jump": "space"})
    km.add_set("ttr", keys={"forward": "i", "left": "j", "reverse": "k",
                            "right": "l", "jump": "Control_R"})
    four = km.add_set("ttr", keys={"forward": "KP_8", "left": "KP_4", "reverse": "KP_5",
                                   "right": "KP_6", "jump": "KP_0"})
    km.set_hidden("ttr", four, True)
    km.update_set_key("ttr", 2, "gags", "w")          # w: Forward in 2, Gags in 3
    km.add_set("cc", keys={"forward": "Up", "left": "Left", "reverse": "Down",
                           "right": "Right", "jump": "Control_R"})
    return km


def keysets_demo(is_dark: bool) -> QWidget:
    from utils.widgets.launchpad.keysets_sheet import KeysetsSheet
    return KeysetsSheet(demo_keymap_manager(), is_dark=is_dark,
                        default_locked=lambda game: False)


class _DemoSettings:
    def __init__(self, is_dark):
        self.d = {"theme": "dark" if is_dark else "light"}
        self.cbs = []

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v

    def on_change(self, cb):
        self.cbs.append(cb)


def settings_demo(is_dark: bool, tab: str = "settings") -> QWidget:
    from utils.widgets.launchpad.settings_sheet import SettingsSheet
    sheet = SettingsSheet(_DemoSettings(is_dark), is_dark=is_dark)
    sheet.set_tab(tab)
    return sheet


SHEETS = {
    "material": ("#1fb8a6", "Sheet material", "Group card, rows, toggles, pills",
                 material_demo),
    "keysets": ("#DAA520", "Keysets",
                "Numbered movement-key layouts. Each toon picks one from its strip.",
                keysets_demo),
    "settings": ("#3da343", "Settings", "App-wide preferences", settings_demo),
    "about": ("#3da343", "Settings", "ToonTown MultiTool",
              lambda d: settings_demo(d, "about")),
}


def render(outdir: str, themes, sheets) -> list[str]:
    import utils.motion as motion
    from utils import theme_manager
    from utils.widgets.launchpad.slide_sheet import SlideSheetHost
    app = QApplication.instance() or QApplication([])
    motion.is_reduced = lambda: True          # final state, no slide in progress
    os.makedirs(outdir, exist_ok=True)
    written = []
    for theme in themes:
        theme_manager.apply_theme(app, theme)
        is_dark = theme == "dark"
        for name in sheets:
            if name not in SHEETS:
                continue
            color, title, sub, build = SHEETS[name]
            win = StandInWindow(is_dark)
            host = SlideSheetHost(win, is_dark=is_dark)
            content = build(is_dark)
            host.open(content, color, title, sub)
            if name == "keysets":
                content.expand_index(1)
            app.processEvents()
            path = os.path.join(outdir, f"{name}-{theme}.png")
            win.grab().save(path)
            written.append(path)
            win.deleteLater()
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir")
    ap.add_argument("--theme", default="both", choices=("dark", "light", "both"))
    ap.add_argument("--sheets", default="material,keysets,settings,about")
    a = ap.parse_args()
    th = ("dark", "light") if a.theme == "both" else (a.theme,)
    for p in render(a.outdir, th, [s.strip() for s in a.sheets.split(",")]):
        print(p)
