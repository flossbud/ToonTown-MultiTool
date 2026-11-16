"""Startup UI scale: the fixed-size window must fit on laptop screens.

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_ui_scale.py -v
"""
import pytest

from utils import ui_scale
from utils.ui_scale import (
    DESIGN_H, DESIGN_W, ENV_ACTIVE, ENV_OVERRIDE, MARGIN, MIN_SCALE,
    apply_startup_ui_scale, compute_ui_scale, logical_size_win32,
    release_qt_env, xft_dpi_from_resources,
)


class TestComputeUiScale:
    @pytest.mark.parametrize("avail,expected", [
        ((1920, 1032), 1.0),     # 1080p at 100%
        ((2560, 1392), 1.0),     # 1440p
        ((1536, 816), 0.85),     # 1080p at 125%
        ((1280, 672), 0.70),     # 1080p at 150%: the reported case
        ((1366, 720), 0.75),     # 1366x768 at 100%
        ((1280, 752), 0.80),     # 1920x1200 at 150%
    ])
    def test_common_laptop_screens(self, avail, expected):
        assert compute_ui_scale(*avail) == expected

    @pytest.mark.parametrize("avail", [
        (1536, 816), (1280, 672), (1366, 720), (1280, 752), (1097, 576), (1440, 852),
    ])
    def test_scaled_window_fits_with_the_margin(self, avail):
        """In Qt's logical pixels the screen grows by 1/scale; the full
        design plus its margin must fit there."""
        scale = compute_ui_scale(*avail)
        if scale > MIN_SCALE:
            assert avail[1] / scale >= DESIGN_H + MARGIN
            assert avail[0] / scale >= DESIGN_W + MARGIN

    def test_never_enlarges(self):
        assert compute_ui_scale(7680, 4320) == 1.0

    def test_floor(self):
        assert compute_ui_scale(640, 400) == MIN_SCALE

    def test_narrow_screen_limits_by_width(self):
        assert compute_ui_scale(800, 2000) == 0.85

    @pytest.mark.parametrize("avail", [(0, 0), (-1, 800), (1280, 0)])
    def test_unknown_size_is_not_scaled(self, avail):
        assert compute_ui_scale(*avail) == 1.0


class TestWin32LogicalSize:
    def test_1080p_at_150_percent_with_taskbar(self):
        # Rects as a DPI-aware caller sees them (physical pixels).
        w, h = logical_size_win32(1920, 1080, 150, monitor_h=1080, work_h=1008,
                                  monitor_w=1920, work_w=1920)
        assert (round(w), round(h)) == (1280, 672)

    def test_same_answer_when_the_rects_are_virtualized(self):
        """A DPI-unaware caller gets the rects already divided by the scale.
        Only their ratio is used, so the result must not change."""
        w, h = logical_size_win32(1920, 1080, 150, monitor_h=720, work_h=672,
                                  monitor_w=1280, work_w=1280)
        assert (round(w), round(h)) == (1280, 672)

    def test_missing_monitor_info_uses_the_full_screen(self):
        assert logical_size_win32(1920, 1080, 125, monitor_h=0, work_h=0) == (1536.0, 864.0)


class TestXftDpi:
    def test_parses_dpi(self):
        assert xft_dpi_from_resources("Xcursor.size:\t24\nXft.dpi:\t144\nXft.rgba:\trgb\n") == 144.0

    @pytest.mark.parametrize("text", ["", "Xft.rgba:\trgb\n", "Xft.dpi:\tabc\n", "Xft.dpi:\t0\n"])
    def test_absent_or_bad(self, text):
        assert xft_dpi_from_resources(text) is None


class TestApplyStartupUiScale:
    def _probe(self, size):
        return lambda platform: size

    def test_small_screen_exports_the_scale_for_qt(self):
        env = {}
        d = apply_startup_ui_scale(env, "win32", self._probe((1280, 672)))
        assert d.scale == 0.70
        assert env["QT_SCALE_FACTOR"] == "0.7"
        assert env[ENV_ACTIVE] == "0.7"
        assert "1280x672" in d.stamp()

    def test_screen_that_fits_is_left_alone(self):
        env = {}
        d = apply_startup_ui_scale(env, "win32", self._probe((1920, 1032)))
        assert d.scale == 1.0
        assert env == {}

    def test_unmeasurable_screen_is_left_alone(self):
        env = {}
        assert apply_startup_ui_scale(env, "linux", self._probe(None)).scale == 1.0
        assert env == {}

    @pytest.mark.parametrize("qt_platform", ["wayland", "wayland-egl", "offscreen:configfile=x"])
    def test_linux_is_only_measured_through_x11(self, qt_platform):
        # The Linux probe reads X11; on another Qt platform its numbers are
        # not the ones Qt lays out with.
        env = {"QT_QPA_PLATFORM": qt_platform}
        d = apply_startup_ui_scale(env, "linux", self._probe((1280, 672)))
        assert d.scale == 1.0
        assert env == {"QT_QPA_PLATFORM": qt_platform}

    @pytest.mark.parametrize("qt_platform", ["", "xcb"])
    def test_linux_x11_small_screen_is_scaled(self, qt_platform):
        env = {"QT_QPA_PLATFORM": qt_platform} if qt_platform else {}
        assert apply_startup_ui_scale(env, "linux", self._probe((1280, 672))).scale == 0.7

    @pytest.mark.parametrize("var", ["QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS"])
    def test_users_own_qt_scale_wins(self, var):
        env = {var: "1.25"}
        d = apply_startup_ui_scale(env, "win32", self._probe((1280, 672)))
        assert d.scale == 1.0
        assert env == {var: "1.25"}

    @pytest.mark.parametrize("value", ["off", "OFF", "0", "1"])
    def test_override_off(self, value):
        env = {ENV_OVERRIDE: value}
        assert apply_startup_ui_scale(env, "win32", self._probe((1280, 672))).scale == 1.0
        assert "QT_SCALE_FACTOR" not in env

    def test_override_forces_a_scale(self):
        env = {ENV_OVERRIDE: "0.8"}
        d = apply_startup_ui_scale(env, "win32", self._probe((1920, 1032)))
        assert d.scale == 0.8
        assert env["QT_SCALE_FACTOR"] == "0.8"

    def test_bad_override_is_ignored_safely(self):
        env = {ENV_OVERRIDE: "banana"}
        assert apply_startup_ui_scale(env, "win32", self._probe((1280, 672))).scale == 1.0
        assert "QT_SCALE_FACTOR" not in env

    def test_helper_process_matches_its_parent(self):
        """The parent drops QT_SCALE_FACTOR after Qt reads it, so a helper
        process gets only ENV_ACTIVE and must not re-measure."""
        env = {ENV_ACTIVE: "0.7"}
        d = apply_startup_ui_scale(env, "win32", self._probe((1920, 1032)))
        assert d.scale == 0.7
        assert env["QT_SCALE_FACTOR"] == "0.7"

    def test_release_keeps_our_scale_out_of_child_processes(self):
        env = {}
        apply_startup_ui_scale(env, "win32", self._probe((1280, 672)))
        release_qt_env(env)
        assert "QT_SCALE_FACTOR" not in env
        assert env[ENV_ACTIVE] == "0.7"

    def test_release_leaves_a_user_set_qt_scale_alone(self):
        env = {"QT_SCALE_FACTOR": "1.25"}
        apply_startup_ui_scale(env, "win32", self._probe((1280, 672)))
        release_qt_env(env)
        assert env == {"QT_SCALE_FACTOR": "1.25"}

    def test_probe_failure_never_raises(self, monkeypatch):
        def boom():
            raise RuntimeError("no display")
        monkeypatch.setattr(ui_scale, "_probe_x11", boom)
        assert ui_scale.probe_available_logical_size("linux") is None
