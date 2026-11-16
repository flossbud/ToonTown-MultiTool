"""Everything that hangs off the strips: counters and the one open popover
each strip may have.

The manager owns the surfaces and their placement. It decides nothing about
toons: the controller hands it counter values and menu items and hears back
which lock or item was pressed.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from utils.strips.popovers import menu as menu_mod
from utils.strips.popovers.counters import CountersModel, CountersView
from utils.strips.popovers.menu import PillMenu
from utils.strips.popovers.placement import CENTER, LEFT, place_popover
from utils.strips.popovers.pointer_watch import PointerWatch
from utils.strips.popovers.surface import PopoverSurface

# How long the counters outlive the pointer leaving the name, so it can
# travel down to the lock.
COUNTERS_LINGER_MS = 160
IDENTITY = "identity"       # anchor: portrait plus name plate
CARD_GAP = 9


class _Entry:
    """What one strip has hanging off it."""

    def __init__(self) -> None:
        self.counters_model: CountersModel | None = None
        self.counters_view: CountersView | None = None
        self.counters_surface: PopoverSurface | None = None
        self.hover_identity = False
        self.hover_counters = False
        self.linger: QTimer | None = None
        self.popover: PopoverSurface | None = None
        self.tag = ""
        self.anchor: tuple[str, int] = ("", 0)
        self.gap = 0
        self.align = CENTER


class StripPopovers(QObject):
    lock_toggled = Signal(str)                # window id
    menu_chosen = Signal(str, str, str)       # window id, menu tag, item key
    closed = Signal(str, str)                 # window id, tag of what closed
    opened = Signal(str, str)                 # window id, tag
    counters_changed = Signal(str, bool)      # window id, showing or not

    def __init__(self, follower, watch: PointerWatch | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._follower = follower
        self._entries: dict[str, _Entry] = {}
        self._watch = watch if watch is not None else PointerWatch(parent=self)
        self._watch.pressed_outside.connect(self.close_all)
        self._watch.escape.connect(self.close_all)
        follower.add_companion(self._own_ids, self._sweep, self._refresh_presentation)

    @property
    def watch(self) -> PointerWatch:
        return self._watch

    # -- strips come and go -------------------------------------------------

    def attach_strip(self, wid: str) -> None:
        wid = str(wid)
        if wid in self._entries:
            return
        surface = self._follower.surface(wid)
        if surface is None:
            return
        self._entries[wid] = _Entry()
        surface.presentation_changed.connect(
            lambda shown, wid=wid: self._on_presentation(wid, shown))
        surface.geometry_applied.connect(lambda wid=wid: self._on_geometry(wid))
        surface.scale_changing.connect(lambda wid=wid: self.close(wid))

    def detach_strip(self, wid: str) -> None:
        entry = self._entries.pop(str(wid), None)
        if entry is None:
            return
        self._drop_popover(str(wid), entry)
        if entry.linger is not None:
            entry.linger.stop()
        if entry.counters_surface is not None:
            entry.counters_surface.dismiss()
        self._sync_watch()

    def shutdown(self) -> None:
        for wid in list(self._entries):
            self.detach_strip(wid)
        self._watch.shutdown()

    def set_style(self, name: str) -> None:
        for wid, entry in self._entries.items():
            if entry.counters_view is not None:
                entry.counters_view.set_style(name)
                self._place_counters(wid, entry)
        self.close_all()

    def rescale(self) -> None:
        """The strips changed size: the counters follow (anything else was
        closed, and opens at the strip's scale the next time)."""
        for wid, entry in self._entries.items():
            surface = self._follower.surface(wid)
            if entry.counters_view is not None and surface is not None:
                entry.counters_view.set_scale(surface.strip.scale())
                self._place_counters(wid, entry)

    # -- anchors ------------------------------------------------------------

    def anchor_rect(self, wid: str, kind: str, number: int = 0) -> QRect | None:
        """A block of a strip (or its identity group) in global coordinates."""
        surface = self._follower.surface(wid)
        if surface is None:
            return None
        strip = surface.strip
        rect = (strip.identity_rect() if kind == IDENTITY
                else strip.block_rect(kind, number))
        if rect is None:
            return None
        local = rect.toAlignedRect()
        return QRect(surface.mapToGlobal(local.topLeft()), local.size())

    @staticmethod
    def _screen_rect(anchor: QRect) -> QRect:
        screen = QGuiApplication.screenAt(anchor.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 100000, 100000)
        return screen.availableGeometry()

    # -- counters -----------------------------------------------------------

    def set_counters(self, wid: str, model: CountersModel | None) -> None:
        entry = self._entries.get(str(wid))
        if entry is None or model == entry.counters_model:
            return
        entry.counters_model = model
        self._update_counters(str(wid))

    def set_identity_hover(self, wid: str, on: bool) -> None:
        entry = self._entries.get(str(wid))
        if entry is None or entry.hover_identity == bool(on):
            return
        entry.hover_identity = bool(on)
        self._hover_changed(str(wid), entry)

    def counters_shown(self, wid: str) -> bool:
        entry = self._entries.get(str(wid))
        return bool(entry and entry.counters_surface is not None
                    and not entry.counters_surface._concealed
                    and entry.counters_surface.isVisible())

    def _hover_changed(self, wid: str, entry: _Entry) -> None:
        if entry.hover_identity or entry.hover_counters:
            if entry.linger is not None:
                entry.linger.stop()
            self._update_counters(wid)
            return
        if entry.linger is None:
            entry.linger = QTimer(self)
            entry.linger.setSingleShot(True)
            entry.linger.setInterval(COUNTERS_LINGER_MS)
            entry.linger.timeout.connect(lambda wid=wid: self._update_counters(wid))
        entry.linger.start()

    def _wants_counters(self, wid: str, entry: _Entry) -> bool:
        surface = self._follower.surface(wid)
        if surface is None or not surface.is_presented():
            return False
        model = entry.counters_model
        if model is None:
            return False
        if entry.popover is not None and entry.tag == "toon":
            return False        # the toon menu takes their place
        if not (model.locked or entry.hover_identity or entry.hover_counters):
            return False
        return not self._popover_covers_counters(wid, entry)

    def _popover_covers_counters(self, wid: str, entry: _Entry) -> bool:
        """Counters and popovers both hang under the strip. Where an open
        popover would sit over the counters (the home panel, an editor under
        the first keyset), the counters step aside until it closes."""
        if entry.popover is None or entry.counters_model is None:
            return False
        anchor = self.anchor_rect(wid, IDENTITY)
        surface = self._follower.surface(wid)
        if anchor is None or surface is None:
            return False
        view = entry.counters_view
        if view is None:
            # Not built yet: measure with a throwaway of the same content.
            view = CountersView()
            view.set_scale(surface.strip.scale())
            view.set_style(surface.strip.style_name())
            view.set_model(entry.counters_model)
            view.deleteLater()
        elif view.model() != entry.counters_model:
            view.set_model(entry.counters_model)
        spot = place_popover(anchor, view.sizeHint(), self._screen_rect(anchor), gap=0)
        pill = view.pill_rect().toAlignedRect().translated(spot.pos)
        content = entry.popover.content
        rects = getattr(content, "input_rects", None)
        rects = rects() if callable(rects) else [content.rect()]
        origin = entry.popover.pos()
        return any(r.translated(origin).intersects(pill) for r in rects)

    def _update_counters(self, wid: str) -> None:
        entry = self._entries.get(wid)
        if entry is None:
            return
        if not self._wants_counters(wid, entry):
            if entry.counters_surface is not None:
                was = not entry.counters_surface._concealed
                entry.counters_surface.conceal()
                if was:
                    self.counters_changed.emit(wid, False)
            return
        surface = self._follower.surface(wid)
        if entry.counters_view is None:
            view = CountersView()
            view.set_scale(surface.strip.scale())
            view.set_style(surface.strip.style_name())
            view.lock_clicked.connect(lambda wid=wid: self.lock_toggled.emit(wid))
            view.hover_changed.connect(
                lambda on, wid=wid: self._counters_hover(wid, on))
            entry.counters_view = view
            entry.counters_surface = PopoverSurface(
                surface.strategy, surface.backend, view)
        entry.counters_view.set_style(surface.strip.style_name())
        entry.counters_view.set_model(entry.counters_model)
        was = not entry.counters_surface._concealed
        self._place_counters(wid, entry)
        if not was:
            self.counters_changed.emit(wid, True)

    def _counters_hover(self, wid: str, on: bool) -> None:
        entry = self._entries.get(wid)
        if entry is None or entry.hover_counters == on:
            return
        entry.hover_counters = on
        self._hover_changed(wid, entry)

    def _place_counters(self, wid: str, entry: _Entry) -> None:
        anchor = self.anchor_rect(wid, IDENTITY)
        surface = self._follower.surface(wid)
        if anchor is None or surface is None or entry.counters_surface is None:
            return
        size = entry.counters_view.sizeHint()
        spot = place_popover(anchor, size, self._screen_rect(anchor), gap=0)
        if self._wants_counters(wid, entry):
            self._gate_before_present(wid, entry.counters_surface, spot.pos)
            entry.counters_surface.present(spot.pos, int(surface.winId()))
        else:
            entry.counters_surface.fit(spot.pos)

    # -- the one open popover per strip --------------------------------------

    def open_tag(self, wid: str) -> str:
        entry = self._entries.get(str(wid))
        return entry.tag if entry and entry.popover is not None else ""

    def open_surface(self, wid: str) -> PopoverSurface | None:
        entry = self._entries.get(str(wid))
        return entry.popover if entry else None

    def counters_surface(self, wid: str) -> PopoverSurface | None:
        entry = self._entries.get(str(wid))
        return entry.counters_surface if entry else None

    def open_content(self, wid: str) -> QWidget | None:
        entry = self._entries.get(str(wid))
        return entry.popover.content if entry and entry.popover is not None else None

    def toggle_menu(self, wid: str, tag: str, anchor_kind: str, anchor_number: int,
                    colour: str, items) -> PillMenu | None:
        """Open a pill menu on a block, or close it if it is the one open."""
        wid = str(wid)
        entry = self._entries.get(wid)
        surface = self._follower.surface(wid)
        if entry is None or surface is None:
            return None
        same = (entry.popover is not None and entry.tag == tag
                and entry.anchor == (anchor_kind, anchor_number))
        self.close(wid)
        if same or not surface.is_presented():
            return None
        content = PillMenu(items, colour, surface.strip.style_name(),
                           surface.strip.scale())
        content.chosen.connect(lambda key, wid=wid, tag=tag: self._chosen(wid, tag, key))
        self._open(wid, entry, tag, (anchor_kind, anchor_number), content,
                   gap=int(round(menu_mod.ANCHOR_GAP * surface.strip.scale())))
        return content

    def open_card(self, wid: str, tag: str, anchor_kind: str, anchor_number: int,
                  content: QWidget, align: str = CENTER) -> PopoverSurface | None:
        """Open any other content (the keyset editor, the home panels) under
        a block. The caller keeps talking to `content`."""
        wid = str(wid)
        entry = self._entries.get(wid)
        surface = self._follower.surface(wid)
        self.close(wid)
        if entry is None or surface is None or not surface.is_presented():
            content.deleteLater()
            return None
        gap = getattr(content, "ANCHOR_GAP", CARD_GAP)
        return self._open(wid, entry, tag, (anchor_kind, anchor_number), content,
                          gap=int(round(gap * surface.strip.scale())), align=align)

    def _open(self, wid: str, entry: _Entry, tag: str, anchor: tuple[str, int],
              content: QWidget, gap: int, align: str = CENTER):
        surface = self._follower.surface(wid)
        entry.popover = PopoverSurface(surface.strategy, surface.backend, content)
        entry.tag, entry.anchor, entry.gap, entry.align = tag, anchor, gap, align
        if not self._place_popover(wid, entry):
            self._drop_popover(wid, entry)
            return None
        self._update_counters(wid)
        self._sync_watch()
        self.opened.emit(wid, tag)
        return entry.popover

    def _place_popover(self, wid: str, entry: _Entry) -> bool:
        rect = self.anchor_rect(wid, *entry.anchor)
        surface = self._follower.surface(wid)
        if rect is None or surface is None or entry.popover is None:
            return False
        content = entry.popover.content
        # A left-aligned card lines its CARD up with the anchor; the halo
        # margin around it hangs out to the left.
        inset = 0
        if entry.align == LEFT:
            inset = int(round(getattr(content, "LEFT_INSET", 0) * surface.strip.scale()))
        screen = self._screen_rect(rect)
        bound_height = getattr(content, "set_available_height", None)
        if callable(bound_height):
            bound_height(None)
            below = screen.bottom() + 1 - 8 - (rect.bottom() + 1 + entry.gap)
            above = rect.top() - entry.gap - (screen.top() + 8)
            room = below
            if content.sizeHint().height() > below and above > below:
                room = above
            bound_height(max(1, room))
        spot = place_popover(rect.translated(-inset, 0), content.sizeHint(),
                             screen, gap=entry.gap, align=entry.align)
        if hasattr(content, "set_caret_x"):
            content.set_caret_x(spot.caret_x + inset)
        if hasattr(content, "set_flipped"):
            content.set_flipped(spot.flipped)
        self._gate_before_present(wid, entry.popover, spot.pos)
        entry.popover.present(spot.pos, int(surface.winId()))
        return True

    def _gate_before_present(self, wid: str, surface: PopoverSurface, pos: QPoint) -> None:
        strategy = self._follower.strategy
        if not strategy.gated:
            return
        target = QRect(pos, surface.content.sizeHint())
        try:
            region = strategy.visible_region(
                target, wid, self._follower.own_window_ids(), clip=False)
        except Exception:
            region = None
        surface.set_visible_region(region)

    def refit(self, wid: str) -> None:
        """The open popover's content changed size."""
        entry = self._entries.get(str(wid))
        if entry is not None and entry.popover is not None:
            self._place_popover(str(wid), entry)

    def _chosen(self, wid: str, tag: str, key: str) -> None:
        self.close(wid)
        self.menu_chosen.emit(wid, tag, key)

    def _drop_popover(self, wid: str, entry: _Entry) -> None:
        popover, tag = entry.popover, entry.tag
        entry.popover, entry.tag, entry.anchor = None, "", ("", 0)
        if popover is not None:
            cancel = getattr(popover.content, "cancel_capture", None)
            if callable(cancel):
                cancel()        # never leave the keyboard held by a dead popover
            popover.dismiss()
            self.closed.emit(wid, tag)

    def close(self, wid: str) -> None:
        wid = str(wid)
        entry = self._entries.get(wid)
        if entry is None or entry.popover is None:
            return
        self._drop_popover(wid, entry)
        self._update_counters(wid)
        self._sync_watch()

    def close_all(self) -> None:
        for wid in list(self._entries):
            self.close(wid)

    # -- following the strip --------------------------------------------------

    def _on_presentation(self, wid: str, shown: bool) -> None:
        entry = self._entries.get(wid)
        if entry is None:
            return
        if not shown:
            # The window is moving, minimized or covered: nothing hangs in
            # mid-air. Counters come back with the strip; a menu does not.
            self._drop_popover(wid, entry)
            entry.hover_identity = entry.hover_counters = False
            self._sync_watch()
        self._update_counters(wid)

    def _on_geometry(self, wid: str) -> None:
        entry = self._entries.get(wid)
        if entry is None:
            return
        if entry.counters_surface is not None:
            surface = self._follower.surface(wid)
            if surface is not None:
                entry.counters_view.set_scale(surface.strip.scale())
            self._place_counters(wid, entry)
        if entry.popover is not None and not self._place_popover(wid, entry):
            self.close(wid)      # its anchor block is gone

    # -- outside clicks, Escape ------------------------------------------------

    def _sync_watch(self) -> None:
        if any(e.popover is not None for e in self._entries.values()):
            self._watch.watch(self._inside)
        else:
            self._watch.stop()

    def _inside(self, point: QPoint) -> bool:
        """Clicks here do not count as "elsewhere": on an open popover, or on
        the block it hangs from (that block's own click toggles it)."""
        for wid, entry in self._entries.items():
            if entry.popover is None:
                continue
            if entry.popover.geometry().contains(point):
                return True
            rect = self.anchor_rect(wid, *entry.anchor)
            if rect is not None and rect.contains(point):
                return True
        return False

    # -- the follower's hooks ----------------------------------------------------

    def _surfaces(self):
        for wid, entry in self._entries.items():
            for s in (entry.counters_surface, entry.popover):
                if s is not None and s.isVisible():
                    yield wid, s

    def _refresh_presentation(self) -> None:
        for _wid, surface in self._surfaces():
            surface.refresh_presentation()

    def _own_ids(self) -> list[int]:
        return [int(s.winId()) for _wid, s in self._surfaces()]

    def _sweep(self, strategy, own) -> None:
        for wid, s in self._surfaces():
            s.set_visible_region(
                strategy.visible_region(s.geometry(), wid, own, clip=False))
