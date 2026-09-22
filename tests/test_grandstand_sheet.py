"""The focus-mode sheet shell: header, cross-link, footer, body hosting."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QLineEdit, QPushButton, QWidget

from utils.widgets.grandstand.sheet import (
    BACK_GLYPH, BACK_SIZE, CROSS_LINK_H, FOOTER_BUTTON_H, SheetHeader,
    SheetShell,
)

TITLE = "Account · Flossbud"
SUBTITLE = "Toontown Rewritten · changes apply to this account only"
CROSS = "✏ Customize appearance"


@pytest.fixture
def shell(qapp):
    s = SheetShell()
    yield s
    s.close()
    s.deleteLater()
    qapp.processEvents()


def test_header_copy_is_kept_verbatim_and_rendered_uppercase(shell):
    """Handoff §4.4 writes `Account · {label|username}`; the prototype renders
    the title as an uppercase section label, the subtitle in sentence case."""
    shell.set_header(TITLE, SUBTITLE)
    assert shell.header.title_text() == TITLE
    assert shell.header.title.text() == "ACCOUNT · FLOSSBUD"
    assert shell.header.subtitle_text() == SUBTITLE
    assert shell.header.subtitle.text() == SUBTITLE


def test_the_one_cross_link_shows_only_with_copy(shell):
    assert shell.header.cross_link.isVisibleTo(shell) is False
    assert shell.header.cross_link_text() == ""
    shell.set_cross_link(CROSS)
    assert shell.header.cross_link.isVisibleTo(shell) is True
    assert shell.header.cross_link_text() == CROSS
    shell.set_cross_link("")
    assert shell.header.cross_link.isVisibleTo(shell) is False
    assert shell.header.cross_link_text() == ""


def test_back_cancel_save_and_cross_link_emit_their_intents(shell):
    seen = []
    shell.back_requested.connect(lambda: seen.append("back"))
    shell.cancel_requested.connect(lambda: seen.append("cancel"))
    shell.save_requested.connect(lambda: seen.append("save"))
    shell.cross_link_requested.connect(lambda: seen.append("x"))
    shell.set_cross_link(CROSS)
    shell.back_button.click()
    shell.cancel_button.click()
    shell.save_button.click()
    shell.header.cross_link.click()
    assert seen == ["back", "cancel", "save", "x"]


def test_footer_note(shell):
    shell.set_note("3 toons discovered")
    assert shell.note_text() == "3 toons discovered"
    assert shell.note.text() == "3 toons discovered"


def test_body_is_hosted_and_replaceable(shell):
    assert shell.body() is None
    first = QWidget()
    shell.set_body(first)
    assert shell.body() is first
    assert first.parent() is shell
    second = QWidget()
    shell.set_body(second)
    assert shell.body() is second
    assert first.parent() is None


def test_handoff_measurements(shell):
    """§4.4: 28 px back arrow, 30 px footer buttons; §4.5: 28 px cross-link."""
    assert (BACK_SIZE, CROSS_LINK_H, FOOTER_BUTTON_H) == (28, 28, 30)
    assert shell.back_button.width() == shell.back_button.height() == BACK_SIZE
    assert shell.back_button.text() == BACK_GLYPH
    assert shell.header.cross_link.height() == CROSS_LINK_H
    assert shell.cancel_button.height() == shell.save_button.height() == FOOTER_BUTTON_H
    assert (shell.cancel_button.text(), shell.save_button.text()) == ("Cancel", "Save")


def test_header_is_reusable_on_its_own(qapp):
    """The toon browser mounts the same head row (handoff §4.7)."""
    header = SheetHeader()
    header.set_copy("Choose a toon · Flossbud", "x")
    seen = []
    header.back_requested.connect(lambda: seen.append(1))
    header.back_button.click()
    assert seen == [1]
    assert header.title.text() == "CHOOSE A TOON · FLOSSBUD"


def test_theme_reaches_the_body(shell):
    class Body(QWidget):
        def __init__(self):
            super().__init__()
            self.seen = []

        def apply_theme(self, is_dark):
            self.seen.append(is_dark)

    body = Body()
    shell.set_body(body)                 # hosting applies the current theme
    shell.apply_theme(False)
    assert body.seen == [True, False]
