from utils.win32_elevation import build_relaunch_params, ELEVATION_RESTART_FLAG


def test_filters_one_shot_modes_and_adds_flag():
    argv = ["--self-check", "--apply-installer-config", "C:/x.json", "--debug"]
    params = build_relaunch_params(argv)
    assert "--self-check" not in params
    assert "--apply-installer-config" not in params
    assert "C:/x.json" not in params
    assert "--debug" in params
    assert ELEVATION_RESTART_FLAG in params


def test_idempotent_does_not_double_add_flag():
    params = build_relaunch_params([ELEVATION_RESTART_FLAG])
    assert params.count(ELEVATION_RESTART_FLAG) == 1


def test_filters_self_check_keyring():
    params = build_relaunch_params(["--self-check-keyring", "--debug"])
    assert "--self-check-keyring" not in params
    assert "--debug" in params


def test_filters_equals_form_of_apply_installer_config():
    params = build_relaunch_params(["--apply-installer-config=C:/x.json", "--debug"])
    assert not any(p.startswith("--apply-installer-config") for p in params)
    assert "--debug" in params


def test_value_flag_followed_by_another_flag_keeps_the_flag():
    # --apply-installer-config with NO value, immediately followed by another
    # flag, must drop only the one-shot flag and keep the unrelated flag.
    params = build_relaunch_params(["--apply-installer-config", "--debug"])
    assert not any(p.startswith("--apply-installer-config") for p in params)
    assert "--debug" in params


def test_value_flag_drops_space_separated_path_value():
    params = build_relaunch_params(["--apply-installer-config", "C:/x.json", "--debug"])
    assert "C:/x.json" not in params
    assert "--debug" in params


from utils import win32_elevation


def test_relaunch_success_quits_only_after_spawn(monkeypatch):
    monkeypatch.setattr(win32_elevation.sys, "platform", "win32")
    order = []
    monkeypatch.setattr(win32_elevation, "_shell_execute_runas",
                        lambda file, params, cwd: order.append("spawn") or True)
    ok = win32_elevation.relaunch_elevated(
        argv=["--debug"], on_success_shutdown=lambda: order.append("shutdown"))
    assert ok is True
    assert order == ["spawn", "shutdown"]   # quit only AFTER successful spawn


def test_relaunch_cancel_leaves_app_running(monkeypatch):
    monkeypatch.setattr(win32_elevation.sys, "platform", "win32")
    called = []
    monkeypatch.setattr(win32_elevation, "_shell_execute_runas",
                        lambda file, params, cwd: False)   # UAC canceled
    ok = win32_elevation.relaunch_elevated(
        argv=["--debug"], on_success_shutdown=lambda: called.append("shutdown"))
    assert ok is False
    assert called == []                     # nothing torn down on cancel


def test_relaunch_passes_filtered_params_with_flag(monkeypatch):
    monkeypatch.setattr(win32_elevation.sys, "platform", "win32")
    captured = {}
    def fake(file, params, cwd):
        captured["params"] = params
        return True
    monkeypatch.setattr(win32_elevation, "_shell_execute_runas", fake)
    win32_elevation.relaunch_elevated(argv=["--self-check", "--debug"],
                                      on_success_shutdown=lambda: None)
    assert "--self-check" not in captured["params"]
    assert "--debug" in captured["params"]
    assert win32_elevation.ELEVATION_RESTART_FLAG in captured["params"]


def test_relaunch_noop_off_windows(monkeypatch):
    monkeypatch.setattr(win32_elevation.sys, "platform", "linux")
    assert win32_elevation.relaunch_elevated(argv=["--debug"]) is False


def test_flush_settings_called_before_spawn(monkeypatch):
    monkeypatch.setattr(win32_elevation.sys, "platform", "win32")
    order = []
    monkeypatch.setattr(win32_elevation, "_shell_execute_runas",
                        lambda file, params, cwd: order.append("spawn") or True)
    win32_elevation.relaunch_elevated(
        argv=["--debug"], flush_settings=lambda: order.append("flush"),
        on_success_shutdown=lambda: order.append("shutdown"))
    assert order == ["flush", "spawn", "shutdown"]


# ── Elevation at startup ───────────────────────────────────────────────────

import pytest

MEDIUM, HIGH, LOW = 0x2000, 0x3000, 0x1000
LIMITED, FULL, DEFAULT = 3, 2, 1


def _decide(argv=(), env=None, platform="win32", integrity=MEDIUM, etype=LIMITED):
    return win32_elevation.decide_startup_elevation(
        platform, list(argv), env or {}, lambda: integrity, lambda: etype)


def test_unelevated_administrator_is_asked():
    assert _decide().state == win32_elevation.PROMPT


def test_already_elevated_is_not_asked():
    # Covers UAC switched off too: an administrator is then high integrity.
    assert _decide(integrity=HIGH, etype=FULL).state == win32_elevation.ELEVATED
    assert _decide(integrity=HIGH, etype=DEFAULT).state == win32_elevation.ELEVATED


def test_other_platforms_are_never_asked_and_read_nothing():
    def boom():
        raise AssertionError("read off Windows")
    for plat in ("linux", "darwin"):
        d = win32_elevation.decide_startup_elevation(plat, [], {}, boom, boom)
        assert d.state == win32_elevation.SKIPPED


@pytest.mark.parametrize("argv", [
    ["--ghost-renderer"], ["--self-check"], ["--self-check-keyring"],
    ["--apply-installer-config", "--check-updates=1"],
    ["--apply-installer-config=C:/x.json"],
])
def test_helper_and_one_shot_modes_are_never_asked(argv):
    def boom():
        raise AssertionError("helper modes must not even read the token")
    d = win32_elevation.decide_startup_elevation("win32", argv, {}, boom, boom)
    assert d.state == win32_elevation.SKIPPED


def test_relaunched_copy_that_is_still_unelevated_does_not_ask_again():
    d = _decide(argv=[ELEVATION_RESTART_FLAG])
    assert d.state == win32_elevation.SKIPPED


def test_standard_account_is_not_asked():
    # Elevating would mean another user's password and another user's profile.
    assert _decide(etype=DEFAULT).state == win32_elevation.SKIPPED
    assert _decide(etype=None).state == win32_elevation.SKIPPED


@pytest.mark.parametrize("integrity", [None, LOW])
def test_unknown_or_sandboxed_integrity_is_not_asked(integrity):
    assert _decide(integrity=integrity).state == win32_elevation.SKIPPED


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_env_opt_out(value):
    assert _decide(env={"TTMT_NO_ELEVATE": value}).state == win32_elevation.SKIPPED


@pytest.mark.parametrize("value", ["", "0", "no"])
def test_env_opt_out_needs_a_truthy_value(value):
    assert _decide(env={"TTMT_NO_ELEVATE": value}).state == win32_elevation.PROMPT


@pytest.fixture
def unelevated_admin(monkeypatch):
    from utils import win32_integrity
    monkeypatch.setattr(win32_integrity, "own_integrity_level", lambda: MEDIUM)
    monkeypatch.setattr(win32_integrity, "own_elevation_type", lambda: LIMITED)
    monkeypatch.setattr(win32_elevation, "_startup_result", None)


def test_granted_prompt_relaunches_with_the_loop_guard(monkeypatch, unelevated_admin):
    captured = {}
    def fake(file, params, cwd):
        captured["params"] = params
        return True
    monkeypatch.setattr(win32_elevation, "_shell_execute_runas", fake)
    r = win32_elevation.elevate_at_startup(argv=["--debug"], environ={}, platform="win32")
    assert r.state == win32_elevation.RELAUNCHED
    assert "--debug" in captured["params"]
    assert ELEVATION_RESTART_FLAG in captured["params"]
    assert win32_elevation.startup_prompt_declined() is False


def test_declined_prompt_carries_on_and_is_remembered(monkeypatch, unelevated_admin):
    monkeypatch.setattr(win32_elevation, "_shell_execute_runas", lambda *a: False)
    r = win32_elevation.elevate_at_startup(argv=[], environ={}, platform="win32")
    assert r.state == win32_elevation.DECLINED
    assert win32_elevation.startup_prompt_declined() is True
    assert r.stamp() == "[Elevation] declined (administrator prompt was declined)"


def test_no_prompt_when_not_needed(monkeypatch, unelevated_admin):
    monkeypatch.setattr(win32_elevation, "_shell_execute_runas",
                        lambda *a: (_ for _ in ()).throw(AssertionError("prompted")))
    for kwargs in (dict(argv=["--self-check"], environ={}, platform="win32"),
                   dict(argv=[], environ={"TTMT_NO_ELEVATE": "1"}, platform="win32"),
                   dict(argv=[], environ={}, platform="linux")):
        r = win32_elevation.elevate_at_startup(**kwargs)
        assert r.state == win32_elevation.SKIPPED
        assert win32_elevation.startup_prompt_declined() is False


def test_a_failing_check_never_stops_the_launch(monkeypatch, unelevated_admin):
    from utils import win32_integrity
    monkeypatch.setattr(win32_integrity, "own_integrity_level",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r = win32_elevation.elevate_at_startup(argv=[], environ={}, platform="win32")
    assert r.state == win32_elevation.SKIPPED


# ── Environment forwarded to the elevated copy ─────────────────────────────

def test_ttmt_variables_survive_the_relaunch():
    parent = {"TTMT_CONFIG_DIR": r"C:\cfg dir", "TTMT_UI_SCALE": "off", "PATH": "x"}
    param = win32_elevation.env_forward_param(parent)
    argv = ["main.py", "--debug", param, ELEVATION_RESTART_FLAG]
    child = {}
    assert win32_elevation.restore_forwarded_env(argv, child) == 2
    assert child == {"TTMT_CONFIG_DIR": r"C:\cfg dir", "TTMT_UI_SCALE": "off"}
    assert argv == ["main.py", "--debug", ELEVATION_RESTART_FLAG]   # flag consumed


def test_nothing_to_forward_adds_no_parameter():
    assert win32_elevation.env_forward_param({"PATH": "x", "HOME": "y"}) is None


def test_per_process_scale_is_not_handed_down():
    param = win32_elevation.env_forward_param(
        {"TTMT_UI_SCALE_ACTIVE": "0.8", "TTMT_INPUT_TRACE": "1"})
    child = {}
    win32_elevation.restore_forwarded_env(["main.py", param], child)
    assert child == {"TTMT_INPUT_TRACE": "1"}


def test_only_ttmt_names_can_be_restored():
    import base64, json
    evil = base64.urlsafe_b64encode(json.dumps(
        {"PATH": "C:/evil", "PYTHONPATH": "C:/evil", "TTMT_OK": "1", "TTMT_N": 5}
    ).encode()).decode()
    child = {}
    win32_elevation.restore_forwarded_env(["main.py", f"--elevation-env={evil}"], child)
    assert child == {"TTMT_OK": "1"}


@pytest.mark.parametrize("junk", ["--elevation-env=", "--elevation-env=!!!", "--elevation-env=bm90IGpzb24="])
def test_garbage_is_ignored_and_removed(junk):
    argv, child = ["main.py", junk, "--debug"], {}
    assert win32_elevation.restore_forwarded_env(argv, child) == 0
    assert argv == ["main.py", "--debug"] and child == {}


def test_oversized_environment_is_not_forwarded():
    assert win32_elevation.env_forward_param({"TTMT_BIG": "x" * 20000}) is None


def test_stale_forwarded_env_is_not_passed_on_twice():
    params = build_relaunch_params(["--elevation-env=abc", "--debug"])
    assert params == ["--debug", ELEVATION_RESTART_FLAG]


def test_startup_relaunch_carries_the_environment(monkeypatch, unelevated_admin):
    captured = {}
    monkeypatch.setattr(win32_elevation, "_shell_execute_runas",
                        lambda file, params, cwd: captured.update(params=params) or True)
    win32_elevation.elevate_at_startup(argv=[], environ={"TTMT_CONFIG_DIR": "C:/c"}, platform="win32")
    child = {}
    win32_elevation.restore_forwarded_env(["main.py"] + captured["params"], child)
    assert child == {"TTMT_CONFIG_DIR": "C:/c"}
