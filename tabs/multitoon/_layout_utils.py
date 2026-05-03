"""Small Qt layout helpers used by the Multitoon Compact/Full layout classes."""

from PySide6.QtWidgets import QLayout


def clear_layout(layout: QLayout) -> None:
    """Take every item out of `layout` without destroying the widgets.

    Used during a layout-mode swap: the new layout calls this on its slot
    sub-layouts before re-adding the shared widgets, so we don't accumulate
    stale `QLayoutItem`s referencing widgets that have been re-parented.
    Widgets themselves are owned by `MultitoonTab` (the shared-widgets pool)
    and must survive — only the layout's references are dropped.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            # Detach so a subsequent addWidget on this widget reparents cleanly.
            widget.setParent(None)
        # If the item is a sub-layout (not a widget), takeAt has already
        # removed it; the sub-layout itself isn't destroyed but is now orphan.
        # Callers re-add their sub-layouts by hand after clear.
