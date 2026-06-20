import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
from PySide6.QtWidgets import QWidget, QLabel
from tabs.multitoon._card_dim_overlay import CardDimOverlay


def test_overlay_tracks_parent_size_and_dims(qapp):
    parent = QWidget()
    parent.resize(200, 150)
    ov = CardDimOverlay(parent)
    ov.set_dimmed(True)
    parent.show()
    qapp.processEvents()
    assert ov.geometry() == parent.rect()
    from PySide6.QtCore import Qt
    assert ov.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert ov.is_dimmed() is True
    ov.set_dimmed(False)
    assert ov.is_dimmed() is False
    # The Resize branch of the event filter keeps the overlay sized to the parent.
    parent.resize(320, 240)
    qapp.processEvents()
    assert ov.geometry() == parent.rect()


def test_overlay_self_heals_above_siblings(qapp):
    """A sibling re-parented in AFTER the overlay restacks above it; the overlay
    must return to the top (via ChildAdded re-raise and set_dimmed's raise_), so
    the dim wash always covers the content."""
    parent = QWidget()
    ov = CardDimOverlay(parent)
    ov.set_dimmed(True)
    # Simulate populate() re-parenting a control onto the card after the overlay.
    content = QLabel("control", parent)
    content.setParent(parent)  # restacks content above the overlay
    qapp.processEvents()
    kids = [c for c in parent.children() if isinstance(c, QWidget)]
    assert kids[-1] is ov, "overlay must self-heal back on top of late siblings"


def test_no_graphics_effect_used(qapp):
    parent = QWidget()
    ov = CardDimOverlay(parent)
    ov.set_dimmed(True)
    assert ov.graphicsEffect() is None
    assert parent.graphicsEffect() is None
