"""Tests for utils.win32_movement_grabber."""

from __future__ import annotations

import sys
import pytest

from utils import win32_movement_grabber as wmg


def _always_consume(_keysym: str) -> bool:
    return True


def _never_consume(_keysym: str) -> bool:
    return False


class TestPrepare:
    def test_prepare_returns_false_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        g = wmg.Win32MovementKeyGrabber()
        assert g.prepare(_always_consume) is False

    def test_prepare_returns_true_on_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        assert g.prepare(_always_consume) is True

    def test_should_suppress_false_without_install(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        assert g.should_suppress("Up") is False
        assert g.should_suppress("w") is False


class TestInstallGrabs:
    def test_install_wasd_suppresses_arrows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        assert g.should_suppress("Up") is True
        assert g.should_suppress("Down") is True
        assert g.should_suppress("Left") is True
        assert g.should_suppress("Right") is True
        assert g.should_suppress("w") is False
        assert g.should_suppress("a") is False

    def test_install_arrows_suppresses_wasd(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("arrows")
        assert g.should_suppress("w") is True
        assert g.should_suppress("a") is True
        assert g.should_suppress("s") is True
        assert g.should_suppress("d") is True
        assert g.should_suppress("Up") is False

    def test_install_unknown_canonical_is_noop(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("xyz")
        assert g.should_suppress("Up") is False
        assert g.should_suppress("w") is False

    def test_install_idempotent_for_same_canonical(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        g.install_grabs("wasd")
        assert g.should_suppress("Up") is True

    def test_install_switch_canonical_replaces_set(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        g.install_grabs("arrows")
        assert g.should_suppress("Up") is False
        assert g.should_suppress("w") is True

    def test_passthrough_keysyms_param_accepted_but_ignored(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd", passthrough_keysyms=["Up", "Down"])
        assert g.should_suppress("Up") is True
        assert g.should_suppress("Down") is True


class TestUninstallGrabs:
    def test_uninstall_clears_suppression(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        g.uninstall_grabs()
        assert g.should_suppress("Up") is False

    def test_uninstall_without_install_is_noop(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.uninstall_grabs()
        assert g.should_suppress("Up") is False


class TestShouldConsumeGating:
    def test_should_consume_false_blocks_suppression(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_never_consume)
        g.install_grabs("wasd")
        assert g.should_suppress("Up") is False

    def test_should_consume_raises_returns_false(self, monkeypatch):
        def boom(_k: str) -> bool:
            raise RuntimeError("oops")

        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(boom)
        g.install_grabs("wasd")
        assert g.should_suppress("Up") is False


class TestStop:
    def test_stop_clears_grabs(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.install_grabs("wasd")
        g.stop()
        assert g.should_suppress("Up") is False

    def test_stop_is_idempotent(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        g = wmg.Win32MovementKeyGrabber()
        g.prepare(_always_consume)
        g.stop()
        g.stop()  # second call must not raise


class TestModuleHelpers:
    def test_opposite_keys_wasd(self):
        assert wmg._opposite_keys("wasd") == ("Up", "Down", "Left", "Right")

    def test_opposite_keys_arrows(self):
        assert wmg._opposite_keys("arrows") == ("w", "a", "s", "d")

    def test_opposite_keys_unknown(self):
        assert wmg._opposite_keys("xyz") == ()

    def test_win32_grabber_available_matches_platform(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert wmg.win32_grabber_available() is True
        monkeypatch.setattr(sys, "platform", "linux")
        assert wmg.win32_grabber_available() is False
