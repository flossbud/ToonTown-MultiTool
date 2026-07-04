"""Darwin grabber/backend lifecycle-conformance integration test.

Unlike the unit tests in test_ttr_strict_separation.py (which drive the focus
handler against a *fake* grabber), this module drives the REAL
services.input_service.InputService lifecycle wired to the REAL
utils.macos_movement_grabber.MacOSMovementKeyGrabber, built through
InputService._start_key_grabber()'s darwin branch. It asserts that the macOS
grabber CONFORMS to the platform-agnostic install / focus-change / readiness /
restart / shutdown lifecycle every grabber must honor, with no macOS-specific
reimplementation of that lifecycle.

Run:
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        pytest tests/test_input_service_darwin_lifecycle.py -q

Every test pins sys.platform="darwin" (so MacOSMovementKeyGrabber.prepare()
returns True and _ttr_strict_supported()/_delivery_backend_ready() take the
darwin path) and calls svc.shutdown() in a finally block (the project requires
input_service cleanup so no grabber/X-slot/thread is leaked).
"""
import sys
from types import SimpleNamespace

import pytest

from utils.macos_movement_grabber import MacOSMovementKeyGrabber


class _StubBackend:
    """Stand-in for the real MacOSBackend.

    Non-None so _delivery_backend_ready() is True, and exposing
    disconnect()/send_* so InputService.shutdown() (which calls
    self._xlib.disconnect()) and any incidental delivery do not raise. A bare
    object() -- as test_ttr_strict_separation uses, where shutdown is never
    called -- would AttributeError inside shutdown()."""

    def __init__(self) -> None:
        self.keydowns: list[tuple[str, str]] = []
        self.keyups: list[tuple[str, str]] = []
        self.post_access = True  # has_post_access() result (Accessibility/TCC)

    def disconnect(self) -> None:
        pass

    def has_post_access(self) -> bool:
        return self.post_access

    def send_keydown(self, win_id, keysym) -> bool:
        self.keydowns.append((str(win_id), keysym))
        return True

    def send_keyup(self, win_id, keysym) -> bool:
        self.keyups.append((str(win_id), keysym))
        return True

    def send_key(self, win_id, keysym, modifiers=None) -> bool:
        return True


def _make_service(monkeypatch, tmp_path, active_wid="", windows=None,
                  games=None, assignments=None, settings=None):
    """Construct a real InputService with stub deps; the run loop is never
    started. Adapted from test_ttr_strict_separation._make_service, with two
    deliberate changes for a lifecycle (not unit) test:

      * sys.platform is pinned to "darwin" up front so _start_key_grabber()
        builds a MacOSMovementKeyGrabber and the platform gates resolve darwin.
      * _xlib is a _StubBackend (with disconnect()) rather than a bare object(),
        because these tests always call shutdown().
    """
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from utils.keymap_manager import KeymapManager
    from utils.game_registry import GameRegistry
    from services.input_service import InputService

    km = KeymapManager()
    windows = windows or []
    games = games or {}
    assignments = assignments or [0] * len(windows)

    monkeypatch.setattr(
        GameRegistry.instance(), "get_game_for_window",
        lambda wid: games.get(str(wid)),
    )

    wm = SimpleNamespace(
        get_active_window=lambda: active_wid,
        get_window_ids=lambda: windows,
        assign_windows=lambda: None,
    )

    store = dict(settings or {})
    sm = SimpleNamespace(
        get=lambda k, d=None: store.get(k, d),
        set=lambda k, v: store.__setitem__(k, v),
        on_change=lambda cb: None,
    )

    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True] * len(windows),
        get_movement_modes=lambda: ["WASD"] * len(windows),
        get_event_queue_func=lambda: None,
        keymap_manager=km,
        get_keymap_assignments=lambda: assignments,
        settings_manager=sm,
    )
    # A usable delivery backend so _delivery_backend_ready() is True until a
    # test deliberately tears it down.
    svc._xlib = _StubBackend()
    svc._xlib_backend_failed = False
    return svc, km


def test_start_key_grabber_builds_real_macos_grabber(monkeypatch, tmp_path):
    """_start_key_grabber()'s darwin branch builds the REAL macOS grabber and
    exposes needs_focused_passthrough=False (the darwin_intercept filter is
    non-exclusive, so non-grabbed keys reach the focused window natively)."""
    svc, _ = _make_service(monkeypatch, tmp_path, active_wid="", windows=[], games={})
    try:
        svc._start_key_grabber()
        assert isinstance(svc._key_grabber, MacOSMovementKeyGrabber)
        assert svc._key_grabber.needs_focused_passthrough is False
    finally:
        svc.shutdown()


def test_startup_focus_seeds_route_all_install_for_ttr(monkeypatch, tmp_path):
    """Startup focus seeding (the _start_key_grabber tail) installs route_all
    grabs for a focused TTR window. The grab set is the KEYMAP UNION (every
    key bound in any of the game's sets) — the fresh tmp config has TTR's
    single native arrows set, so Up/space/Delete are suppressed while w is
    NOT (unbound: the router would never re-synthesize it, so suppressing it
    would silently eat it). Non-movement keys (Return) are not suppressed,
    and the real-install gate _ttr_grabs_active is flipped True via the
    grabber's on_grabs_changed."""
    svc, _ = _make_service(
        monkeypatch, tmp_path, active_wid="ttr-1",
        windows=["ttr-1"], games={"ttr-1": "ttr"}, assignments=[0],
    )
    try:
        svc._start_key_grabber()  # seeds focus to ttr-1 -> route_all install
        g = svc._key_grabber
        assert g.should_suppress("Up") is True
        assert g.should_suppress("space") is True
        assert g.should_suppress("Delete") is True
        assert g.should_suppress("w") is False  # unbound in this config's union
        assert g.should_suppress("Return") is False
        assert svc._ttr_grabs_active is True
    finally:
        svc.shutdown()


def test_focus_game_to_nongame_uninstalls(monkeypatch, tmp_path):
    """Focusing away from a TTR window to a non-game window uninstalls the grab
    set: the real grabber stops suppressing and _ttr_grabs_active clears."""
    svc, _ = _make_service(
        monkeypatch, tmp_path, active_wid="ttr-1",
        windows=["ttr-1"], games={"ttr-1": "ttr"}, assignments=[0],
    )
    try:
        svc._start_key_grabber()
        assert svc._key_grabber.should_suppress("Up") is True  # seeded TTR focus
        # Focus a REAL non-game window: get_game_for_window -> None -> the
        # "game not in (cc, ttr)" uninstall branch (distinct from the empty-wid
        # focus-loss branch).
        svc._on_active_window_changed_for_grabber("finder-1")
        assert svc._key_grabber.should_suppress("Up") is False
        assert svc._ttr_grabs_active is False
        # The empty-window focus-loss path also keeps grabs uninstalled.
        svc._on_active_window_changed_for_grabber("ttr-1")  # re-arm
        assert svc._key_grabber.should_suppress("Up") is True
        svc._on_active_window_changed_for_grabber("")
        assert svc._key_grabber.should_suppress("Up") is False
        assert svc._ttr_grabs_active is False
    finally:
        svc.shutdown()


def test_focus_game_to_game_reinstalls_safely(monkeypatch, tmp_path):
    """Focusing from one TTR window to another reinstalls grabs cleanly (no
    stuck/torn state): suppression stays active across the game->game switch."""
    svc, _ = _make_service(
        monkeypatch, tmp_path, active_wid="ttr-1",
        windows=["ttr-1", "ttr-2"], games={"ttr-1": "ttr", "ttr-2": "ttr"},
        assignments=[0, 0],
    )
    try:
        svc._start_key_grabber()
        assert svc._key_grabber.should_suppress("Up") is True
        # Spy on the REAL grabber's install_grabs to PROVE the game->game focus
        # actually re-applies the grab set, rather than just observing that
        # suppression is still on from the ttr-1 seed (which would pass even if
        # the ttr-2 focus did nothing).
        installs = []
        _real_install = svc._key_grabber.install_grabs

        def _spy_install(*args, **kwargs):
            installs.append((args, kwargs))
            return _real_install(*args, **kwargs)

        svc._key_grabber.install_grabs = _spy_install
        svc._on_active_window_changed_for_grabber("ttr-2")
        assert installs, "focusing ttr-2 must (re)install the grab set"
        assert installs[-1][1].get("route_all") is True  # route_all reinstall
        assert svc._key_grabber.should_suppress("Up") is True
        assert svc._ttr_grabs_active is True
    finally:
        svc.shutdown()


def test_readiness_loss_disables_suppression(monkeypatch, tmp_path):
    """No-freeze invariant: when the delivery backend dies, suppression must
    turn OFF so the focused toon falls back to native delivery instead of being
    grabbed-but-not-redelivered (frozen). The focus handler's own gate reads
    UIPI safety, not backend health, so it may still re-install the grab set;
    but should_suppress() routes through _should_consume_grabbed_key ->
    _delivery_backend_ready(), which is False here, so the key is NOT
    suppressed. (This is the same degrade path proven for win32 in
    test_dead_backend_degrades_through_should_suppress_bridge.)"""
    svc, _ = _make_service(
        monkeypatch, tmp_path, active_wid="ttr-1",
        windows=["ttr-1"], games={"ttr-1": "ttr"}, assignments=[0],
    )
    try:
        svc._start_key_grabber()
        assert svc._key_grabber.should_suppress("Up") is True  # healthy backend

        # Simulate delivery-backend loss.
        svc._xlib = None
        svc._xlib_backend_failed = True
        assert svc._delivery_backend_ready() is False

        svc._on_active_window_changed_for_grabber("ttr-1")  # re-focus
        # Grabs ARE (re)installed (the focus gate reads UIPI safety, not backend
        # health)...
        assert svc._ttr_grabs_active is True
        # ...but suppression is degraded OFF by the consume-gate -> not frozen.
        assert svc._key_grabber.should_suppress("Up") is False
    finally:
        svc.shutdown()


def test_accessibility_revoked_disables_suppression_no_freeze(monkeypatch, tmp_path):
    """Review finding I-1: a CONNECTED backend whose Accessibility (post) access
    is revoked must still degrade suppression. CGEventPostToPid silently no-ops
    without post-permission, so if suppression stayed on the focused toon would
    freeze. Here the backend is non-None (unlike the backend-death test above) but
    has_post_access() is False; _delivery_backend_ready() must therefore be False
    and should_suppress() must degrade to native delivery -- live, per keystroke.
    """
    svc, _ = _make_service(
        monkeypatch, tmp_path, active_wid="ttr-1",
        windows=["ttr-1"], games={"ttr-1": "ttr"}, assignments=[0],
    )
    try:
        svc._start_key_grabber()
        assert svc._key_grabber.should_suppress("Up") is True   # post-access OK
        # Accessibility revoked mid-session: backend object still present.
        svc._xlib.post_access = False
        assert svc._delivery_backend_ready() is False
        assert svc._key_grabber.should_suppress("Up") is False  # degraded -> no freeze
    finally:
        svc.shutdown()


def test_restart_is_idempotent(monkeypatch, tmp_path):
    """_start_key_grabber() is idempotent: a second call must not rebuild the
    grabber (the stop()/start() cycle preserves it)."""
    svc, _ = _make_service(monkeypatch, tmp_path, active_wid="", windows=[], games={})
    try:
        svc._start_key_grabber()
        g = svc._key_grabber
        assert g is not None
        svc._start_key_grabber()
        assert svc._key_grabber is g
    finally:
        svc.shutdown()


def test_shutdown_stops_grabber(monkeypatch, tmp_path):
    """shutdown() stops the grabber (uninstalling the grab set) and drops the
    reference. We capture the grabber before shutdown because shutdown() nulls
    svc._key_grabber; the captured object must no longer suppress. A second
    shutdown() must be a safe no-op (no grabber, no backend)."""
    svc, _ = _make_service(
        monkeypatch, tmp_path, active_wid="ttr-1",
        windows=["ttr-1"], games={"ttr-1": "ttr"}, assignments=[0],
    )
    try:
        svc._start_key_grabber()
        g = svc._key_grabber  # capture before shutdown() nulls it
        assert g.should_suppress("Up") is True
    finally:
        svc.shutdown()
    assert svc._key_grabber is None       # service dropped the reference
    assert g.should_suppress("Up") is False  # stop() uninstalled the grab set
    svc.shutdown()  # guard against double-shutdown: must not raise


@pytest.mark.skip(
    reason="Held-key release on teardown/focus-away is platform-agnostic "
    "router+backend behavior, already covered by "
    "test_ttr_strict_separation.test_strict_toggle_off_while_held_sends_"
    "focused_keyup and the release_all_keys tests, plus T13 live validation. "
    "Driving a held movement key without the run loop requires seeding the "
    "private holds registry (holds.acquire), which the task says not to force; "
    "it is not macOS-grabber-specific, so it adds no grabber-conformance "
    "coverage here."
)
def test_held_keys_released_before_teardown(monkeypatch, tmp_path):  # pragma: no cover
    pass
