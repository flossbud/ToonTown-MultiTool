"""Global hotkeys for a window shell: the manager, the platform provider and
the interop with InputService's key grabber, in one object.

Three sources can fire a hotkey action, and each exists for a reason:

* ``HotkeyManager`` (the pynput listener) fires them on Windows and macOS,
  and feeds every key event to the router's queue on all platforms.
* A platform provider registers the chords with the OS: X11 passive grabs on
  Linux, Carbon ``RegisterEventHotKey`` on macOS.
* While InputService's persistent keyboard grab is held (X11 route_all) it
  preempts the provider's passive grabs, so the grabber is handed a lookup
  over the same bindings and dispatches matches itself.

All three end in ``on_action(action_id)`` on the GUI thread.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QTimer, Signal

from utils.settings_keys import HOTKEY_BINDINGS


class HotkeyWiring(QObject):
    # Provider registration failures, after the provider applied bindings:
    # whatever its failures() returns. For a hotkeys settings page.
    status_changed = Signal(object)

    def __init__(self, *, window_manager, settings_manager, input_service,
                 key_event_queue, on_action, parent: QObject | None = None):
        super().__init__(parent)
        from services.hotkey_manager import HotkeyManager
        from utils.hotkey_actions import ACTIONS, effective_bindings, make_hotkey_hook

        self._settings = settings_manager
        self._window_manager = window_manager
        self._input_service = input_service
        self._effective_bindings = effective_bindings
        self._repeat_ok_ids = frozenset(a.id for a in ACTIONS if a.repeat_ok)
        self._grabber_wired = False
        self._grabber_wire_error_logged = False
        self._grabber_lookup = {"lookup": None}

        self.hotkey_manager = HotkeyManager(
            window_manager,
            key_event_queue,
            suppress_predicate=input_service._suppress_predicate,
            hotkey_hook=make_hotkey_hook(settings_manager),
            fire_hotkeys=not sys.platform.startswith("linux"),
            hotkey_repeat_ok=self._repeat_ok_ids,
            vk_keysym_lookup=input_service.grabber_keysym_for_vk,
        )
        # hotkey_triggered is emitted on the listener thread; the connection
        # to a QObject slot hops to the GUI thread. Emission is gated by
        # fire_hotkeys inside the manager, so connecting is unconditional.
        self._on_action = on_action
        self.hotkey_manager.hotkey_triggered.connect(self._fire)
        self.hotkey_manager.start()

        self.global_hotkeys = self._start_provider()
        settings_manager.on_change(self._on_setting_changed)
        if self.global_hotkeys is not None:
            # After the provider's event thread has processed the queued apply.
            QTimer.singleShot(1000, self._push_status)

        # The grabber is created lazily by InputService.start(), so wiring
        # retries until it exists: the callback covers a service start while a
        # game already has focus (route_all can arm before any focus change),
        # the focus signal covers everything else.
        self._wire_grabber()
        if self.global_hotkeys is not None:
            input_service.grabber_created_callback = self._wire_grabber
            window_manager.active_window_changed.connect(self._wire_grabber)

    def _fire(self, action_id) -> None:
        self._on_action(action_id)

    def _start_provider(self):
        if sys.platform.startswith("linux"):
            from services.global_hotkeys import X11GlobalHotkeys as Provider
        elif sys.platform == "darwin":
            from services.global_hotkeys import MacOSCarbonHotkeys as Provider
        else:
            return None
        provider = Provider(repeat_ok_ids=self._repeat_ok_ids)
        if not provider.start():
            return None
        provider.action_triggered.connect(self._fire)
        provider.apply_bindings(self._effective_bindings(self._settings))
        if sys.platform == "darwin":
            # The session tap PRECEDES Carbon dispatch, so the tap keeps only
            # what Carbon can never see (suppressed chords, two-key chords)
            # and stops firing the rest; both firing would double-dispatch.
            self.hotkey_manager.set_hotkey_provider_armed(True)
        return provider

    def _on_setting_changed(self, key, _value) -> None:
        if key != HOTKEY_BINDINGS:
            return
        self._grabber_lookup["lookup"] = None       # rebuilt on the grabber thread
        if self.global_hotkeys is not None:
            self.global_hotkeys.apply_bindings(self._effective_bindings(self._settings))
            QTimer.singleShot(300, self._push_status)

    def failures(self):
        """The provider's registration failures; empty without a provider."""
        if self.global_hotkeys is None:
            return {}
        try:
            return self.global_hotkeys.failures()
        except Exception:  # noqa: BLE001
            return {}

    def _push_status(self) -> None:
        self.status_changed.emit(self.failures())

    def _wire_grabber(self, *_args) -> None:
        if self._grabber_wired or self.global_hotkeys is None:
            return
        try:
            grabber = self._input_service._key_grabber
            if grabber is None or not hasattr(grabber, "set_hotkey_lookup"):
                return
            from services.global_hotkeys import make_event_lookup
            # The lookup builds lazily ON the grabber's event thread from the
            # grabber's OWN display (X connection discipline) and is dropped
            # on any bindings change. is_down is the grabber's physical-state
            # check, so a two-key chord member matches only while its partner
            # is held.
            state = self._grabber_lookup
            settings = self._settings

            def lookup(keycode, kstate, is_down):
                if state["lookup"] is None:
                    display = getattr(grabber, "_display", None)
                    if display is None:
                        return None
                    state["lookup"] = make_event_lookup(display, settings)
                return state["lookup"](keycode, kstate, is_down)

            provider = self.global_hotkeys
            grabber.set_hotkey_lookup(
                lookup,
                # Signal emission is thread-safe: this hops to the GUI thread.
                lambda action_id: provider.action_triggered.emit(action_id),
                repeat_ok_ids=self._repeat_ok_ids)
            self._grabber_wired = True
        except Exception as e:  # noqa: BLE001
            if not self._grabber_wire_error_logged:
                self._grabber_wire_error_logged = True
                print(f"[GlobalHotkeys] route_all interop wiring failed: {e}")

    def stop(self) -> None:
        for label, target in (("global_hotkeys", self.global_hotkeys),
                              ("hotkey_manager", self.hotkey_manager)):
            if target is None:
                continue
            try:
                target.stop()
            except Exception as e:  # noqa: BLE001
                print(f"[HotkeyWiring] {label} stop error: {e}")
