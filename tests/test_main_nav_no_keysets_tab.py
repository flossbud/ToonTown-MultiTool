def test_nav_items_have_no_keysets_segment():
    src = open("main.py").read()
    block = src[src.index("nav_items = ["): src.index("]", src.index("nav_items = ["))]
    assert '"keysets"' not in block and "Keysets" not in block
    assert '"multitoon"' in block and '"settings"' in block

def test_no_keymaptab_import():
    src = open("main.py").read()
    assert "from tabs.keymap_tab import KeymapTab" not in src
    assert "self.keymap_tab" not in src

def test_keymap_tab_module_deleted():
    import os
    assert not os.path.exists("tabs/keymap_tab.py")

def test_view_logs_and_settings_indices_updated():
    src = open("main.py").read()
    assert "nav_select(3)" in src        # View Logs (debug) now index 3
    assert "nav_select(2)" in src        # Settings now index 2
    assert "currentIndex() == 3" in src  # debug-tab visibility guard now 3
