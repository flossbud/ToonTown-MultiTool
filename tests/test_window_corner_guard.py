from utils.window_corner_state import corner_state_signature, should_skip_restyle


def test_signature_changes_with_corner_and_theme():
    a = corner_state_signature(maximized=False, native_titlebar=False, theme_key="dark")
    b = corner_state_signature(maximized=True, native_titlebar=False, theme_key="dark")
    c = corner_state_signature(maximized=False, native_titlebar=False, theme_key="light")
    assert a != b      # maximize changes it
    assert a != c      # theme changes it


def test_skip_only_when_unchanged_and_not_forced():
    sig = corner_state_signature(False, False, "dark")
    assert should_skip_restyle(sig, sig, force=False) is True
    assert should_skip_restyle(sig, sig, force=True) is False      # theme path
    other = corner_state_signature(True, False, "dark")
    assert should_skip_restyle(sig, other, force=False) is False
    assert should_skip_restyle(None, sig, force=False) is False    # first apply
