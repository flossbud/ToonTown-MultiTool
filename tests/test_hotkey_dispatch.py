from utils.hotkey_dispatch import build_dispatch
from utils.settings_keys import CLICK_SYNC_ENABLED, HOTKEY_LAUNCH_SLOTS


class _Rec:
    def __init__(self):
        self.calls = []
    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name, a, k))


class _Mode(_Rec):
    def __init__(self, active=True):
        super().__init__()
        self.is_active = active


class _Settings:
    def __init__(self, data=None):
        self._d = dict(data or {})
        self.sets = []
    def get(self, key, default=None):
        return self._d.get(key, default)
    def set(self, key, value):
        self._d[key] = value
        self.sets.append((key, value))


class _Launch(_Rec):
    def game_of_account(self, aid):
        return "ttr" if aid == "acct-1" else None


def _dispatch(mode=None, settings=None, launch=None, tab=None, profiles=None):
    return build_dispatch(
        mode_controller=mode or _Mode(),
        launch_tab=launch or _Launch(),
        multitoon_tab=tab or _Rec(),
        settings_manager=settings or _Settings(),
        load_profile=profiles or (lambda idx: None),
    )


def test_every_registry_action_has_a_handler():
    from utils.hotkey_actions import ACTIONS
    d = _dispatch()
    assert set(d) == {a.id for a in ACTIONS}


def test_overlay_actions_guarded_by_float_active():
    mode = _Mode(active=False)
    d = _dispatch(mode=mode)
    d["overlay.toggle_cards"](); d["overlay.scale_up"]()
    assert mode.calls == []                       # framed -> no-op
    mode = _Mode(active=True)
    d = _dispatch(mode=mode)
    d["overlay.toggle_cards"](); d["overlay.scale_down"]()
    assert ("toggle_cards_hidden", (), {"animate": True}) in mode.calls
    assert ("set_scale_by_notches", (-1,), {}) in mode.calls


def test_launch_slot_uses_assignment_and_noops_unassigned():
    launch = _Launch()
    settings = _Settings({HOTKEY_LAUNCH_SLOTS: {"1": "acct-1"}})
    d = _dispatch(launch=launch, settings=settings)
    d["launch.slot_1"]()
    assert ("launch_account", ("ttr", "acct-1"), {}) in launch.calls
    d["launch.slot_2"]()                          # unassigned
    assert len([c for c in launch.calls if c[0] == "launch_account"]) == 1


def test_clicksync_flips_setting():
    settings = _Settings({CLICK_SYNC_ENABLED: False})
    d = _dispatch(settings=settings)
    d["clicksync.toggle"]()
    assert (CLICK_SYNC_ENABLED, True) in settings.sets


def test_service_keepalive_refresh_profiles_route():
    tab = _Rec()
    seen = []
    d = _dispatch(tab=tab, profiles=lambda idx: seen.append(idx))
    d["service.toggle"](); d["keepalive.toggle_all"](); d["app.refresh"]()
    names = [c[0] for c in tab.calls]
    assert names == ["toggle_service", "toggle_keep_alive_all",
                     "_on_refresh_requested"]
    d["profile.load_1"](); d["profile.load_5"]()
    assert seen == [0, 4]
