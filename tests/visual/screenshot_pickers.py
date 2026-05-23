"""Visual smoke check for the CC install + CC compat picker dialogs.

Run from the project root:

    QT_QPA_PLATFORM=offscreen python -m tests.visual.screenshot_pickers

Produces 4 PNGs under tests/visual/_screenshots/ — one per
(picker, theme) combination. Eyeball them against the mockup at
.superpowers/brainstorm/*/content/picker-style-b-real.html.

Not collected by pytest (filename does not start with `test_`).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from services.steam_proton_tools import ProtonTool  # noqa: E402
from services.wine_runtimes import WineInstall, install_signature  # noqa: E402
from utils import theme_manager  # noqa: E402
from utils.widgets.cc_compat_picker import CCCompatPickerDialog  # noqa: E402
from utils.widgets.cc_install_picker import CCInstallPickerDialog  # noqa: E402


OUT_DIR = Path(__file__).parent / "_screenshots"


def _materialize_stub(root: Path, rel: str) -> str:
    """Create an empty stub file at `root/rel` and return its absolute path.

    The install picker filters out cards whose exe_path does not exist on disk
    (cc_install_picker.CCInstallPickerDialog.__init__) so the harness needs
    real files behind every synthetic install or only the active one renders.
    """
    full = root / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.touch()
    return str(full)


def _synthetic_installs(stub_root: Path) -> list[WineInstall]:
    bottles_prefix = stub_root / "bottles/Corporate-Clash"
    steam_prefix = stub_root / "Steam/steamapps/compatdata/2696034361/pfx"
    lutris_prefix = stub_root / "Games/lutris/corporate-clash"
    return [
        WineInstall(
            exe_path=_materialize_stub(
                stub_root,
                "bottles/Corporate-Clash/drive_c/users/steamuser/AppData/Local/"
                "Corporate Clash/CorporateClash.exe",
            ),
            launcher="bottles",
            prefix_path=str(bottles_prefix),
            display_name="Bottles · Corporate Clash",
            metadata={
                "bottle_name": "Corporate-Clash",
                "bottle_display_name": "Corporate Clash",
                "distribution": "native",
            },
        ),
        WineInstall(
            exe_path=_materialize_stub(
                stub_root,
                "Steam/steamapps/compatdata/2696034361/pfx/drive_c/users/steamuser/"
                "AppData/Local/Corporate Clash/CorporateClash.exe",
            ),
            launcher="steam-proton",
            prefix_path=str(steam_prefix),
            display_name="Steam · Toontown Corporate Clash",
            metadata={
                "appid": "2696034361",
                "steam_root": str(stub_root / "Steam"),
                "proton_dir": str(
                    stub_root / "Steam/compatibilitytools.d/GE-Proton10-34"
                ),
            },
        ),
        WineInstall(
            exe_path=_materialize_stub(
                stub_root,
                "Games/lutris/corporate-clash/drive_c/Program Files/"
                "Corporate Clash/CorporateClash.exe",
            ),
            launcher="lutris",
            prefix_path=str(lutris_prefix),
            display_name="Lutris · corporate-clash",
            metadata={"lutris_slug": "corporate-clash", "lutris_name": "Corporate Clash"},
        ),
    ]


def _synthetic_protons() -> list[ProtonTool]:
    steam_root = "/home/demo/.local/share/Steam"
    return [
        ProtonTool(
            name="GE-Proton10-34",
            display_name="GE-Proton10-34",
            nickname="GE-Proton 10-34",
            proton_dir=f"{steam_root}/compatibilitytools.d/GE-Proton10-34",
            source="compatibilitytools.d",
            steam_root=steam_root,
            version_key=(10, 34),
        ),
        ProtonTool(
            name="proton_experimental",
            display_name="Proton Experimental",
            nickname="Proton Experimental",
            proton_dir=f"{steam_root}/steamapps/common/Proton - Experimental",
            source="official",
            steam_root=steam_root,
            version_key=(11, 0),
        ),
        ProtonTool(
            name="proton-cachyos",
            display_name="proton-cachyos-10.0-20260424-slr-x86_64",
            nickname="Proton-CachyOS 10.0",
            proton_dir=f"{steam_root}/compatibilitytools.d/proton-cachyos-10.0",
            source="compatibilitytools.d",
            steam_root=steam_root,
            version_key=(10, 0),
        ),
    ]


def _grab(dialog, path: Path) -> None:
    dialog.show()
    QApplication.processEvents()
    dialog.repaint()
    QApplication.processEvents()
    pix = dialog.grab()
    path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(path))
    print(f"  wrote {path}")
    dialog.close()


def _shoot_one(theme_name: str, theme_qss: str, stub_root: Path) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme_qss)

    installs = _synthetic_installs(stub_root)
    active_sig = install_signature(installs[0])
    install_dlg = CCInstallPickerDialog(installs, active_signature=active_sig)
    install_dlg.select_index(1)
    _grab(install_dlg, OUT_DIR / f"picker-install-{theme_name}.png")

    tools = _synthetic_protons()
    compat_dlg = CCCompatPickerDialog(
        tools=tools,
        current_override=tools[0].proton_dir,
        steam_default_display="GE-Proton 10-34",
    )
    _grab(compat_dlg, OUT_DIR / f"picker-compat-{theme_name}.png")


def main() -> int:
    QApplication.instance() or QApplication(sys.argv)
    print("Generating picker screenshots...")
    with tempfile.TemporaryDirectory(prefix="ttmt-picker-shots-") as tmp:
        stub_root = Path(tmp)
        _shoot_one("dark", theme_manager.DARK_THEME, stub_root)
        _shoot_one("light", theme_manager.LIGHT_THEME, stub_root)
    print(f"\nDone. Output dir: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
