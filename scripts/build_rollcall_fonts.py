"""Build the static fonts the Roll Call windows ship (assets/fonts/rollcall).

The installer runs before anything is installed, so it carries its own type:
Fredoka for headlines, Inter for the interface, JetBrains Mono for numbers and
paths. Each file is one weight cut from the upstream variable font, subset to
the Latin the windows use, and given a family name of its own so that no
platform's weight matching can pick the wrong file or synthesize a bold.

Usage (needs fonttools; the sources are the variable TTFs from
https://github.com/google/fonts, ofl/fredoka, ofl/inter, ofl/jetbrainsmono):

    python scripts/build_rollcall_fonts.py <dir with Fredoka.ttf Inter.ttf JetBrainsMono.ttf>
"""
from __future__ import annotations

import os
import sys

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "assets", "fonts", "rollcall")

# source file, axes, family name, file name, usWeightClass
CUTS = (
    ("Fredoka.ttf", {"wght": 700, "wdth": 100}, "Rollcall Fredoka Bold", "RollcallFredoka-Bold.ttf", 700),
    ("Inter.ttf", {"wght": 400, "opsz": 14}, "Rollcall Inter Regular", "RollcallInter-Regular.ttf", 400),
    ("Inter.ttf", {"wght": 500, "opsz": 14}, "Rollcall Inter Medium", "RollcallInter-Medium.ttf", 500),
    ("Inter.ttf", {"wght": 600, "opsz": 14}, "Rollcall Inter SemiBold", "RollcallInter-SemiBold.ttf", 600),
    ("Inter.ttf", {"wght": 700, "opsz": 14}, "Rollcall Inter Bold", "RollcallInter-Bold.ttf", 700),
    ("Inter.ttf", {"wght": 800, "opsz": 14}, "Rollcall Inter ExtraBold", "RollcallInter-ExtraBold.ttf", 800),
    ("JetBrainsMono.ttf", {"wght": 500}, "Rollcall Mono Medium", "RollcallMono-Medium.ttf", 500),
    ("JetBrainsMono.ttf", {"wght": 700}, "Rollcall Mono Bold", "RollcallMono-Bold.ttf", 700),
)

# Basic Latin, Latin-1, and the punctuation the copy uses: dashes, quotes,
# bullet, ellipsis, arrows, multiplication sign, middle dot.
UNICODES = (
    list(range(0x20, 0x7F)) + list(range(0xA0, 0x100))
    + [0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026,
       0x2190, 0x2192, 0x00D7, 0x00B7, 0x2212]
)


def _rename(font: TTFont, family: str, weight: int) -> None:
    name = font["name"]
    postscript = family.replace(" ", "")
    for record in list(name.names):
        if record.nameID in (1, 4, 16):
            name.setName(family, record.nameID, record.platformID,
                         record.platEncID, record.langID)
        elif record.nameID == 2:
            name.setName("Regular", 2, record.platformID, record.platEncID,
                         record.langID)
        elif record.nameID == 6:
            name.setName(postscript, 6, record.platformID, record.platEncID,
                         record.langID)
        elif record.nameID in (17, 21, 22, 25):
            name.removeNames(nameID=record.nameID)
    font["OS/2"].usWeightClass = weight
    # One upright "Regular" face per family: nothing left to synthesize from.
    font["OS/2"].fsSelection = (font["OS/2"].fsSelection & ~0x21) | 0x40
    font["head"].macStyle = 0


def build(source_dir: str) -> None:
    os.makedirs(OUT, exist_ok=True)
    for source, axes, family, filename, weight in CUTS:
        font = TTFont(os.path.join(source_dir, source))
        font = instancer.instantiateVariableFont(font, axes)
        for tag in ("STAT", "fvar", "avar", "gvar", "MVAR", "HVAR"):
            if tag in font:
                del font[tag]
        options = subset.Options()
        options.layout_features = ["kern", "liga", "calt", "tnum", "ccmp", "locl", "mark", "mkmk"]
        options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
        options.notdef_outline = True
        options.hinting = False
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=UNICODES)
        subsetter.subset(font)
        _rename(font, family, weight)
        out = os.path.join(OUT, filename)
        font.save(out)
        print(f"{filename}: {os.path.getsize(out)} bytes, family {family!r}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(sys.argv[1])
