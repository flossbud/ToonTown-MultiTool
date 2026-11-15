"""Colors shared by the small modal dialogs (account editor, confirm, launch
error, elevation prompt).

The app stylesheet paints every QWidget with the theme background, so a
modal's surface always follows the theme. These dialogs used to hardcode
their text for dark, which left white text on a near-white surface in light
mode. Each dialog now asks for its colors here and sets its own surface to
match, so text and surface can never come from different themes.
"""
from __future__ import annotations

from utils.theme_manager import get_theme_colors

# Applied by each dialog to its header/body frames so the flat dialog surface
# shows through instead of the app theme's per-widget background.
SECTION_OBJECT_NAME = "modal_section"


def modal_colors(is_dark: bool) -> dict:
    c = get_theme_colors(is_dark)
    if is_dark:
        return {
            "bg": c["bg_app"],
            "title": "#fff", "body": "#cfd6e6", "muted": "#8a9bb8",
            "input_bg": "rgba(255,255,255,0.04)",
            "input_border": "rgba(255,255,255,0.1)", "input_text": "#fff",
            "error": "#ff7575",
            "detail_bg": "rgba(0,0,0,0.3)", "detail_text": "#ffaaaa",
            "cancel_border": "rgba(255,255,255,0.15)", "cancel_text": "#cfd6e6",
            "save_bg": "#0077ff", "save_text": "white",
            "danger_bg": "#b34848", "danger_text": "white",
        }
    return {
        "bg": c["bg_app"],
        "title": c["text_primary"], "body": c["text_secondary"],
        "muted": c["text_muted"],
        "input_bg": c["bg_input"],
        "input_border": c["border_input"], "input_text": c["text_primary"],
        "error": c["accent_red"],
        "detail_bg": c["bg_card_inner"], "detail_text": c["accent_red"],
        "cancel_border": c["border_input"], "cancel_text": c["text_secondary"],
        "save_bg": c["accent_blue_btn"], "save_text": c["text_on_accent"],
        "danger_bg": c["accent_red"], "danger_text": c["text_on_accent"],
    }


def surface_stylesheet(col: dict) -> str:
    """Dialog-level stylesheet: flat themed surface, transparent sections."""
    return (f"QDialog {{ background: {col['bg']}; }}"
            f" QFrame#{SECTION_OBJECT_NAME} {{ background: transparent; }}")
