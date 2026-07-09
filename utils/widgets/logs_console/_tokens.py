"""Color/metric tokens for the Logs V2 console. Exact ports of the logs
redesign bundle (dark) and the approved light derivation (near-white console,
remapped ink). Same shape convention as theme_manager.get_v2_tokens: rgba
strings carry 0-255 alpha (this codebase's QSS convention)."""
from __future__ import annotations

from utils.color_math import alpha

# Tag colors — routing tags, bundle §Color System.
TAG_COLORS_DARK = {
    "[Credentials]": "#4dd2c3", "[CCLauncher]": "#ff8f4d",
    "[Input]": "#6ba8f0", "[Service]": "#6ba8f0", "[TTR API]": "#6ba8f0",
    "[KeepAlive]": "#ffb04d", "[Hotkey]": "#d4548a",
    "[Profile]": "#56d66a", "[Launch]": "#e8c14d",
}
TAG_COLORS_LIGHT = {
    "[Credentials]": "#0f766e", "[CCLauncher]": "#c2410c",
    "[Input]": "#2563eb", "[Service]": "#2563eb", "[TTR API]": "#2563eb",
    "[KeepAlive]": "#b45309", "[Hotkey]": "#be185d",
    "[Profile]": "#15803d", "[Launch]": "#a16207",
}


def get_logs_tokens(is_dark: bool) -> dict:
    """Theme-dependent token set for the Logs V2 console widgets."""
    if is_dark:
        return {
            "console_bg": "#101413", "console_border": alpha("#000000", 0.45),
            "inset_shadow": alpha("#000000", 0.45),
            "ts": alpha("#ffffff", 0.30),
            "hover_row": alpha("#ffffff", 0.05),
            "copy_glyph": alpha("#ffffff", 0.45), "copied": "#56d66a",
            "empty": alpha("#ffffff", 0.40),
            "levels": {"info": "#c9cfd4", "ok": "#56d66a",
                       "warn": "#ffb04d", "error": "#ea7a7a"},
            "tags": dict(TAG_COLORS_DARK), "tag_fallback": "#9aa4ad",
            "chip_idle_bg": alpha("#000000", 0.24),
            "chip_idle_border": alpha("#ffffff", 0.10),
            "chip_idle_text": alpha("#ffffff", 0.55),
            "chip_active_text": "#ffffff", "chip_active_bg_alpha": 0.22,
            "search_bg": alpha("#000000", 0.35),
            "search_border": alpha("#ffffff", 0.14),
            "search_text": "#ffffff",
            "search_placeholder": alpha("#ffffff", 0.35),
            "search_focus": "#a87cf0",
            "status_text": alpha("#ffffff", 0.62),
            "dot": "#56d66a", "dot_glow_alpha": 0.7,
            "toast_bg": alpha("#000000", 0.72),
            "toast_border": alpha("#ffffff", 0.16),
        }
    return {
        "console_bg": "#f1f5f9", "console_border": "#cbd5e1",
        "inset_shadow": alpha("#0f172a", 0.08),
        "ts": alpha("#0f172a", 0.38),
        "hover_row": alpha("#0f172a", 0.05),
        "copy_glyph": alpha("#0f172a", 0.45), "copied": "#15803d",
        "empty": alpha("#0f172a", 0.45),
        "levels": {"info": "#334155", "ok": "#15803d",
                   "warn": "#b45309", "error": "#b91c1c"},
        "tags": dict(TAG_COLORS_LIGHT), "tag_fallback": "#64748b",
        "chip_idle_bg": alpha("#0f172a", 0.05),
        "chip_idle_border": alpha("#0f172a", 0.10),
        "chip_idle_text": "#475569",
        "chip_active_text": "#0f172a", "chip_active_bg_alpha": 0.16,
        "search_bg": alpha("#0f172a", 0.05),
        "search_border": alpha("#0f172a", 0.14),
        "search_text": "#0f172a",
        "search_placeholder": alpha("#0f172a", 0.40),
        "search_focus": "#8749E0",
        "status_text": alpha("#0f172a", 0.55),
        "dot": "#3da343", "dot_glow_alpha": 0.5,
        # Toast stays dark in BOTH themes (spec §4).
        "toast_bg": alpha("#000000", 0.72),
        "toast_border": alpha("#ffffff", 0.16),
    }
