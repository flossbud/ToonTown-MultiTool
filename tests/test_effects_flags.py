import importlib


def test_effects_disabled_reads_env(monkeypatch):
    import utils.effects_flags as ef
    monkeypatch.setenv("TTMT_NO_EFFECTS", "1")
    importlib.reload(ef)
    assert ef.effects_disabled() is True
    monkeypatch.delenv("TTMT_NO_EFFECTS", raising=False)
    importlib.reload(ef)
    assert ef.effects_disabled() is False
