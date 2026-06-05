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
