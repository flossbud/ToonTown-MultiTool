"""Tests for utils.macos_movement_grabber."""

from __future__ import annotations

import sys

from utils import macos_movement_grabber as mmg


def _always_consume(_keysym: str) -> bool:
    return True


def _never_consume(_keysym: str) -> bool:
    return False


class TestPrepare:
    def test_prepare_returns_false_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        g = mmg.MacOSMovementKeyGrabber()
        assert g.prepare(_always_consume) is False

    def test_prepare_returns_true_on_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        assert g.prepare(_always_consume) is True

    def test_should_suppress_false_without_install(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        assert g.should_suppress("Up") is False
        assert g.should_suppress("w") is False


class TestInstallGrabs:
    def test_install_wasd_suppresses_arrows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        assert g.should_suppress("Up") is True
        assert g.should_suppress("Down") is True
        assert g.should_suppress("Left") is True
        assert g.should_suppress("Right") is True
        assert g.should_suppress("w") is False
        assert g.should_suppress("a") is False

    def test_install_arrows_suppresses_wasd(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("arrows")
        assert g.should_suppress("w") is True
        assert g.should_suppress("a") is True
        assert g.should_suppress("s") is True
        assert g.should_suppress("d") is True
        assert g.should_suppress("Up") is False

    def test_install_unknown_canonical_is_noop(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("xyz")
        assert g.should_suppress("Up") is False
        assert g.should_suppress("w") is False

    def test_install_idempotent_for_same_canonical(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        g.install_grabs("wasd")
        assert g.should_suppress("Up") is True

    def test_install_switch_canonical_replaces_set(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        g.install_grabs("arrows")
        assert g.should_suppress("Up") is False
        assert g.should_suppress("w") is True

    def test_passthrough_keysyms_param_accepted_but_ignored(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd", passthrough_keysyms=["Up", "Down"])
        assert g.should_suppress("Up") is True
        assert g.should_suppress("Down") is True


class TestUninstallGrabs:
    def test_uninstall_clears_suppression(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        g.uninstall_grabs()
        assert g.should_suppress("Up") is False

    def test_uninstall_without_install_is_noop(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.uninstall_grabs()
        assert g.should_suppress("Up") is False


class TestShouldConsumeGating:
    def test_should_consume_false_blocks_suppression(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_never_consume)
        g.install_grabs("wasd")
        assert g.should_suppress("Up") is False

    def test_should_consume_raises_returns_false(self, monkeypatch):
        def boom(_k: str) -> bool:
            raise RuntimeError("oops")

        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(boom)
        g.install_grabs("wasd")
        assert g.should_suppress("Up") is False


class TestStop:
    def test_stop_clears_grabs(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        g.stop()
        assert g.should_suppress("Up") is False

    def test_stop_is_idempotent(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.stop()
        g.stop()  # second call must not raise


class TestModuleHelpers:
    def test_opposite_keys_wasd(self):
        assert mmg._opposite_keys("wasd") == ("Up", "Down", "Left", "Right")

    def test_opposite_keys_arrows(self):
        assert mmg._opposite_keys("arrows") == ("w", "a", "s", "d")

    def test_opposite_keys_unknown(self):
        assert mmg._opposite_keys("xyz") == ()

    def test_macos_grabber_available_matches_platform(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert mmg.macos_grabber_available() is True
        monkeypatch.setattr(sys, "platform", "linux")
        assert mmg.macos_grabber_available() is False


class TestRouteAll:
    def test_route_all_grabs_both_keysets(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd", route_all=True)
        for k in ("w", "a", "s", "d", "Up", "Down", "Left", "Right"):
            assert g.should_suppress(k) is True, k

    def test_route_all_ignores_canonical_for_grab_set(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("arrows", route_all=True)
        for k in ("w", "a", "s", "d", "Up", "Down", "Left", "Right"):
            assert g.should_suppress(k) is True, k

    def test_route_all_false_keeps_opposite_only(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")  # route_all defaults False
        assert g.should_suppress("Up") is True
        assert g.should_suppress("w") is False


class TestRouteKeysParity:
    def test_route_keys_kwarg_accepted_and_ignored(self, monkeypatch):
        # InputService passes route_keys= unconditionally when installing TTR
        # strict grabs, so install_grabs must accept the kwarg (signature
        # parity with the Win32/X11 grabbers) and behave exactly as if it were
        # omitted -- honoring the keymap union on darwin is a recorded
        # follow-up.
        monkeypatch.setattr(sys, "platform", "darwin")
        with_kwarg = mmg.MacOSMovementKeyGrabber()
        with_kwarg.prepare(_always_consume)
        with_kwarg.install_grabs(
            "wasd", passthrough_keysyms=["space"], route_all=True,
            route_keys={"w", "Alt_R"})
        without_kwarg = mmg.MacOSMovementKeyGrabber()
        without_kwarg.prepare(_always_consume)
        without_kwarg.install_grabs(
            "wasd", passthrough_keysyms=["space"], route_all=True)
        for k in ("w", "a", "s", "d", "Up", "Down", "Left", "Right",
                  "Alt_R", "space"):
            assert with_kwarg.should_suppress(k) == \
                without_kwarg.should_suppress(k), k
        # Ignored means keys outside the preset keysets stay unsuppressed even
        # when named in route_keys.
        assert with_kwarg.should_suppress("Alt_R") is False

    def test_route_keys_ignored_on_legacy_cc_path(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd", route_keys={"w", "Alt_R"})
        assert g.should_suppress("Up") is True
        assert g.should_suppress("w") is False
        assert g.should_suppress("Alt_R") is False


class TestOnGrabsChanged:
    def test_install_route_all_notifies_canonical(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        seen = []
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume, on_grabs_changed=seen.append)
        g.install_grabs("wasd", route_all=True)
        assert seen == ["wasd"]

    def test_install_unknown_canonical_notifies_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        seen = []
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume, on_grabs_changed=seen.append)
        g.install_grabs("xyz")  # opposite_keys -> () -> empty
        assert seen == [None]

    def test_install_opposite_only_notifies_canonical(self, monkeypatch):
        # The CC (route_all=False) path with a known canonical also reports it.
        monkeypatch.setattr(sys, "platform", "darwin")
        seen = []
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume, on_grabs_changed=seen.append)
        g.install_grabs("wasd")  # route_all defaults False
        assert seen == ["wasd"]

    def test_uninstall_notifies_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        seen = []
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume, on_grabs_changed=seen.append)
        g.install_grabs("wasd", route_all=True)
        seen.clear()
        g.uninstall_grabs()
        assert seen == [None]

    def test_stop_fires_callback_with_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        seen = []
        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume, on_grabs_changed=seen.append)
        g.install_grabs("wasd", route_all=True)
        seen.clear()
        g.stop()
        assert seen == [None]

    def test_callback_exception_is_shielded(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

        def boom(_canonical):
            raise RuntimeError("callback blew up")

        g = mmg.MacOSMovementKeyGrabber()
        g.prepare(_always_consume, on_grabs_changed=boom)
        g.install_grabs("wasd", route_all=True)
        g.uninstall_grabs()
        assert g.should_suppress("Up") is False

    def test_prepare_without_callback_still_works(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        g = mmg.MacOSMovementKeyGrabber()
        assert g.prepare(_always_consume) is True
        g.install_grabs("wasd", route_all=True)
        assert g.should_suppress("Up") is True


class TestCapabilityFlag:
    def test_needs_focused_passthrough_is_false(self):
        assert mmg.MacOSMovementKeyGrabber.needs_focused_passthrough is False


class TestBothKeysetsHelper:
    def test_both_keysets(self):
        assert mmg._both_keysets() == ("w", "a", "s", "d", "Up", "Down", "Left", "Right")
