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
