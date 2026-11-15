"""The small modal dialogs must be readable in both themes.

The app stylesheet paints every widget with the theme background, so a
modal's surface is light in light mode. These dialogs used to hardcode
white text, which was nearly invisible there.

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_modal_theme_contrast.py -v
"""
import re

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _luma(css: str, prop: str) -> float:
    m = re.search(rf"(?<![-\w]){prop}:\s*([^;}}]+)", css)
    assert m, f"no {prop} in {css!r}"
    return QColor(m.group(1).strip()).lightnessF()


def _confirm(mod):
    d = mod.ConfirmDialog("Delete account?", "This cannot be undone.", "Delete",
                          show_dont_ask_again=True)
    return d, [d.title_label, d.body_label, d.dont_ask_again_check, d.cancel_btn]


def _error(mod):
    d = mod.ErrorModal("Louie", "ttr", "Login failed")
    return d, [d.title_label, d.subline, d.close_btn]


def _uipi(mod):
    d = mod.UipiElevationDialog(["Louie"])
    return d, [d._title, d._body, d._affected, d._remediation]


CASES = [
    ("utils.widgets.confirm_dialog", _confirm),
    ("utils.widgets.error_modal", _error),
    ("utils.widgets.uipi_elevation_dialog", _uipi),
]


@pytest.mark.parametrize("is_dark", [False, True])
@pytest.mark.parametrize("module_name,build", CASES)
def test_text_contrasts_with_the_surface(qapp, monkeypatch, module_name, build, is_dark):
    import importlib
    mod = importlib.import_module(module_name)
    monkeypatch.setattr(mod, "is_dark_palette", lambda: is_dark)
    dialog, widgets = build(mod)
    surface = _luma(dialog.styleSheet(), "background")
    assert (surface < 0.5) is is_dark
    for w in widgets:
        text = _luma(w.styleSheet(), "color")
        assert abs(text - surface) > 0.3, (
            f"{module_name} {type(w).__name__} {w.text()!r}: "
            f"text {text:.2f} on surface {surface:.2f}")


@pytest.mark.parametrize("is_dark", [False, True])
def test_error_detail_box_is_readable(qapp, monkeypatch, is_dark):
    import utils.widgets.error_modal as mod
    monkeypatch.setattr(mod, "is_dark_palette", lambda: is_dark)
    dialog = mod.ErrorModal("Louie", "cc", "boom")   # keep it alive
    css = dialog.body_text.styleSheet()
    text = QColor(re.search(r"(?<![-\w])color:\s*([^;}]+)", css).group(1).strip())
    assert (text.lightnessF() > 0.5) is is_dark
