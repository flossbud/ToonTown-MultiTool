import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_purple_accent_registered_with_exact_hex():
    from utils.theme_manager import V2_ACCENTS
    assert V2_ACCENTS["purple"] == {"c": "#8749E0", "b": "#a87cf0"}


def test_dark_tokens_exact_values():
    from utils.widgets.logs_console._tokens import get_logs_tokens
    t = get_logs_tokens(True)
    assert t["console_bg"] == "#101413"
    assert t["levels"] == {"info": "#c9cfd4", "ok": "#56d66a",
                           "warn": "#ffb04d", "error": "#ea7a7a"}
    assert t["tags"]["[Credentials]"] == "#4dd2c3"
    assert t["tags"]["[TTR API]"] == "#6ba8f0"
    assert t["tags"]["[Launch]"] == "#e8c14d"
    assert t["tag_fallback"] == "#9aa4ad"
    assert t["ts"] == "rgba(255, 255, 255, 77)"          # alpha(#ffffff, 0.30) — 76.5 rounds half-up
    assert t["search_focus"] == "#a87cf0"                 # bright b in dark
    assert t["dot"] == "#56d66a"


def test_light_tokens_remapped_ink():
    from utils.widgets.logs_console._tokens import get_logs_tokens
    t = get_logs_tokens(False)
    assert t["console_bg"] == "#f1f5f9"
    assert t["console_border"] == "#cbd5e1"
    assert t["levels"] == {"info": "#334155", "ok": "#15803d",
                           "warn": "#b45309", "error": "#b91c1c"}
    assert t["tags"]["[Credentials]"] == "#0f766e"
    assert t["tags"]["[Input]"] == "#2563eb"
    assert t["tag_fallback"] == "#64748b"
    assert t["search_focus"] == "#8749E0"                 # base c in light
    assert t["dot"] == "#3da343"


def test_both_themes_expose_the_same_keys():
    from utils.widgets.logs_console._tokens import get_logs_tokens
    dark = get_logs_tokens(True)
    light = get_logs_tokens(False)
    assert set(dark) == set(light)
    assert set(dark["tags"]) == set(light["tags"])
    assert set(dark["levels"]) == set(light["levels"])
