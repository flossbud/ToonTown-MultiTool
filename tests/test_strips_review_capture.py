"""Only one strip editor may own the shared capture session."""
from PySide6.QtWidgets import QWidget

from utils import chord_capture_state
from utils.strips.popovers.editor import EditorModel, KeysetEditor


def test_new_capture_cancels_previous_editor_before_it_takes_ownership(qapp, monkeypatch):
    sessions = []
    monkeypatch.setattr('utils.strips.popovers.editor.key_session.begin',
                        lambda w: sessions.append(('begin', w)))
    monkeypatch.setattr('utils.strips.popovers.editor.key_session.end',
                        lambda w: sessions.append(('end', w)))
    model = EditorModel(1, (('forward', 'Forward'),), (('forward', 'w'),))
    first, second = KeysetEditor(model), KeysetEditor(model)
    first.show()
    second.show()
    try:
        first.begin_capture('forward')
        second.begin_capture('forward')
        assert not first.listening()
        assert second.listening() == 'forward'
        assert sessions == [('begin', first), ('end', first), ('begin', second)]
        # Closing the first toon after ownership changed must not end the new session.
        first.close()
        assert chord_capture_state.is_active()
        assert QWidget.keyboardGrabber() is second
        second.cancel_capture()
        assert not chord_capture_state.is_active()
        assert QWidget.keyboardGrabber() is None
    finally:
        first.cancel_capture()
        second.cancel_capture()
        first.close()
        second.close()
