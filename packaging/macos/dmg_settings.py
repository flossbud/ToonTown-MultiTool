"""dmgbuild settings - classic drag-to-Applications layout.

Driven by env so the same file serves stable and beta:
  TTMT_DMG_APP      path to the .app to ship (required)
  TTMT_DMG_VOLNAME  mounted volume name (default "ToonTown MultiTool")
  TTMT_DMG_BG       optional background image path
"""
import os

app = os.environ["TTMT_DMG_APP"]
appname = os.path.basename(app)

volume_name = os.environ.get("TTMT_DMG_VOLNAME", "ToonTown MultiTool")
format = "UDZO"            # compressed
files = [app]
symlinks = {"Applications": "/Applications"}
icon_locations = {appname: (140, 160), "Applications": (400, 160)}
window_rect = ((200, 200), (540, 360))
default_view = "icon-view"
icon_size = 96
_bg = os.environ.get("TTMT_DMG_BG")
if _bg and os.path.exists(_bg):
    background = _bg
