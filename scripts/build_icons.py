"""Regenerate derived icon assets from assets/multitool.png.

Run manually (`python scripts/build_icons.py`) whenever the canonical source
changes. Outputs are committed alongside the source change in the same commit.
ImageMagick (`magick`) is required for the .ico step only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPixmap,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "assets" / "multitool.png"
CANONICAL_SIZE = 512

PNG_OUTPUTS = [
    REPO_ROOT / "flatpak" / "icon-512.png",
    REPO_ROOT / "AppDir" / "io.github.flossbud.ToonTownMultiTool.png",
    REPO_ROOT / "AppDir" / ".DirIcon",
]
# Intermediate sizes for the Flatpak hicolor theme. Plasma 6 / kickoff /
# task manager pick from these instead of downscaling the 512 every time,
# which is what broke the icon on KDE Plasma Wayland Flatpak installs.
FLATPAK_SIZES = (48, 64, 128, 256)
FLATPAK_SIZE_OUTPUTS = [
    (size, REPO_ROOT / "flatpak" / f"icon-{size}.png") for size in FLATPAK_SIZES
]
BETA_OUTPUT = REPO_ROOT / "assets" / "ToonTownMultiTool-beta.png"
ICO_OUTPUT = REPO_ROOT / "assets" / "ToonTownMultiTool.ico"
ICNS_OUTPUT = REPO_ROOT / "assets" / "ToonTownMultiTool.icns"

# Standard Apple .iconset slots as (filename, pixel size). The canonical source
# is 512x512, so the 512x512@2x (1024) slot is intentionally omitted rather than
# upscaled: a baked-in blurry 1024 is worse than letting macOS scale the crisp
# 512 on demand. Add the 1024 slot here only once a >=1024 master exists.
ICONSET_SLOTS = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
)


def _load_source() -> QPixmap:
    if not SOURCE.exists():
        print(f"error: source not found: {SOURCE}", file=sys.stderr)
        sys.exit(1)
    pix = QPixmap(str(SOURCE))
    if pix.isNull():
        print(f"error: could not load source as image: {SOURCE}", file=sys.stderr)
        sys.exit(1)
    if pix.width() != pix.height():
        print(
            f"warning: source is not square ({pix.width()}x{pix.height()}); "
            "scaling to 512x512 will distort proportions",
            file=sys.stderr,
        )
    if pix.size().width() != CANONICAL_SIZE:
        pix = pix.scaled(
            CANONICAL_SIZE,
            CANONICAL_SIZE,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
    return pix


def _write_stable_pngs(source: QPixmap) -> None:
    for dest in PNG_OUTPUTS:
        dest.parent.mkdir(parents=True, exist_ok=True)
        ok = source.save(str(dest), "PNG")
        if not ok:
            print(f"error: failed to write {dest}", file=sys.stderr)
            sys.exit(1)
        print(f"  wrote {dest.relative_to(REPO_ROOT)}")


def _write_flatpak_size_pngs(source: QPixmap) -> None:
    for size, dest in FLATPAK_SIZE_OUTPUTS:
        scaled = source.scaled(
            size,
            size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        ok = scaled.save(str(dest), "PNG")
        if not ok:
            print(f"error: failed to write {dest}", file=sys.stderr)
            sys.exit(1)
        print(f"  wrote {dest.relative_to(REPO_ROOT)}")


def _write_beta_png(source: QPixmap) -> None:
    canvas = QPixmap(source.size())
    canvas.fill(Qt.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawPixmap(0, 0, source)

    # Clip to the icon's circle so the ribbon doesn't bleed outside the disk
    clip = QPainterPath()
    clip.addEllipse(0, 0, source.width(), source.height())
    painter.setClipPath(clip)

    # Anchor the ribbon center in the top-right quadrant
    painter.save()
    painter.translate(source.width() * 0.78, source.height() * 0.20)
    painter.rotate(35)

    ribbon_w = source.width() * 0.70
    ribbon_h = source.height() * 0.13
    ribbon_rect = QRectF(-ribbon_w / 2, -ribbon_h / 2, ribbon_w, ribbon_h)
    painter.fillRect(ribbon_rect, QColor("#e94d8a"))

    font = QFont("DejaVu Sans", int(ribbon_h * 0.55), QFont.Bold)
    font.setFamilies(["DejaVu Sans", "Liberation Sans", "Arial", "sans-serif"])
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(ribbon_rect, Qt.AlignCenter, "BETA")

    painter.restore()
    painter.end()

    BETA_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ok = canvas.save(str(BETA_OUTPUT), "PNG")
    if not ok:
        print(f"error: failed to write {BETA_OUTPUT}", file=sys.stderr)
        sys.exit(1)
    print(f"  wrote {BETA_OUTPUT.relative_to(REPO_ROOT)}")


def _write_ico() -> None:
    # magick (.ico) and iconutil (.icns) are each single-platform tools, and a
    # given machine rarely has both. Skip-with-note rather than hard-fail so the
    # script always finishes the cross-platform PNG set and emits whatever
    # platform-specific icon the current host can; regenerate the missing format
    # on a host that has its tool when the source changes.
    if shutil.which("magick") is None:
        print(
            "note: 'magick' (ImageMagick) not on PATH -- skipping .ico generation.\n"
            "  install: pacman -S imagemagick  (or apt install imagemagick), "
            "then re-run to refresh the .ico.",
            file=sys.stderr,
        )
        return
    cmd = [
        "magick",
        str(SOURCE),
        "-define",
        "icon:auto-resize=256,128,64,48,32,16",
        str(ICO_OUTPUT),
    ]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"error: magick failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(1)
    print(f"  wrote {ICO_OUTPUT.relative_to(REPO_ROOT)}")


def _write_icns(source: QPixmap) -> None:
    """Build the macOS .icns from the canonical source via iconutil.

    iconutil is the macOS-canonical packer (part of the Xcode command line
    tools) and is macOS-only; on other platforms this step is skipped with a
    note so a Linux dev regenerating the PNG/.ico set is not blocked. The
    iconset PNGs are produced with the same QPixmap smooth downscale as the
    other outputs.
    """
    if shutil.which("iconutil") is None:
        print(
            "note: 'iconutil' not on PATH (macOS only) -- skipping .icns "
            "generation. Regenerate the .icns on macOS when the source changes.",
            file=sys.stderr,
        )
        return
    with tempfile.TemporaryDirectory(suffix=".iconset") as tmp:
        iconset = Path(tmp)
        for name, size in ICONSET_SLOTS:
            scaled = source.scaled(
                size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            if not scaled.save(str(iconset / name), "PNG"):
                print(f"error: failed to write iconset slot {name}", file=sys.stderr)
                sys.exit(1)
        cmd = ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS_OUTPUT)]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(f"error: iconutil failed (exit {result.returncode})", file=sys.stderr)
            sys.exit(1)
    print(f"  wrote {ICNS_OUTPUT.relative_to(REPO_ROOT)}")


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841

    print(f"building icons from {SOURCE.relative_to(REPO_ROOT)}")
    source = _load_source()
    _write_stable_pngs(source)
    _write_flatpak_size_pngs(source)
    _write_beta_png(source)
    _write_ico()
    _write_icns(source)
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
