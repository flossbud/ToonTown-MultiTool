from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

class _FakeSettings:        # duck-types SettingsManager
    def __init__(self, d=None): self._d = dict(d or {})
    def get(self, k, default=None): return self._d.get(k, default)
    def set(self, k, v): self._d[k] = v


from utils.saved_colors import SavedColorsStore

def test_save_clear_and_cap_at_six():
    s = _FakeSettings()
    store = SavedColorsStore(s)
    assert store.get() == []
    for hex_ in ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666"]:
        store.save(hex_)
    assert store.get() == ["#111111","#222222","#333333","#444444","#555555","#666666"]
    store.save("#777777")                      # 7th is dropped (cap 6)
    assert store.get() == ["#111111","#222222","#333333","#444444","#555555","#666666"]
    store.save("#222222")                      # duplicate is a no-op
    assert store.get().count("#222222") == 1
    store.clear(1)                             # remove index 1
    assert store.get() == ["#111111","#333333","#444444","#555555","#666666"]

def test_persists_through_settings():
    s = _FakeSettings()
    SavedColorsStore(s).save("#abcdef")
    assert s.get("saved_colors") == ["#abcdef"]
