# tests/test_glass_dock.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_v2_nav_has_four_tabs_with_exact_hex():
    from utils.theme_manager import V2_NAV
    assert V2_NAV["multitoon"] == {"c": "#0077ff", "b": "#3399ff"}
    assert V2_NAV["launcher"] == {"c": "#E05252", "b": "#ea7a7a"}
    assert V2_NAV["keysets"] == {"c": "#DAA520", "b": "#e8c14d"}
    assert V2_NAV["settings"] == {"c": "#3da343", "b": "#56d66a"}
