import os
import tempfile
from unittest.mock import patch

import pytest

from utils.profile_manager import ProfileManager, NUM_PROFILES, DEFAULT_NAMES


@pytest.fixture
def pm(tmp_path):
    """Create a ProfileManager that stores its config in a temp directory."""
    fake_home = str(tmp_path)
    with patch("utils.profile_manager.os.path.expanduser", return_value=fake_home):
        mgr = ProfileManager()
    return mgr


class TestDefaultProfiles:
    def test_correct_number_of_profiles(self, pm):
        names = pm.get_all_names()
        assert len(names) == NUM_PROFILES

    def test_default_names(self, pm):
        for i in range(NUM_PROFILES):
            assert pm.get_name(i) == f"Profile {i + 1}"

    def test_default_profile_structure(self, pm):
        for i in range(NUM_PROFILES):
            p = pm.get_profile(i)
            assert p.name == f"Profile {i + 1}"
            assert p.enabled_toons == [False, False, False, False]
            assert p.movement_modes == ["Default", "Default", "Default", "Default"]


class TestSaveAndLoad:
    def test_save_profile_persists_data(self, tmp_path):
        fake_home = str(tmp_path)
        with patch("utils.profile_manager.os.path.expanduser", return_value=fake_home):
            pm1 = ProfileManager()
            pm1.save_profile(0, [True, False, True, False], ["Sprint", "Default", "Jump", "Default"])

        # Create a second manager reading from the same path
        with patch("utils.profile_manager.os.path.expanduser", return_value=fake_home):
            pm2 = ProfileManager()

        p = pm2.get_profile(0)
        assert p.enabled_toons == [True, False, True, False]
        assert p.movement_modes == ["Sprint", "Default", "Jump", "Default"]

    def test_save_preserves_name(self, pm):
        pm.rename_profile(0, "MyProfile")
        pm.save_profile(0, [True, True, True, True], ["Sprint", "Sprint", "Sprint", "Sprint"])
        p = pm.get_profile(0)
        assert p.name == "MyProfile"
        assert p.enabled_toons == [True, True, True, True]


class TestRenameProfile:
    def test_rename_profile(self, pm):
        pm.rename_profile(2, "Boss Run")
        assert pm.get_name(2) == "Boss Run"

    def test_rename_empty_string_falls_back_to_default(self, pm):
        pm.rename_profile(1, "Temp Name")
        assert pm.get_name(1) == "Temp Name"
        pm.rename_profile(1, "")
        assert pm.get_name(1) == DEFAULT_NAMES[1]

    def test_rename_whitespace_only_falls_back_to_default(self, pm):
        pm.rename_profile(3, "   ")
        assert pm.get_name(3) == DEFAULT_NAMES[3]


class TestMoveUp:
    def test_move_up_swaps_profiles(self, pm):
        pm.rename_profile(0, "A")
        pm.rename_profile(1, "B")
        pm.move_up(1)
        assert pm.get_name(0) == "B"
        assert pm.get_name(1) == "A"

    def test_move_up_index_zero_is_noop(self, pm):
        pm.rename_profile(0, "First")
        pm.move_up(0)
        assert pm.get_name(0) == "First"


class TestMoveDown:
    def test_move_down_swaps_profiles(self, pm):
        pm.rename_profile(2, "X")
        pm.rename_profile(3, "Y")
        pm.move_down(2)
        assert pm.get_name(2) == "Y"
        assert pm.get_name(3) == "X"

    def test_move_down_last_index_is_noop(self, pm):
        last = NUM_PROFILES - 1
        pm.rename_profile(last, "Last")
        pm.move_down(last)
        assert pm.get_name(last) == "Last"
